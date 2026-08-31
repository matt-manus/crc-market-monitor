import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const state = JSON.parse(fs.readFileSync(path.join(root, 'data/market-state.json'), 'utf8'));
const secSource = process.env.SEC_COMPANY_TICKERS_FILE || '/home/ubuntu/upload/www.sec.gov_files_company_tickers.json_1788166363386.md';
const output = path.join(root, 'data/sic-candidates-v1.json');
const allowedTypes = new Set(['CS', 'ADRC']);
const target = state.summaries.at(-1).date;

function normalizeSymbol(value) {
  return String(value || '').trim().toUpperCase().replace(/[.\/]/g, '-');
}

const rawSec = fs.readFileSync(secSource, 'utf8').replaceAll('\\_', '_');
const secRows = Object.values(JSON.parse(rawSec));
const byTicker = new Map();
for (const row of secRows) {
  const key = normalizeSymbol(row.ticker);
  if (!key || byTicker.has(key)) continue;
  byTicker.set(key, { cik: String(row.cik_str).padStart(10, '0'), secTicker: row.ticker, secTitle: row.title });
}

const candidates = [];
for (const [ticker, series] of Object.entries(state.bars || {})) {
  const meta = state.metadata?.[ticker] || {};
  if (!allowedTypes.has(String(meta.type || '').toUpperCase())) continue;
  const latestSeries = series.filter(row => row.date <= target);
  const latest = latestSeries.at(-1);
  if (!latest || latestSeries.length < 2 || latest.date !== target || latest.c < 5 || latest.v < 300000 || (latest.vw || latest.c) * latest.v < 5000000) continue;
  const sec = byTicker.get(normalizeSymbol(ticker));
  candidates.push({
    ticker,
    name: meta.name || ticker,
    type: meta.type,
    cik: sec?.cik || null,
    secTicker: sec?.secTicker || null,
    secTitle: sec?.secTitle || null,
    match: sec ? (normalizeSymbol(ticker) === normalizeSymbol(sec.secTicker) ? 'exact_or_normalized' : 'normalized') : 'unmatched'
  });
}

const existing = fs.existsSync(output) ? JSON.parse(fs.readFileSync(output, 'utf8')) : {};
const snapshot = {
  version: 'crc-sic-candidates-v1',
  generatedAt: new Date().toISOString(),
  asOf: target,
  source: 'SEC company_tickers.json',
  candidates,
  summary: {
    candidateCount: candidates.length,
    cikMatched: candidates.filter(row => row.cik).length,
    cikUnmatched: candidates.filter(row => !row.cik).length
  },
  records: existing.records || {}
};
fs.writeFileSync(output, `${JSON.stringify(snapshot, null, 2)}\n`);
console.log(JSON.stringify(snapshot.summary));
