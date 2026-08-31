import fs from 'node:fs';

const state = JSON.parse(fs.readFileSync(new URL('../data/market-state.json', import.meta.url), 'utf8'));
const target = (state.summaries || []).at(-1)?.date;
const types = {};
const latestByType = {};
const exchanges = {};
const allowedExchanges = {};
const analysisExchanges = {};
for (const [ticker, bars] of Object.entries(state.bars || {})) {
  const latest = bars.at(-1);
  if (!latest || latest.date !== target || latest.c < 5 || latest.v < 300000) continue;
  const type = String(state.metadata?.[ticker]?.type || '(blank)').toUpperCase();
  types[type] = (types[type] || 0) + 1;
  const exchange = state.metadata?.[ticker]?.primaryExchange || '(blank)';
  exchanges[exchange] = (exchanges[exchange] || 0) + 1;
  if (type === 'CS' || type === 'ADRC') {
    allowedExchanges[exchange] = (allowedExchanges[exchange] || 0) + 1;
    if (latest.c * latest.v >= 5_000_000) analysisExchanges[exchange] = (analysisExchanges[exchange] || 0) + 1;
  }
  (latestByType[type] ||= []).push(ticker);
}
console.log(JSON.stringify({ target, types, exchanges, allowedExchanges, analysisExchanges, samples: Object.fromEntries(Object.entries(latestByType).map(([type, tickers]) => [type, tickers.slice(0, 15)])) }, null, 2));
