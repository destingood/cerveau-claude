import assert from 'node:assert/strict';
import { test } from 'node:test';

import { InteractionContextType } from 'discord.js';

import { ApiFailure } from '../src/api.js';
import {
  KILL_REASON,
  MAX_LISTED,
  REFUSAL_REASON,
  createHandlers,
  refusalOf,
} from '../src/handlers.js';
import { APPROVAL_ID, OWNER, fakeApi, fakeInteraction, request } from './fakes.js';

const STRANGER = '987654321098765432';
const CODE = '482915';

function setup(overrides = {}) {
  const events = [];
  const lines = [];
  const { api, calls } = fakeApi(overrides, events);
  const handlers = createHandlers({ api, ownerId: OWNER, log: (line) => lines.push(line) });
  const run = async (options) => {
    const interaction = fakeInteraction({ events, ...options });
    await handlers.onInteraction(interaction);
    return interaction;
  };
  return { calls, events, lines, run };
}

const reply = (interaction) => interaction.sent.find(([name]) => name === 'editReply')?.[1];

test("only the user, in the bot's private messages, is answered", () => {
  const dm = { user: { id: OWNER }, guildId: null, context: InteractionContextType.BotDM };
  assert.equal(refusalOf(dm, OWNER), null);
  assert.equal(refusalOf({ ...dm, context: undefined }, OWNER), null); // Discord may omit it
  assert.equal(refusalOf({ ...dm, user: { id: STRANGER } }, OWNER), 'utilisateur');
  assert.equal(refusalOf({ ...dm, guildId: '111111111111111111' }, OWNER), 'salon');
  assert.equal(refusalOf({ ...dm, context: InteractionContextType.PrivateChannel }, OWNER), 'salon');
  assert.equal(refusalOf({ ...dm, context: InteractionContextType.Guild }, OWNER), 'salon');
});

test('anyone else is ignored and reported without identifier, even for /kill', async () => {
  const { calls, lines, run } = setup();
  const stranger = await run({ user: STRANGER, commandName: 'kill' });
  const server = await run({ guildId: '111111111111111111', commandName: 'kill' });
  assert.deepEqual(calls, [
    ['ignored', 'utilisateur'],
    ['ignored', 'salon'],
  ]);
  assert.deepEqual([...stranger.sent, ...server.sent], []);
  assert.deepEqual(lines, ['interaction ignorée (utilisateur)', 'interaction ignorée (salon)']);
});

test('an ignored interaction the API cannot record is logged', async () => {
  const { lines, run } = setup({
    ignored: () => {
      throw new ApiFailure(null, null);
    },
  });
  await run({ user: STRANGER, commandName: 'status' });
  assert.deepEqual(lines, [
    'interaction ignorée (utilisateur)',
    'signalement impossible : HTTP injoignable',
  ]);
});

test('/status answers with the state, mentioning nobody', async () => {
  const { events, run } = setup();
  const interaction = await run({ commandName: 'status' });
  assert.deepEqual(events, ['deferReply', 'status', 'editReply']);
  assert.ok(reply(interaction).content.startsWith('**État de CERVEAU**'));
  assert.deepEqual(reply(interaction).allowedMentions, { parse: [] });
});

test('/kill sends the stop before Discord hears back, without a code (D11)', async () => {
  const { calls, events, run } = setup();
  const interaction = await run({ commandName: 'kill' });
  assert.deepEqual(events, ['kill', 'deferReply', 'editReply']);
  assert.deepEqual(calls, [['kill', KILL_REASON]]);
  assert.ok(reply(interaction).content.startsWith('**Arrêt total engagé**'));
});

test('the stop leaves even when Discord loses the interaction', async () => {
  const { events, lines, run } = setup();
  await run({ commandName: 'kill', failOn: 'deferReply' });
  assert.deepEqual(events, ['kill', 'deferReply']);
  assert.deepEqual(lines, ['interaction non traitée : Error']);
});

test('an unconfirmed stop sends the user to his terminal', async () => {
  const { lines, run } = setup({
    kill: () => {
      throw new ApiFailure(null, null);
    },
  });
  const interaction = await run({ commandName: 'kill' });
  assert.ok(reply(interaction).content.startsWith('**Arrêt NON confirmé**'));
  assert.ok(reply(interaction).content.includes('`cerveau kill`'));
  assert.deepEqual(lines, ['arrêt non confirmé : HTTP injoignable']);
});

test('/approbations lists the pending requests, each with its buttons, ten at most', async () => {
  const requests = Array.from({ length: MAX_LISTED + 2 }, () => request());
  const { run } = setup({ pending: { open: true, reason: null, locked: false, requests } });
  const interaction = await run({ commandName: 'approbations' });
  const followUps = interaction.sent.filter(([name]) => name === 'followUp');
  assert.equal(reply(interaction).content, '12 demande(s) en attente ; les 10 plus anciennes suivent.');
  assert.equal(followUps.length, MAX_LISTED);
  assert.ok(followUps[0][1].content.startsWith("**Demande d'approbation**"));
  assert.equal(followUps[0][1].components.length, 1);
});

test('/approbations reports a failure and lists nothing', async () => {
  const { run } = setup({
    pending: () => {
      throw new ApiFailure(503, 'registre des approbations indisponible');
    },
  });
  const interaction = await run({ commandName: 'approbations' });
  assert.equal(reply(interaction).content, 'registre des approbations indisponible');
  assert.ok(!interaction.sent.some(([name]) => name === 'followUp'));
});

test('/rapport gives the daily report, for a given day or the last one', async () => {
  const { calls, run } = setup();
  const given = await run({ commandName: 'rapport', options: { jour: '2026-10-16' } });
  await run({ commandName: 'rapport' });
  const wrong = await run({ commandName: 'rapport', options: { jour: '16/10/2026' } });
  assert.deepEqual(calls, [
    ['daily', '2026-10-16'],
    ['daily', undefined],
  ]);
  assert.equal(reply(given).content, 'Rapport quotidien CERVEAU');
  assert.equal(reply(wrong).content, 'Jour attendu au format AAAA-MM-JJ.');
});

test('Approuver opens the code modal and calls nothing', async () => {
  const { calls, run } = setup();
  const interaction = await run({ kind: 'button', customId: `approve:${APPROVAL_ID}` });
  assert.deepEqual(calls, []);
  assert.equal(interaction.sent.length, 1);
  const [name, modal] = interaction.sent[0];
  assert.equal(name, 'showModal');
  assert.equal(modal.toJSON().custom_id, `code:${APPROVAL_ID}`);
});

test('Refuser refuses the request', async () => {
  const { calls, run } = setup();
  const interaction = await run({ kind: 'button', customId: `refuse:${APPROVAL_ID}` });
  assert.deepEqual(calls, [['refuse', APPROVAL_ID, REFUSAL_REASON]]);
  assert.equal(reply(interaction).content, 'Demande **refusée**.');
});

test('the code goes to the API and nowhere else', async () => {
  for (const approve of [
    undefined,
    () => {
      throw new ApiFailure(409, 'code refusé');
    },
  ]) {
    const { calls, lines, run } = setup(approve ? { approve } : {});
    const interaction = await run({
      kind: 'modal',
      customId: `code:${APPROVAL_ID}`,
      fields: { code: ` ${CODE} ` },
    });
    assert.deepEqual(calls, [['approve', APPROVAL_ID, CODE]]);
    assert.ok(reply(interaction).content.length > 0);
    assert.ok(!JSON.stringify(interaction.sent).includes(CODE));
    assert.ok(!lines.join('\n').includes(CODE));
  }
});

test('custom ids the bot did not write, and unknown commands, are ignored', async () => {
  const { calls, lines, run } = setup();
  const interactions = [
    await run({ kind: 'button', customId: 'approve:../kill' }),
    await run({ kind: 'button', customId: `code:${APPROVAL_ID}` }),
    await run({ kind: 'modal', customId: `approve:${APPROVAL_ID}`, fields: { code: CODE } }),
    await run({ commandName: 'rearm' }),
  ];
  assert.deepEqual(calls, []);
  assert.deepEqual(
    interactions.flatMap((interaction) => interaction.sent),
    [],
  );
  assert.deepEqual(lines, [
    'bouton inconnu ignoré',
    'bouton inconnu ignoré',
    'modale inconnue ignorée',
    'commande inconnue ignorée',
  ]);
});
