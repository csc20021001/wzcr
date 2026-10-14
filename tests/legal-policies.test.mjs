import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const terms = readFileSync(new URL('../app/terms/page.tsx', import.meta.url), 'utf8');
const privacy = readFileSync(new URL('../app/privacy/page.tsx', import.meta.url), 'utf8');

test('terms describe service boundaries and user-generated-content risks', () => {
  assert.match(terms, /課程評分是個別修課經驗的彙整/);
  assert.match(terms, /學校官方公開來源/);
  assert.match(terms, /禁止內容與行為/);
  assert.match(terms, /著作權通知與下架/);
  assert.match(terms, /三次涉有著作權侵害情事/);
  assert.match(terms, /外部連結、廣告與第三方服務/);
  assert.match(terms, /故意或重大過失/);
  assert.match(terms, /依法享有且不得拋棄的權利/);
  assert.doesNotMatch(terms, /租屋|房東|租金|看屋/);
});

test('privacy policy includes the statutory collection notice fields', () => {
  assert.match(privacy, /個資蒐集者與聯絡方式/);
  assert.match(privacy, /蒐集目的/);
  assert.match(privacy, /利用期間、地區、對象與方式/);
  assert.match(privacy, /是否必須提供資料及不提供的影響/);
  assert.match(privacy, /查詢或閱覽、製給複製本、補充或更正、停止蒐集處理或利用，以及刪除/);
  assert.match(privacy, /境外處理/);
  assert.doesNotMatch(privacy, /租屋|房東|租金|看屋/);
});
