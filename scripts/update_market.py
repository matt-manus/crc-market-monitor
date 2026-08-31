#!/usr/bin/env python3
"""CRC Market Monitor daily data updater.

This script is intentionally server-side only: its API key is read from the
GitHub Actions secret environment and never enters the website. It maintains a
rolling private state, calculates the dashboard aggregates, applies quality
gates, then atomically writes site/data/latest.json only when verified.

Massive endpoint paths are supplied as the Polygon-compatible REST endpoints
documented for the account. Confirm plan availability and permitted personal use
before the first bootstrap run; no provider data is fetched without a user key.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "market-state.json"
OUTPUT_PATH = ROOT / "site" / "data" / "latest.json"
OVERRIDES_PATH = ROOT / "config" / "security-overrides.json"
WINDOW_DAYS = 84
MIN_EXPECTED_UNIVERSE = 500
EXCLUDED_TYPES = {"ETF", "ETN", "FUND", "MF", "WARRANT", "WT", "RIGHT", "RT", "UNIT", "PFD", "PREF"}
MIN_SECONDS_BETWEEN_REQUESTS = 12.5
LAST_REQUEST_AT = 0.0


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def environment() -> tuple[str | None, str]:
    return os.environ.get("MASSIVE_API_KEY"), os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com").rstrip("/")


def get_json(base_url: str, path_or_url: str, api_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    global LAST_REQUEST_AT
    url = path_or_url if path_or_url.startswith("http") else f"{base_url}{path_or_url}"
    query = {"apiKey": api_key, **(params or {})}
    for attempt in range(4):
        delay = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        response = requests.get(url, params=query, timeout=55)
        LAST_REQUEST_AT = time.monotonic()
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        retry_after = response.headers.get("Retry-After")
        try:
            cooldown = max(float(retry_after), 60.0) if retry_after else 60.0
        except ValueError:
            cooldown = 60.0
        print(f"Rate limit reached; waiting {cooldown:.0f}s before retry {attempt + 1}/3…")
        time.sleep(cooldown)
    response.raise_for_status()
    return {}


def fetch_grouped_bars(base_url: str, api_key: str, session: date) -> list[dict[str, Any]]:
    """Fetch one U.S. market daily aggregate session using the provider's grouped-bars API."""
    payload = get_json(base_url, f"/v2/aggs/grouped/locale/us/market/stocks/{session.isoformat()}", api_key, {"adjusted": "true"})
    return payload.get("results") or []


def fetch_metadata(base_url: str, api_key: str) -> dict[str, dict[str, Any]]:
    """Retrieve the active U.S. stock reference list, following pagination."""
    metadata: dict[str, dict[str, Any]] = {}
    path: str | None = "/v3/reference/tickers"
    parameters: dict[str, Any] | None = {"market": "stocks", "active": "true", "limit": 1000}
    while path:
        page = get_json(base_url, path, api_key, parameters)
        parameters = None
        for item in page.get("results") or []:
            ticker = item.get("ticker")
            if ticker:
                metadata[ticker] = {"type": (item.get("type") or "").upper(), "name": item.get("name") or ticker}
        path = page.get("next_url")
    return metadata


def session_candidates(end: date, bootstrap: bool) -> list[date]:
    if not bootstrap:
        return [end]
    candidates: list[date] = []
    cursor = end
    # Calendar days deliberately exceed 63 sessions; empty holiday responses are ignored.
    while len(candidates) < 78:
        if cursor.weekday() < 5:
            candidates.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(candidates))


def ingest_bars(state: dict[str, Any], raw_bars: list[dict[str, Any]], session: date, keep: set[str]) -> None:
    """Keep only the final-session candidate universe plus SPY/QQQ history.

    The grouped endpoint contains every U.S. symbol. Persisting all of it would
    make a single bootstrap state excessively large, despite only about 2,400
    securities being relevant to this dashboard's daily eligibility rules.
    """
    for raw in raw_bars:
        normalized = normalize_bar(raw, session)
        if not normalized:
            continue
        ticker, bar = normalized
        if ticker not in keep:
            continue
        series = [row for row in state["bars"].get(ticker, []) if row["date"] != bar["date"]]
        series.append(bar)
        state["bars"][ticker] = sorted(series, key=lambda row: row["date"])[-WINDOW_DAYS:]


def normalize_bar(raw: dict[str, Any], session: date) -> tuple[str, dict[str, Any]] | None:
    ticker = raw.get("T") or raw.get("ticker")
    close, high, low, volume = raw.get("c"), raw.get("h"), raw.get("l"), raw.get("v")
    if not ticker or any(value is None for value in (close, high, low, volume)):
        return None
    if close <= 0 or high < low or volume < 0:
        return None
    return ticker, {"date": session.isoformat(), "o": raw.get("o"), "h": high, "l": low, "c": close, "v": volume}


def is_allowed(ticker: str, metadata: dict[str, Any], overrides: dict[str, Any]) -> bool:
    if ticker in set(overrides.get("excludedTickers") or []):
        return False
    security_type = (metadata.get(ticker, {}).get("type") or "").upper()
    return security_type not in EXCLUDED_TYPES


def ema(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    result = mean(values[:span])
    multiplier = 2 / (span + 1)
    for value in values[span:]:
        result = value * multiplier + result * (1 - multiplier)
    return result


def atr(bars: list[dict[str, Any]], span: int = 14) -> float | None:
    if len(bars) < span + 1:
        return None
    ranges = []
    for previous, current in zip(bars, bars[1:]):
        ranges.append(max(current["h"] - current["l"], abs(current["h"] - previous["c"]), abs(current["l"] - previous["c"])))
    return mean(ranges[-span:]) if len(ranges) >= span else None


def security_metric(bars: list[dict[str, Any]]) -> dict[str, float | None]:
    closes = [bar["c"] for bar in bars]
    if len(closes) < 2:
        return {"return1d": None, "sma20": None, "sma50": None, "ema50": None, "atr14": None, "return63d": None}
    return {
        "return1d": closes[-1] / closes[-2] - 1,
        "sma20": mean(closes[-20:]) if len(closes) >= 20 else None,
        "sma50": mean(closes[-50:]) if len(closes) >= 50 else None,
        "ema50": ema(closes, 50),
        "atr14": atr(bars),
        "return63d": closes[-1] / closes[-64] - 1 if len(closes) >= 64 else None,
    }


def summarize(state: dict[str, Any], session: str, overrides: dict[str, Any]) -> dict[str, Any] | None:
    bars_by_ticker = state["bars"]
    metadata = state.get("metadata") or {}
    pool: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for ticker, bars in bars_by_ticker.items():
        if not bars or bars[-1]["date"] != session or not is_allowed(ticker, metadata, overrides):
            continue
        latest = bars[-1]
        if latest["c"] < 5 or latest["v"] < 300_000:
            continue
        metric = security_metric(bars)
        if metric["return1d"] is None:
            continue
        pool.append((ticker, latest, metric))
    if len(pool) < MIN_EXPECTED_UNIVERSE:
        print(f"QUALITY GATE: candidate pool is {len(pool)}, lower than expected {MIN_EXPECTED_UNIVERSE}; retain previous published result.")
        return None

    up4 = sum(metric["return1d"] >= 0.04 for _, _, metric in pool)
    down4 = sum(metric["return1d"] <= -0.04 for _, _, metric in pool)
    sma20_valid = [metric for _, _, metric in pool if metric["sma20"] is not None]
    sma50_valid = [metric for _, _, metric in pool if metric["sma50"] is not None]
    leaders = [(ticker, latest, metric) for ticker, latest, metric in pool if latest["c"] * latest["v"] >= 5_000_000 and metric["return63d"] is not None and metric["return63d"] >= 0.20]

    def etf_atr_distance(ticker: str) -> float | None:
        bars = bars_by_ticker.get(ticker, [])
        if not bars or bars[-1]["date"] != session:
            return None
        metric = security_metric(bars)
        if not metric["ema50"] or not metric["atr14"]:
            return None
        return (bars[-1]["c"] - metric["ema50"]) / metric["atr14"]

    industry_pool: dict[str, int] = defaultdict(int)
    industry_leaders: dict[str, int] = defaultdict(int)
    for ticker, _, _ in pool:
        industry_pool[overrides.get("industryOverrides", {}).get(ticker, "Unclassified")] += 1
    for ticker, _, _ in leaders:
        industry_leaders[overrides.get("industryOverrides", {}).get(ticker, "Unclassified")] += 1
    leader_n = len(leaders)
    industry = []
    for name, count in industry_leaders.items():
        pool_n = industry_pool[name]
        leader_share = count / leader_n * 100 if leader_n else 0
        pool_share = pool_n / len(pool) * 100
        industry.append({"name": name, "leaderN": count, "leaderShare": round(leader_share, 1), "poolShare": round(pool_share, 1), "penetration": round(count / pool_n * 100, 1), "excess": round(leader_share - pool_share, 1)})
    industry.sort(key=lambda row: row["leaderN"], reverse=True)

    return {
        "date": session,
        "up4": up4,
        "down4": down4,
        "sma20Pct": round(sum(bar["c"] > metric["sma20"] for _, bar, metric in pool if metric["sma20"] is not None) / len(sma20_valid) * 100, 1) if sma20_valid else None,
        "sma20N": len(sma20_valid),
        "sma50Pct": round(sum(bar["c"] > metric["sma50"] for _, bar, metric in pool if metric["sma50"] is not None) / len(sma50_valid) * 100, 1) if sma50_valid else None,
        "sma50N": len(sma50_valid),
        "spyAtr": round(etf_atr_distance("SPY"), 2) if etf_atr_distance("SPY") is not None else None,
        "qqqAtr": round(etf_atr_distance("QQQ"), 2) if etf_atr_distance("QQQ") is not None else None,
        "mliReturn": round(mean(metric["return1d"] for _, _, metric in leaders) * 100, 2) if leaders else None,
        "mliUpPct": round(sum(metric["return1d"] > 0 for _, _, metric in leaders) / leader_n * 100, 1) if leaders else None,
        "mliN": leader_n,
        "universeN": len(pool),
        "sp500Close": None,
        "industry": industry[:20],
    }


def build_output(state: dict[str, Any]) -> dict[str, Any]:
    summaries = state.get("summaries") or []
    latest = summaries[-1]
    history = []
    for summary in reversed(summaries[-20:]):
        history.append({
            "date": summary["date"][5:], "up4": summary["up4"], "down4": summary["down4"], "sma20Pct": summary["sma20Pct"], "sma50Pct": summary["sma50Pct"], "spyAtr": summary["spyAtr"], "qqqAtr": summary["qqqAtr"], "mliReturn": summary["mliReturn"], "mliUpPct": summary["mliUpPct"], "mliN": summary["mliN"], "universeN": summary["universeN"], "sp500Close": summary["sp500Close"]
        })
    trend = [round(summary["mliN"] / summary["universeN"] * 100, 1) for summary in summaries[-126:] if summary["universeN"]]
    return {"status": "live", "asOf": latest["date"], "updatedAt": datetime.now(timezone.utc).isoformat(), "source": "個人 Massive 資料服務 · 私人用途", "message": "", "summary": latest, "history": history, "industry": latest.get("industry") or [], "leaderTrend": trend}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--refresh-metadata", action="store_true")
    args = parser.parse_args()
    api_key, base_url = environment()
    if not api_key:
        print("SAFE EXIT: MASSIVE_API_KEY is not configured. Add it to GitHub Secrets; existing published output is untouched.")
        return 0

    state = load_json(STATE_PATH, {"bars": {}, "metadata": {}, "summaries": [], "lastMetadataRefresh": None, "schemaVersion": 1})
    overrides = load_json(OVERRIDES_PATH, {"excludedTickers": [], "industryOverrides": {}})
    today = datetime.now(timezone.utc).date()
    metadata_is_old = not state.get("lastMetadataRefresh") or date.fromisoformat(state["lastMetadataRefresh"]) < today - timedelta(days=7)
    if args.bootstrap or args.refresh_metadata or metadata_is_old:
        print("Refreshing ticker reference metadata…")
        state["metadata"] = fetch_metadata(base_url, api_key)
        state["lastMetadataRefresh"] = today.isoformat()

    candidates = session_candidates(args.as_of, args.bootstrap)
    if args.bootstrap:
        # Resolve the latest actual market session first, then build history only
        # for securities that meet that session's price/volume screen.
        current_raw: list[dict[str, Any]] = []
        target_date: date | None = None
        for candidate in reversed(candidates):
            try:
                current_raw = fetch_grouped_bars(base_url, api_key, candidate)
            except requests.RequestException as error:
                print(f"Provider request failed for {candidate}: {error}")
                continue
            if current_raw:
                target_date = candidate
                break
        if target_date is None:
            print("SAFE EXIT: no completed provider session was returned; existing published output is untouched.")
            return 0
        keep = {"SPY", "QQQ"}
        for raw in current_raw:
            ticker = raw.get("T") or raw.get("ticker")
            if ticker and (raw.get("c") or 0) >= 5 and (raw.get("v") or 0) >= 300_000:
                keep.add(ticker)
        ingest_bars(state, current_raw, target_date, keep)
        fetched_sessions: list[str] = [target_date.isoformat()]
        requested_sessions = [candidate for candidate in candidates if candidate < target_date]
    else:
        fetched_sessions = []
        requested_sessions = candidates

    for candidate in requested_sessions:
        try:
            raw_bars = fetch_grouped_bars(base_url, api_key, candidate)
        except requests.RequestException as error:
            print(f"Provider request failed for {candidate}: {error}")
            if not args.bootstrap:
                return 1
            continue
        if not raw_bars:
            continue
        if args.bootstrap:
            ingest_bars(state, raw_bars, candidate, keep)
        else:
            daily_keep = {"SPY", "QQQ"}
            for raw in raw_bars:
                ticker = raw.get("T") or raw.get("ticker")
                if ticker and (raw.get("c") or 0) >= 5 and (raw.get("v") or 0) >= 300_000:
                    daily_keep.add(ticker)
            ingest_bars(state, raw_bars, candidate, daily_keep)
        fetched_sessions.append(candidate.isoformat())

    if not fetched_sessions:
        print("SAFE EXIT: no completed provider session was returned; existing published output is untouched.")
        return 0
    target_session = fetched_sessions[-1]
    summary = summarize(state, target_session, overrides)
    if summary is None:
        return 0
    state["summaries"] = [item for item in state.get("summaries", []) if item["date"] != target_session] + [summary]
    state["summaries"] = sorted(state["summaries"], key=lambda item: item["date"])[-252:]
    write_json_atomic(STATE_PATH, state)
    write_json_atomic(OUTPUT_PATH, build_output(state))
    print(f"Published verified CRC market summary for {target_session}: {summary['universeN']} securities, {summary['mliN']} leaders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
