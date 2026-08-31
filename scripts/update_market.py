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
SIC_CACHE_PATH = ROOT / "data" / "sic-candidates-v1.json"
SIC_TAXONOMY_PATH = ROOT / "config" / "crc-sic-taxonomy-v1.json"
WINDOW_DAYS = 84
BENCHMARK_WINDOW_DAYS = 320
MIN_EXPECTED_UNIVERSE = 500
# Polygon-compatible reference data distinguishes common stock (CS) and ADR
# common stock (ADRC) from exchange-traded products such as ETV and ETS.
# The reference methodology admits only these two classes.
ALLOWED_SECURITY_TYPES = {"CS", "ADRC"}
MIN_SECONDS_BETWEEN_REQUESTS = 12.5
LAST_REQUEST_AT = 0.0
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true"


def classify_industry(raw_industry: str | None, raw_sector: str | None) -> str:
    """Map Nasdaq's live industry labels into compact display buckets.

    This is a transparent display taxonomy, rather than a claim that Nasdaq
    labels are SEC SIC values. Unknown labels remain Unclassified.
    """
    text = f"{raw_industry or ''} {raw_sector or ''}".upper()
    groups = (
        ("Software & IT Services", ("COMPUTER SOFTWARE", "EDP SERVICES", "INTERNET", "IT SERVICES", "TECHNOLOGY SERVICES")),
        ("Biotech & Pharma", ("BIOTECH", "PHARMACEUT", "MEDICAL SPECIAL", "LIFE SCIENCE")),
        ("Instruments & Medical Devices", ("MEDICAL/DENTAL", "MEDICAL EQUIPMENT", "LABORATORY", "DIAGNOSTIC", "ELECTROMEDICAL")),
        ("Insurance", ("INSURANCE",)),
        ("Banks & Financial Services", ("BANK", "SAVINGS", "INVESTMENT BANK", "FINANCE", "CREDIT", "ASSET MANAGEMENT", "SECURITIES")),
        ("Health Care Services", ("HOSPITAL", "HEALTH CARE", "NURSING", "CARE SERVICES")),
        ("Retail", ("RETAIL", "CATALOG", "DEPARTMENT STORE")),
        ("Metals & Coal Mining", ("MINING", "COAL", "METAL", "GOLD", "SILVER")),
        ("Petroleum Refining", ("PETROLEUM", "OIL", "NATURAL GAS", "ENERGY")),
        ("Transportation & Logistics", ("TRANSPORT", "TRUCK", "SHIPPING", "AIR FREIGHT", "RAILROAD", "MARINE")),
        ("Computer Hardware", ("COMPUTER HARDWARE", "SEMICONDUCTOR", "ELECTRONIC COMPONENT", "ELECTRONICS")),
        ("Industrial Materials", ("CHEMICAL", "STEEL", "BUILDING MATERIAL", "CEMENT", "LUMBER", "PACKAGING")),
        ("Wholesale", ("WHOLESALE",)),
        ("Consumer Products", ("APPAREL", "FOOD", "BEVERAGE", "TOBACCO", "TEXTILE", "COSMETIC", "HOUSEHOLD")),
        ("Telecom & Media", ("TELECOMMUNICATION", "BROADCAST", "PUBLISHING", "ENTERTAINMENT", "MEDIA")),
        ("Real Estate", ("REAL ESTATE", "REIT")),
        ("Utilities", ("ELECTRIC UTIL", "GAS UTIL", "WATER UTIL", "UTILITY")),
        ("Business Services", ("BUSINESS SERVICE", "PROFESSIONAL SERVICE", "CONSULTING")),
    )
    for label, needles in groups:
        if any(needle in text for needle in needles):
            return label
    return "Unclassified"


def fetch_nasdaq_industry_map() -> dict[str, str]:
    """Fetch public Nasdaq screener labels for transparent display grouping."""
    response = requests.get(
        NASDAQ_SCREENER_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    rows = response.json().get("data", {}).get("rows", [])
    industry_map: dict[str, str] = {}
    for row in rows:
        ticker = str(row.get("symbol") or "").upper()
        if ticker:
            industry_map[ticker] = classify_industry(row.get("industry"), row.get("sector"))
    return industry_map


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def load_sic_industry_map() -> tuple[dict[str, str], dict[str, int | str]]:
    """Map tickers to the versioned CRC industry taxonomy from cached SEC SIC data."""
    cache = load_json(SIC_CACHE_PATH, {"candidates": [], "records": {}})
    taxonomy = load_json(SIC_TAXONOMY_PATH, {"version": "unavailable", "rules": [], "precedence": [], "unmappedIndustry": "Unclassified"})
    rules = {rule["industry"]: rule for rule in taxonomy.get("rules", [])}

    def classify(sic_value: Any) -> str:
        try:
            sic = int(sic_value)
        except (TypeError, ValueError):
            return taxonomy.get("unmappedIndustry", "Unclassified")
        for label in taxonomy.get("precedence", []):
            rule = rules.get(label, {})
            if sic in set(rule.get("sic") or []):
                return label
            if any(start <= sic <= end for start, end in rule.get("ranges") or []):
                return label
        return taxonomy.get("unmappedIndustry", "Unclassified")

    result: dict[str, str] = {}
    matched = 0
    with_sic = 0
    for candidate in cache.get("candidates") or []:
        ticker, cik = candidate.get("ticker"), candidate.get("cik")
        if not ticker or not cik:
            continue
        matched += 1
        record = (cache.get("records") or {}).get(cik, {})
        if record.get("sic"):
            with_sic += 1
        result[ticker] = classify(record.get("sic"))
    return result, {"taxonomyVersion": taxonomy.get("version", "unavailable"), "candidateCikMatched": matched, "withSic": with_sic}


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


def fetch_benchmark_history(base_url: str, api_key: str, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
    """Fetch a long adjusted daily series for SPY/QQQ so EMA50 is warmed up."""
    payload = get_json(
        base_url,
        f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}",
        api_key,
        {"adjusted": "true", "sort": "asc", "limit": 5000},
    )
    bars: list[dict[str, Any]] = []
    for raw in payload.get("results") or []:
        stamp = raw.get("t")
        close, high, low, volume = raw.get("c"), raw.get("h"), raw.get("l"), raw.get("v")
        if stamp is None or any(value is None for value in (close, high, low, volume)):
            continue
        session = datetime.fromtimestamp(stamp / 1000, timezone.utc).date()
        if close <= 0 or high < low or volume < 0:
            continue
        bars.append({"date": session.isoformat(), "o": raw.get("o"), "h": high, "l": low, "c": close, "v": volume, "vw": raw.get("vw") or close})
    return sorted(bars, key=lambda row: row["date"])[-BENCHMARK_WINDOW_DAYS:]


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
                metadata[ticker] = {
                    "type": (item.get("type") or "").upper(),
                    "name": item.get("name") or ticker,
                    "primaryExchange": item.get("primary_exchange") or "",
                    "sicCode": item.get("sic_code") or "",
                    "sicDescription": item.get("sic_description") or "",
                }
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
        limit = BENCHMARK_WINDOW_DAYS if ticker in {"SPY", "QQQ"} else WINDOW_DAYS
        state["bars"][ticker] = sorted(series, key=lambda row: row["date"])[-limit:]


def normalize_bar(raw: dict[str, Any], session: date) -> tuple[str, dict[str, Any]] | None:
    ticker = raw.get("T") or raw.get("ticker")
    close, high, low, volume = raw.get("c"), raw.get("h"), raw.get("l"), raw.get("v")
    if not ticker or any(value is None for value in (close, high, low, volume)):
        return None
    if close <= 0 or high < low or volume < 0:
        return None
    return ticker, {"date": session.isoformat(), "o": raw.get("o"), "h": high, "l": low, "c": close, "v": volume, "vw": raw.get("vw") or close}


def is_allowed(ticker: str, metadata: dict[str, Any], overrides: dict[str, Any]) -> bool:
    if ticker in set(overrides.get("excludedTickers") or []):
        return False
    security_type = (metadata.get(ticker, {}).get("type") or "").upper()
    return security_type in ALLOWED_SECURITY_TYPES


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


def summarize(state: dict[str, Any], session: str, overrides: dict[str, Any], official_industry_map: dict[str, str] | None = None, sic_coverage: dict[str, int | str] | None = None) -> dict[str, Any] | None:
    bars_by_ticker = state["bars"]
    metadata = state.get("metadata") or {}
    eligible: list[tuple[str, dict[str, Any]]] = []
    pool: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for ticker, bars in bars_by_ticker.items():
        series = [bar for bar in bars if bar["date"] <= session]
        if not series or series[-1]["date"] != session or not is_allowed(ticker, metadata, overrides):
            continue
        latest = series[-1]
        if latest["c"] < 5 or latest["v"] < 300_000:
            continue
        eligible.append((ticker, latest))
        metric = security_metric(series)
        if metric["return1d"] is None:
            continue
        pool.append((ticker, latest, metric))
    if len(eligible) < MIN_EXPECTED_UNIVERSE:
        print(f"QUALITY GATE: candidate pool is {len(eligible)}, lower than expected {MIN_EXPECTED_UNIVERSE}; retain previous published result.")
        return None

    up4 = sum(metric["return1d"] >= 0.04 for _, _, metric in pool)
    down4 = sum(metric["return1d"] <= -0.04 for _, _, metric in pool)
    sma20_valid = [metric for _, _, metric in pool if metric["sma20"] is not None]
    sma50_valid = [metric for _, _, metric in pool if metric["sma50"] is not None]
    analysis_pool = [(ticker, latest, metric) for ticker, latest, metric in pool if (latest.get("vw") or latest["c"]) * latest["v"] >= 5_000_000]
    leaders = [(ticker, latest, metric) for ticker, latest, metric in analysis_pool if metric["return63d"] is not None and metric["return63d"] >= 0.20]

    def etf_atr_distance(ticker: str) -> float | None:
        bars = [bar for bar in bars_by_ticker.get(ticker, []) if bar["date"] <= session]
        if not bars or bars[-1]["date"] != session:
            return None
        metric = security_metric(bars)
        if not metric["ema50"] or not metric["atr14"]:
            return None
        return (bars[-1]["c"] - metric["ema50"]) / metric["atr14"]

    industry_pool: dict[str, int] = defaultdict(int)
    industry_leaders: dict[str, int] = defaultdict(int)
    industry_map = official_industry_map if official_industry_map is not None else state.get("industryMap") or {}
    reviewed_overrides = overrides.get("industryOverrides", {})
    industry_for = lambda ticker: reviewed_overrides.get(ticker, industry_map.get(ticker, "Unclassified"))
    for ticker, _, _ in analysis_pool:
        industry_pool[industry_for(ticker)] += 1
    for ticker, _, _ in leaders:
        industry_leaders[industry_for(ticker)] += 1
    leader_n = len(leaders)
    industry = []
    for name, count in industry_leaders.items():
        pool_n = industry_pool[name]
        leader_share = count / leader_n * 100 if leader_n else 0
        pool_share = pool_n / len(analysis_pool) * 100
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
        "universeN": len(eligible),
        "analysisN": len(analysis_pool),
        "sp500Close": None,
        "industry": industry[:20],
        "industrySource": "SEC submissions SIC mapped to CRC fixed taxonomy",
        "industryStatus": "crc_sic_v1" if official_industry_map is not None else "awaiting_sic_verification",
        "industryCoverage": sic_coverage or {},
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
    verified = latest.get("industryStatus") == "crc_sic_v1"
    return {"status": "live", "asOf": latest["date"], "updatedAt": datetime.now(timezone.utc).isoformat(), "source": "Massive 日線資料 · SEC SIC 分類", "message": "", "summary": latest, "history": history, "industry": latest.get("industry") or [], "industryStatus": latest.get("industryStatus", "awaiting_sic_verification"), "industryMessage": "CRC 固定 SIC 對照規則已套用；個別未返回 SIC 或未對照的公司歸入 Unclassified。" if verified else "行業成員現正按可驗證 SIC 資料校對；為免以粗略標籤造成錯誤排行，暫停顯示未驗證行業數字。", "industryCoverage": latest.get("industryCoverage") or {}, "leaderTrend": trend}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-benchmarks", action="store_true")
    args = parser.parse_args()
    api_key, base_url = environment()
    if not api_key:
        print("SAFE EXIT: MASSIVE_API_KEY is not configured. Add it to GitHub Secrets; existing published output is untouched.")
        return 0

    state = load_json(STATE_PATH, {"bars": {}, "metadata": {}, "industryMap": {}, "summaries": [], "lastMetadataRefresh": None, "lastIndustryRefresh": None, "schemaVersion": 1})
    overrides = load_json(OVERRIDES_PATH, {"excludedTickers": [], "industryOverrides": {}})
    sic_industry_map, sic_coverage = load_sic_industry_map()
    today = datetime.now(timezone.utc).date()
    metadata_is_old = not state.get("lastMetadataRefresh") or date.fromisoformat(state["lastMetadataRefresh"]) < today - timedelta(days=7)
    if args.bootstrap or args.refresh_metadata or metadata_is_old:
        print("Refreshing ticker reference metadata…")
        state["metadata"] = fetch_metadata(base_url, api_key)
        state["lastMetadataRefresh"] = today.isoformat()
    industry_is_old = not state.get("lastIndustryRefresh") or date.fromisoformat(state["lastIndustryRefresh"]) < today - timedelta(days=7)
    if args.bootstrap or industry_is_old:
        print("Refreshing public industry mapping…")
        try:
            state["industryMap"] = fetch_nasdaq_industry_map()
            state["lastIndustryRefresh"] = today.isoformat()
        except requests.RequestException as error:
            print(f"Industry mapping refresh failed; preserving cached mapping: {error}")

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

    should_refresh_benchmarks = args.bootstrap or args.refresh_benchmarks or any(len(state["bars"].get(ticker, [])) < 150 for ticker in ("SPY", "QQQ"))
    benchmark_end = target_date if args.bootstrap and target_date else args.as_of
    if should_refresh_benchmarks:
        benchmark_start = benchmark_end - timedelta(days=450)
        for ticker in ("SPY", "QQQ"):
            try:
                long_series = fetch_benchmark_history(base_url, api_key, ticker, benchmark_start, benchmark_end)
                if long_series:
                    state["bars"][ticker] = long_series
            except requests.RequestException as error:
                print(f"Benchmark history refresh failed for {ticker}; preserving cached history: {error}")

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
    # Bootstrap fetches historical sessions after the latest completed market
    # day. Keep publishing anchored to that latest session rather than the
    # final history request, otherwise every series ends one day ahead of the
    # selected summary and the quality gate correctly rejects the mismatch.
    target_session = target_date.isoformat() if args.bootstrap and target_date else fetched_sessions[-1]
    summary = summarize(state, target_session, overrides, sic_industry_map, sic_coverage)
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
