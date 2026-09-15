import assert from 'node:assert/strict';
import test from 'node:test';
import { sanitizeMetric } from '../../core/static/core/js/speed-insights.mjs';

test('performance events never retain searches or fragments', () => {
  const original = { url: 'https://piem.example/cursos/?q=aluno@example.com#contato', type: 'vital', value: 42 };
  assert.deepEqual(sanitizeMetric(original), { ...original, url: 'https://piem.example/cursos/' });
  assert.match(original.url, /aluno/);
});

test('private paths, credential tokens and malformed URLs are not collected', () => {
  for (const url of ['https://piem.example/painel/', 'https://piem.example/curriculo/validar/token/', '/cursos/', 'invalid']) {
    assert.equal(sanitizeMetric({ url }), null);
  }
});
