import fs from 'node:fs';

const state = JSON.parse(fs.readFileSync(new URL('../data/market-state.json', import.meta.url), 'utf8'));
const nasdaq = fs.existsSync('/tmp/nasdaq_screener.json')
  ? new Map(JSON.parse(fs.readFileSync('/tmp/nasdaq_screener.json', 'utf8')).data.rows.map(row => [String(row.symbol || '').toUpperCase(), row]))
  : new Map();
const target = state.summaries.at(-1).date;
const allowed = new Set(['CS', 'ADRC']);
const tracked = new Set(['Software & IT Services', 'Biotech & Pharma', 'Instruments & Medical Devices', 'Business Services', 'Health Care Services', 'Professional Services', 'Unclassified']);
const members = Object.fromEntries([...tracked].map(name => [name, []]));

for (const [ticker, bars] of Object.entries(state.bars)) {
  const metadata = state.metadata?.[ticker] || {};
  if (!allowed.has(String(metadata.type || '').toUpperCase())) continue;
  const series = bars.filter(row => row.date <= target);
  const latest = series.at(-1);
  if (!latest || latest.date !== target || latest.c < 5 || latest.v < 300000 || (latest.vw || latest.c) * latest.v < 5000000 || series.length < 64) continue;
  const return63 = latest.c / series.at(-64).c - 1;
  if (return63 < 0.20) continue;
  const industry = state.industryMap?.[ticker] || 'Unclassified';
  if (!tracked.has(industry)) continue;
  const source = nasdaq.get(ticker) || {};
  members[industry].push({ ticker, name: metadata.name || ticker, rawIndustry: source.industry || null, rawSector: source.sector || null, return63: +(return63 * 100).toFixed(1) });
}

console.log(JSON.stringify({ target, groups: Object.fromEntries(Object.entries(members).map(([name, items]) => [name, { count: items.length, members: items.sort((a, b) => b.return63 - a.return63) }])) }, null, 2));
