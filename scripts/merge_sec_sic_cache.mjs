import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const candidatesPath = path.join(root, 'data/sic-candidates-v1.json');
const receiverPath = '/tmp/sec-sic-received.json';
const candidates = JSON.parse(fs.readFileSync(candidatesPath, 'utf8'));
const received = JSON.parse(fs.readFileSync(receiverPath, 'utf8'));
const now = new Date().toISOString();
const records = {};

for (const [cik, record] of Object.entries(received.records || {})) {
  records[cik] = {
    cik,
    sic: record.sic || null,
    sicDescription: record.sicDescription || null,
    status: record.status || 'unknown',
    sourceUrl: `https://data.sec.gov/submissions/CIK${cik}.json`,
    retrievedAt: now,
  };
}

candidates.records = records;
candidates.cache = {
  version: 'crc-sec-sic-cache-v1',
  source: 'SEC submissions API',
  retrievedAt: now,
  uniqueCikQueried: Object.keys(records).length,
  withSic: Object.values(records).filter(row => row.sic).length,
  blankSic: Object.values(records).filter(row => !row.sic && row.status === 'ok').length,
  candidateCount: candidates.candidates.length,
  candidateCikMatched: candidates.candidates.filter(row => row.cik).length,
};

fs.writeFileSync(candidatesPath, `${JSON.stringify(candidates, null, 2)}\n`);
console.log(JSON.stringify(candidates.cache));
