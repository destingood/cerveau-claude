import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiFailure, createApi, describe } from '../src/api.js';

const TOKEN = 't'.repeat(40);

function recorder(status = 200, body = { ok: true }) {
  const requests = [];
  const fetchImpl = async (url, init) => {
    requests.push({ url, ...init });
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
  };
  return { requests, api: createApi({ baseUrl: 'http://127.0.0.1:8765', token: TOKEN, fetchImpl }) };
}

test('every call carries the bearer token, refuses redirects and has a timeout', async () => {
  const { requests, api } = recorder();
  await api.status();
  await api.kill('arrêt');
  const [get, post] = requests;
  assert.equal(get.url, 'http://127.0.0.1:8765/status');
  assert.equal(get.method, 'GET');
  assert.deepEqual(get.headers, { authorization: `Bearer ${TOKEN}` });
  assert.equal(get.body, undefined);
  assert.equal(get.redirect, 'error');
  assert.ok(get.signal instanceof AbortSignal);
  assert.equal(post.headers['content-type'], 'application/json');
  assert.deepEqual(JSON.parse(post.body), { reason: 'arrêt' });
});

test('each route is the API route', async () => {
  const { requests, api } = recorder();
  const id = '01929f3e-7a1b-7c2d-8e3f-123456789abc';
  await api.settings();
  await api.pending();
  await api.approve(id, '123456');
  await api.refuse(id, 'non');
  await api.daily();
  await api.daily('2026-10-16');
  await api.alerts(7, 50);
  await api.ignored('salon');
  await api.approve('../kill', '1');
  assert.deepEqual(
    requests.map(({ method, url }) => `${method} ${url.replace('http://127.0.0.1:8765', '')}`),
    [
      'GET /bot/settings',
      'GET /approvals/pending',
      `POST /approvals/${id}/approve`,
      `POST /approvals/${id}/refuse`,
      'GET /reports/daily',
      'GET /reports/daily?day=2026-10-16',
      'GET /alerts?after=7&limit=50',
      'POST /events/ignored',
      'POST /approvals/..%2Fkill/approve',
    ],
  );
  assert.deepEqual(JSON.parse(requests[2].body), { code: '123456' });
  assert.deepEqual(JSON.parse(requests[3].body), { reason: 'non' });
  assert.deepEqual(JSON.parse(requests[7].body), { kind: 'salon' });
});

test("an error answer keeps the API's status and text", async () => {
  const conflict = recorder(409, { detail: 'approbation x REFUSEE : aucun code attendu' }).api;
  await assert.rejects(conflict.approve('x', '123456'), (error) => {
    assert.ok(error instanceof ApiFailure);
    assert.equal(error.status, 409);
    assert.equal(error.detail, 'approbation x REFUSEE : aucun code attendu');
    return true;
  });
  const garbled = recorder(500, 'pas du json').api;
  await assert.rejects(garbled.status(), (error) => error.status === 500 && error.detail === null);
});

test('an unreachable API drops the cause, which may quote the request', async () => {
  const api = createApi({
    baseUrl: 'http://127.0.0.1:8765',
    token: TOKEN,
    fetchImpl: async () => {
      throw new TypeError(`fetch failed ${TOKEN}`);
    },
  });
  await assert.rejects(api.status(), (error) => {
    assert.ok(error instanceof ApiFailure);
    assert.equal(error.status, null);
    assert.equal(error.cause, undefined);
    assert.ok(!error.message.includes(TOKEN));
    return true;
  });
});

test('only the kind and status of an error reach the log', () => {
  assert.equal(describe(new ApiFailure(409, 'détail')), 'HTTP 409');
  assert.equal(describe(new ApiFailure(null, null)), 'HTTP injoignable');
  assert.equal(describe(new RangeError('valeur 123456')), 'RangeError');
  assert.equal(describe(undefined), 'erreur');
});
