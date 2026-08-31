# CRC Market Monitor

CRC Market Monitor is a **personal market-breadth research dashboard**. It runs in a private GitHub repository, calculates daily breadth and momentum statistics with a server-side market-data key, and writes one static dashboard payload for your own viewing. It does not provide investment advice, recommendations, execution signals, or public redistribution rights for provider data.

> The committed dashboard initially loads a **reference-layout preview** because no personal market-data key has been configured. The first successful bootstrap run replaces it with your own calculated data.

## What this repository contains

| Path | Purpose |
|---|---|
| `site/` | A dependency-free static dashboard. It renders only `site/data/latest.json`. |
| `scripts/update_market.py` | Server-side data fetch, rolling 84-session state, indicator calculation and quality gates. |
| `data/market-state.json` | Private rolling state. It needs to remain in this **private** repository because it supports SMA, EMA and ATR calculations. |
| `.github/workflows/daily-market.yml` | Weekday collection at 22:25 UTC plus a manual bootstrap button. |
| `config/security-overrides.json` | Auditable exclusions and reviewed industry mappings. |

## Initial GitHub setup

Create a **private** repository named `crc-market-monitor`, then upload or push this entire folder to its default branch. In the repository settings, enable **Actions** and set **Settings → Actions → General → Workflow permissions** to allow read and write permissions; the daily job commits only the updated aggregate and the private rolling state.

Open **Settings → Secrets and variables → Actions → Secrets** and add `MASSIVE_API_KEY`. Do not paste the key into a source file, issue tracker, chat, `latest.json`, or workflow YAML. If your account requires a different documented API host, add a repository variable named `MASSIVE_BASE_URL`; otherwise the project uses `https://api.massive.com` by default.

In the **Actions** tab, select `CRC daily market refresh`, choose **Run workflow**, turn on **bootstrap**, and run it once. Bootstrap asks the provider for a rolling history so the dashboard can calculate 50-session and 63-session readings. The script exits without modifying the previously published result if the provider has no completed daily session, returns too few eligible securities, or if the key is missing.

## Private viewing and deployment boundary

GitHub repository privacy and website privacy are different. GitHub Pages is not an access-control layer: GitHub documents that Pages sites are publicly available, including when a private repository is eligible to publish them. Do **not** treat an unshared Pages URL as a private site.

For the lowest-cost personal workflow, keep this repository private and either clone it to your own computer and open `site/index.html`, or serve the `site/` directory locally after each pull. If you need a browser-accessible URL while keeping the dashboard private, use the same private GitHub repository with a host that provides an authentication gate (for example, an access-protected static site). Configure that host only after confirming the market-data provider permits the intended use.

## Indicator definitions implemented

| Metric | Calculation |
|---|---|
| Up 4% / Down 4% | Eligible securities where daily close-to-close return is at least `+4%` or at most `-4%`. |
| 20D / 50D breadth | Eligible securities with close above respective SMA, divided only by securities holding enough price history. |
| SPY / QQQ ATR distance | `(close − EMA50) / ATR14`, using a 14-session simple average of True Range. |
| MLI membership | Eligible security with price ≥ 5, volume ≥ 300,000, dollar volume ≥ 5m, and 63-session return ≥ 20%. |
| MLI return and rise % | Equal-weight daily return of leaders and proportion with positive daily return. |

The script starts with basic provider security-type exclusions. Review and maintain exclusions in `config/security-overrides.json`; provider instrument labels can change. Industry data defaults to `Unclassified` until you add an audited mapping or a separately verified SEC-based classification process.

## Daily operation

The scheduled workflow runs Monday–Friday at 22:25 UTC, deliberately after the U.S. regular session. A schedule is a target time, not a guaranteed market-close feed. The quality gate prevents an incomplete response from overwriting the last working result. Use **Run workflow** for a manual rerun or a date-specific historical check.

The program currently uses Polygon-compatible Massive grouped daily aggregates and ticker-reference endpoints. Before enabling it, check your own provider account’s current endpoint documentation, entitlements, data-use terms and personal-use eligibility. The code is a personal technical template, not confirmation that a given plan permits a particular form of storage or display.

## Local test without a key

You can verify that no credentials are leaked by running the saved script without `MASSIVE_API_KEY`; it should print `SAFE EXIT` and preserve the reference preview. Once a key is configured, run the workflow manually rather than entering secrets into the browser source code.

## Next enhancement: industry classifications

The dashboard layout supports industry comparisons immediately, but reliable industry classification needs its own reviewed mapping. A later version can build a CIK-to-SIC data process from SEC filings, document its mapping version, and retain `Unclassified` when issuer information is unavailable. Do not use company-name keyword guessing as the only classification source.
