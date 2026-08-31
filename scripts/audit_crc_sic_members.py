#!/usr/bin/env python3
"""Write an auditable member list for the active CRC SIC industry summary."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from update_market import OVERRIDES_PATH, ROOT, STATE_PATH, is_allowed, load_json, load_sic_industry_map, security_metric, write_json_atomic

OUTPUT_PATH = ROOT / "data" / "crc-sic-industry-audit-v1.json"


def main() -> int:
    state = load_json(STATE_PATH, {"bars": {}, "metadata": {}, "summaries": []})
    overrides = load_json(OVERRIDES_PATH, {"excludedTickers": [], "industryOverrides": {}})
    official_map, coverage = load_sic_industry_map()
    target = state["summaries"][-1]["date"]
    candidates = load_json(ROOT / "data" / "sic-candidates-v1.json", {"candidates": [], "records": {}})
    by_ticker = {row["ticker"]: row for row in candidates.get("candidates") or []}
    grouped: dict[str, list[dict]] = defaultdict(list)

    for ticker, bars in state.get("bars", {}).items():
        series = [bar for bar in bars if bar["date"] <= target]
        if not series or series[-1]["date"] != target or not is_allowed(ticker, state.get("metadata") or {}, overrides):
            continue
        latest = series[-1]
        metric = security_metric(series)
        if latest["c"] < 5 or latest["v"] < 300_000 or metric["return1d"] is None:
            continue
        if (latest.get("vw") or latest["c"]) * latest["v"] < 5_000_000 or metric["return63d"] is None or metric["return63d"] < 0.20:
            continue
        candidate = by_ticker.get(ticker, {})
        record = (candidates.get("records") or {}).get(candidate.get("cik"), {})
        industry = overrides.get("industryOverrides", {}).get(ticker, official_map.get(ticker, "Unclassified"))
        grouped[industry].append({
            "ticker": ticker,
            "name": (state.get("metadata") or {}).get(ticker, {}).get("name") or ticker,
            "cik": candidate.get("cik"),
            "sic": record.get("sic"),
            "sicDescription": record.get("sicDescription"),
            "return63Pct": round(metric["return63d"] * 100, 1),
        })

    payload = {
        "version": "crc-sic-industry-audit-v1",
        "asOf": target,
        "taxonomyVersion": coverage.get("taxonomyVersion"),
        "sicCoverage": coverage,
        "groups": {
            name: {"leaderN": len(items), "members": sorted(items, key=lambda row: row["ticker"])}
            for name, items in sorted(grouped.items())
        },
    }
    write_json_atomic(OUTPUT_PATH, payload)
    print(f"Wrote {OUTPUT_PATH} with {sum(group['leaderN'] for group in payload['groups'].values())} leaders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
