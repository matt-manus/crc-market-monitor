import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = JSON.parse(fs.readFileSync(path.join(root, 'data/sic-candidates-v1.json'), 'utf8'));
const records = source.records || {};
const pending = source.candidates.filter(row => row.cik && !records[row.cik]);
const batches = [];
for (let index = 0; index < pending.length; index += 100) batches.push(pending.slice(index, index + 100));
fs.writeFileSync('/tmp/sec-sic-batches.json', JSON.stringify({ generatedAt: new Date().toISOString(), pending: pending.length, batches }, null, 2));
console.log(JSON.stringify({ pending: pending.length, batchCount: batches.length }));
