import assert from 'node:assert/strict';
import test from 'node:test';
import { safeEqual, sanitizeReturnTo } from '../app/auth/security.mjs';

test('accepts only same-origin relative return paths', () => {
  assert.equal(sanitizeReturnTo('/?publish=1'), '/?publish=1');
  assert.equal(sanitizeReturnTo('https://evil.example/'), '/');
  assert.equal(sanitizeReturnTo('//evil.example/'), '/');
  assert.equal(sanitizeReturnTo(null), '/');
});

test('compares OAuth state without early character exits', () => {
  assert.equal(safeEqual('abc123', 'abc123'), true);
  assert.equal(safeEqual('abc123', 'abc124'), false);
  assert.equal(safeEqual('short', 'longer'), false);
});
