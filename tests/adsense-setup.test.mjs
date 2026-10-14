import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const config = readFileSync(new URL('../app/adsense-config.ts', import.meta.url), 'utf8');
const layout = readFileSync(new URL('../app/layout.tsx', import.meta.url), 'utf8');
const slot = readFileSync(new URL('../app/adsense.tsx', import.meta.url), 'utf8');
const adsTxt = readFileSync(new URL('../app/ads.txt/route.ts', import.meta.url), 'utf8');
const directory = readFileSync(new URL('../app/courses/course-directory.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

test('AdSense verification uses the real publisher and publishes the authorized-seller line', () => {
  assert.match(config, /ca-pub-7452457835531443/);
  assert.match(config, /1381740675/);
  assert.match(layout, /google-adsense-account/);
  assert.doesNotMatch(layout, /pagead2\.googlesyndication\.com/);
  assert.match(slot, /pagead2\.googlesyndication\.com\/pagead\/js\/adsbygoogle\.js/);
  assert.match(slot, /strategy="afterInteractive"/);
  assert.match(adsTxt, /ADSENSE_PUBLISHER_ID/);
  assert.match(adsTxt, /google\.com, \$\{ADSENSE_PUBLISHER_ID\}, DIRECT, f08c47fec0942fa0/);
});

test('course directory reserves a responsive, clearly labelled ad placement', () => {
  assert.match(directory, /import \{ AdSenseSlot \}/);
  assert.match(directory, /<AdSenseSlot \/>/);
  assert.match(slot, /className="ad-slot ad-placeholder"/);
  assert.match(slot, /<span>廣告<\/span>/);
  assert.match(slot, /data-ad-slot=\{ADSENSE_SLOT\}/);
  assert.match(slot, /data-full-width-responsive="true"/);
  assert.match(styles, /\.ad-slot \{[\s\S]*min-height: 112px/);
  assert.match(styles, /\.ad-placeholder/);
  assert.doesNotMatch(slot, /點擊廣告|支持本站|贊助本站/);
});
