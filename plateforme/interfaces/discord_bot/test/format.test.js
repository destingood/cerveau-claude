import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiFailure } from '../src/api.js';
import {
  alertText,
  approvalMessage,
  approvalText,
  approveText,
  failureText,
  killFailure,
  killText,
  message,
  pendingText,
  refuseText,
  statusText,
} from '../src/format.js';
import { APPROVAL_ID, GRANTED, STATUS, STOP, request } from './fakes.js';

const unix = (iso) => Date.parse(iso) / 1000;

test('a payload never mentions anyone, whatever its text holds', () => {
  assert.deepEqual(message('@everyone'), { content: '@everyone', allowedMentions: { parse: [] } });
  const payload = message({ content: 'x', allowedMentions: { parse: ['everyone'] } });
  assert.deepEqual(payload.allowedMentions, { parse: [] });
});

test('the status shows the switch, the live mode, the capped levels and an undefined budget', () => {
  const text = statusText(STATUS);
  for (const line of [
    'Kill switch : armé.',
    'Live : désactivé.',
    'Niveaux en vigueur : finance N2 (N3 écrit), generaliste N1.',
    'Approbations : 1 en attente, 0 accordée(s).',
    'Ordres : 2 ouvert(s) sur 5.',
    `Réconciliation : dernière <t:${unix('2026-10-21T08:00:00Z')}:f> ; 0 écart(s) ouvert(s).`,
    `Boucle : dernière journée 16/10/2026, terminée <t:${unix('2026-10-16T18:00:00Z')}:f>.`,
    'Budget LLM : budgets à définir (R7).',
  ]) {
    assert.ok(text.split('\n').includes(line), line);
  }
  assert.ok(!text.includes('Signatures'));
});

test('an engaged switch, closed approvals and a defined budget are spelled out', () => {
  const text = statusText({
    ...STATUS,
    kill_switch: { engaged: true, trigger: 'discord', engaged_at: '2026-10-21T12:00:00+00:00' },
    autonomy: { ...STATUS.autonomy, problems: ['signature absente'] },
    approvals: { open: false, reason: 'kill switch engagé', pending: 0, granted: 0, locked: false },
    reconciliation: { last_at: null, open_gaps: 1, awaiting_acknowledgement: true },
    loop: { last_day: null, completed_at: null },
    budget: { defined: true, reason: null, day_pct: 12.5, month_pct: 40 },
  });
  for (const line of [
    `Kill switch : **ENGAGÉ** (discord) <t:${unix('2026-10-21T12:00:00Z')}:f>.`,
    'Signatures : 1 problème(s), voir `cerveau status`.',
    'Approbations : kill switch engagé.',
    'Réconciliation : aucune ; 1 écart(s) ouvert(s), accusé de réception attendu.',
    'Boucle : aucune journée traitée.',
    'Budget LLM : 12,5 % du jour, 40 % du mois.',
  ]) {
    assert.ok(text.split('\n').includes(line), line);
  }
});

test('the stop reports its time against the target and never offers to rearm here', () => {
  const text = killText(STOP);
  assert.equal(
    text,
    [
      '**Arrêt total engagé** en 1,25 s (cible de 5 s tenue).',
      'Ordres annulés : 2 ; chez le courtier : 0 ; non confirmés : 0 ; inconnus : 0.',
      'Approbations refusées : 1.',
      'Arrêt propre.',
      'Le réarmement se fait seulement dans ton terminal (ADR-034).',
    ].join('\n'),
  );
  const late = killText({ ...STOP, elapsed_s: 6.5, within_target: false });
  assert.ok(late.includes('en 6,5 s (cible de 5 s **DÉPASSÉE**)'));
  const unclean = killText({
    ...STOP,
    target_s: null,
    within_target: null,
    errors: ['annulation : HTTP 503'],
    alerts_failed: 2,
    clean: false,
  });
  assert.ok(unclean.includes('(cible non définie)'));
  assert.ok(unclean.includes("Erreurs : 1, voir le journal d'audit."));
  assert.ok(unclean.includes('Alertes non envoyées : 2.'));
  assert.ok(unclean.includes('**Arrêt incomplet**'));
});

test('a stop the API did not confirm sends the user to his terminal', () => {
  assert.equal(
    killFailure(new ApiFailure(null, null)),
    '**Arrêt NON confirmé** : API interne injoignable : est-elle lancée ?.\n' +
      'Lance `cerveau kill` dans un terminal.',
  );
});

test("a failure reads as the API wrote it, and a bot error never shows its text", () => {
  assert.equal(failureText(new ApiFailure(409, 'approbation déjà traitée')), 'approbation déjà traitée');
  assert.equal(failureText(new ApiFailure(500, null)), "erreur de l'API interne (HTTP 500)");
  assert.equal(failureText(new ApiFailure(401, 'jeton invalide')), "jeton refusé par l'API interne");
  assert.equal(failureText(new ApiFailure(null, null)), 'API interne injoignable : est-elle lancée ?');
  assert.equal(failureText(new TypeError('valeur 482915')), 'erreur interne du bot');
});

test('an approval request names the order, the gate, the failed checks and the deadline', () => {
  const deadline = unix('2026-10-21T12:15:00Z');
  assert.equal(
    approvalText(request()),
    [
      "**Demande d'approbation** (compte paper)",
      'Achat de 3 CW8 à 512,40 EUR au plus',
      'Porte de risque : accepte ; quantité retenue 3 sur 4 demandée(s).',
      'Contrôles en échec : secteur.',
      `Échéance : <t:${deadline}:f> (<t:${deadline}:R>).`,
      'Essais de code restants : 3.',
    ].join('\n'),
  );
  const clean = request();
  clean.gate.failed_checks = [];
  clean.expires_at = null;
  const text = approvalText(clean);
  assert.ok(text.includes('Contrôles en échec : aucun.'));
  assert.ok(text.includes('Échéance : à une date inconnue'));
  const payload = approvalMessage(request());
  assert.deepEqual(payload.allowedMentions, { parse: [] });
  assert.equal(payload.components[0].toJSON().components[0].custom_id, `approve:${APPROVAL_ID}`);
});

test('the pending list says how many requests wait and whether codes are locked', () => {
  const pending = { open: true, reason: null, locked: false, requests: [request()] };
  assert.equal(pendingText(pending, 10), '1 demande(s) en attente.');
  assert.equal(
    pendingText({ ...pending, requests: [], locked: true }, 10),
    'Aucune demande en attente ; approbations **verrouillées**.',
  );
  const many = { ...pending, requests: Array.from({ length: 12 }, () => request()) };
  assert.equal(pendingText(many, 10), '12 demande(s) en attente ; les 10 plus anciennes suivent.');
  assert.equal(pendingText({ open: false, reason: 'kill switch engagé' }, 10), 'kill switch engagé.');
});

test('the answer to a code says whether the intent is granted and what was sent', () => {
  assert.equal(
    approveText(GRANTED),
    'Code accepté : intention **accordée**.\nEnvoi au compte paper : envoye.\nOrdre ENVOYE.',
  );
  assert.equal(
    approveText({ state: 'EN_ATTENTE', accepted: false, attempts_left: 2, locked: false }),
    'Code refusé. Essais restants : 2.',
  );
  const spent = approveText({
    state: 'REFUSEE',
    accepted: false,
    attempts_left: 0,
    locked: true,
    alerts_failed: 1,
  });
  assert.ok(spent.includes('Essais épuisés : la demande est **refusée**.'));
  assert.ok(spent.includes('**verrouillées**'));
  assert.ok(spent.includes('Alertes non envoyées : 1.'));
});

test('refusals and alerts', () => {
  assert.equal(refuseText({ state: 'REFUSEE' }), 'Demande **refusée**.');
  assert.equal(refuseText({ state: 'EXPIREE' }), 'Demande : EXPIREE.');
  assert.equal(alertText({ text: 'écart de réconciliation' }), '**Alerte CERVEAU** : écart de réconciliation');
});
