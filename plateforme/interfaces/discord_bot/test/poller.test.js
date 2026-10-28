import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiFailure } from '../src/api.js';
import { ALERT_BATCH, createPoller } from '../src/poller.js';
import { APPROVAL_ID, fakeApi, memoryCursor, request } from './fakes.js';

const OTHER_ID = '01929f3e-7a1b-7c2d-8e3f-123456789abd';

const alert = (seq, kind = 'ecart', ref = null) => ({ seq, kind, text: `alerte ${seq}`, ref });

/** A poller over a world the test changes between rounds: alerts, requests, Discord's state. */
function setup(cursor = memoryCursor()) {
  const world = { alerts: [], requests: [], daily: null, sendLimit: Infinity, gate: null };
  const sent = [];
  const lines = [];
  const { api, calls } = fakeApi({
    alerts: (after, limit) => ({
      alerts: world.alerts.filter((item) => item.seq > after).slice(0, limit),
    }),
    pending: () => ({ open: true, reason: null, locked: false, requests: world.requests }),
    daily: (day) => {
      if (world.daily) throw world.daily;
      return { text: `Rapport quotidien du ${day}` };
    },
  });
  const send = async (payload) => {
    if (world.gate) await world.gate;
    if (sent.length >= world.sendLimit) throw new Error('Missing Access');
    sent.push(payload);
  };
  const poller = createPoller({ api, send, cursor, log: (line) => lines.push(line) });
  return { world, sent, lines, calls, cursor, poller };
}

test('alerts are posted in order and the cursor follows each post', async () => {
  const { world, sent, cursor, poller } = setup();
  world.alerts = [alert(1), alert(2), alert(3)];
  assert.equal(await poller.tick(), true);
  assert.deepEqual(sent, ['**Alerte CERVEAU** : alerte 1', '**Alerte CERVEAU** : alerte 2', '**Alerte CERVEAU** : alerte 3']);
  assert.deepEqual(
    cursor.saves.map((state) => state.after),
    [1, 2, 3],
  );
  assert.equal(await poller.tick(), true);
  assert.equal(sent.length, 3);
});

test('a long outbox is read in batches', async () => {
  const { world, sent, calls, poller } = setup();
  world.alerts = Array.from({ length: 2 * ALERT_BATCH + 20 }, (_, index) => alert(index + 1));
  await poller.tick();
  assert.equal(sent.length, world.alerts.length);
  assert.deepEqual(
    calls.filter(([name]) => name === 'alerts').map(([, after, limit]) => [after, limit]),
    [
      [0, ALERT_BATCH],
      [ALERT_BATCH, ALERT_BATCH],
      [2 * ALERT_BATCH, ALERT_BATCH],
    ],
  );
});

test('a failed post keeps the cursor, and the next round neither loses nor repeats', async () => {
  const { world, sent, lines, poller } = setup();
  world.alerts = [alert(1), alert(2), alert(3)];
  world.sendLimit = 1;
  assert.equal(await poller.tick(), false);
  assert.equal(poller.state().after, 1);
  assert.deepEqual(lines, ['relève interrompue : Error']);
  world.sendLimit = Infinity;
  assert.equal(await poller.tick(), true);
  assert.deepEqual(sent, ['**Alerte CERVEAU** : alerte 1', '**Alerte CERVEAU** : alerte 2', '**Alerte CERVEAU** : alerte 3']);
});

test('the daily report alert posts the report itself (D13)', async () => {
  const { world, sent, calls, poller } = setup();
  world.alerts = [alert(1, 'rapport_quotidien', '2026-10-16')];
  await poller.tick();
  assert.deepEqual(calls.find(([name]) => name === 'daily'), ['daily', '2026-10-16']);
  assert.deepEqual(sent, ['Rapport quotidien du 2026-10-16']);
});

test('an unreachable API delays the report; a refused report falls back to the alert', async () => {
  const { world, sent, lines, poller } = setup();
  world.alerts = [alert(1, 'rapport_quotidien', '2026-10-16'), alert(2, 'rapport_quotidien', '2026-10-17')];
  world.daily = new ApiFailure(null, null);
  assert.equal(await poller.tick(), false);
  assert.deepEqual(sent, []);
  assert.equal(poller.state().after, 0);
  world.daily = new ApiFailure(404, 'aucun rapport');
  assert.equal(await poller.tick(), true);
  assert.deepEqual(sent, ['**Alerte CERVEAU** : alerte 1', '**Alerte CERVEAU** : alerte 2']);
  assert.deepEqual(lines, [
    'relève interrompue : HTTP injoignable',
    'rapport indisponible : HTTP 404',
    'rapport indisponible : HTTP 404',
  ]);
});

test('each approval request is posted once, after the alerts, and forgotten once handled', async () => {
  const { world, sent, poller } = setup();
  world.alerts = [alert(1)];
  world.requests = [request(APPROVAL_ID), request(OTHER_ID)];
  await poller.tick();
  assert.equal(sent[0], '**Alerte CERVEAU** : alerte 1');
  assert.deepEqual(
    sent.slice(1).map((payload) => payload.components[0].toJSON().components[1].custom_id),
    [`refuse:${APPROVAL_ID}`, `refuse:${OTHER_ID}`],
  );
  assert.deepEqual(poller.state().posted, [APPROVAL_ID, OTHER_ID]);
  await poller.tick();
  assert.equal(sent.length, 3);
  world.requests = [request(OTHER_ID)];
  await poller.tick();
  assert.equal(sent.length, 3);
  assert.deepEqual(poller.state().posted, [OTHER_ID]);
});

test('a restart resumes from the saved cursor', async () => {
  const { world, sent, poller } = setup(memoryCursor({ after: 2, posted: [APPROVAL_ID] }));
  world.alerts = [alert(1), alert(2), alert(3)];
  world.requests = [request(APPROVAL_ID)];
  await poller.tick();
  assert.deepEqual(sent, ['**Alerte CERVEAU** : alerte 3']);
});

test('a round still running makes the next one wait its turn', async () => {
  const { world, sent, poller } = setup();
  world.alerts = [alert(1)];
  let release;
  world.gate = new Promise((resolve) => {
    release = resolve;
  });
  const first = poller.tick();
  assert.equal(await poller.tick(), false);
  release();
  assert.equal(await first, true);
  assert.equal(sent.length, 1);
});
