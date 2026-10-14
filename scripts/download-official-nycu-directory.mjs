import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const url = 'https://www.nycu.edu.tw/it/ch/app/news/doc?detailNo=1446065073796681728&module=headnews&type=s';
const directory = resolve('tmp/pdfs');
const output = resolve(directory, 'nycu-website-health-list.pdf');
const response = await fetch(url, {
  headers: { 'User-Agent': 'WZUNAA official academic directory builder/1.0 (+https://map.scmwcscr.com)' },
  signal: AbortSignal.timeout(60_000),
});
if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
mkdirSync(directory, { recursive: true });
writeFileSync(output, Buffer.from(await response.arrayBuffer()));
console.log(output);
