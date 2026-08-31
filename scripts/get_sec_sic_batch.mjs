import fs from 'node:fs';

const batchIndex = Number(process.argv[2] || 0);
const payload = JSON.parse(fs.readFileSync('/tmp/sec-sic-batches.json', 'utf8'));
const batch = payload.batches[batchIndex] || [];
console.log(JSON.stringify({ batchIndex, count: batch.length, records: batch.map(row => ({ ticker: row.ticker, cik: row.cik })) }));
