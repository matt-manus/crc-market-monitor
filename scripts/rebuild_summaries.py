#!/usr/bin/env python3
"""Rebuild visible CRC history from the verified rolling market-state file.

The first Massive bootstrap intentionally fetches enough daily bars to calculate
50-session and 63-session rules. This script derives one verified summary per
available session from that saved, provider-sourced state; it does not make any
network request or use an API key.
"""
from __future__ import annotations

from pathlib import Path

from update_market import OVERRIDES_PATH, STATE_PATH, build_output, load_json, summarize, write_json_atomic


def main() -> int:
    state = load_json(STATE_PATH, {"bars": {}, "metadata": {}, "summaries": []})
    overrides = load_json(OVERRIDES_PATH, {"excludedTickers": [], "industryOverrides": {}})
    sessions = sorted({bar["date"] for bars in state.get("bars", {}).values() for bar in bars})
    summaries = []
    for session in sessions:
        summary = summarize(state, session, overrides)
        if summary is not None:
            summaries.append(summary)
    if not summaries:
        raise SystemExit("No verified historical summaries could be rebuilt.")
    state["summaries"] = summaries[-252:]
    write_json_atomic(STATE_PATH, state)
    write_json_atomic(Path(__file__).resolve().parents[1] / "site" / "data" / "latest.json", build_output(state))
    print(f"Rebuilt {len(summaries)} real market summaries through {summaries[-1]['date']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
