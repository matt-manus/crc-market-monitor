#!/usr/bin/env python3
"""Refresh the public industry label map without re-fetching market prices."""
from __future__ import annotations

from datetime import date

from update_market import STATE_PATH, fetch_nasdaq_industry_map, load_json, write_json_atomic


def main() -> int:
    state = load_json(STATE_PATH, {"bars": {}, "metadata": {}, "summaries": []})
    mapping = fetch_nasdaq_industry_map()
    state["industryMap"] = mapping
    state["lastIndustryRefresh"] = date.today().isoformat()
    write_json_atomic(STATE_PATH, state)
    print(f"Refreshed {len(mapping)} public industry labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
