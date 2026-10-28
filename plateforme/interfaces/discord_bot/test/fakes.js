// A fake API and a fake Discord interaction: the tests reach neither the API nor Discord.

import { InteractionContextType } from 'discord.js';

export const OWNER = '123456789012345678';
export const APPROVAL_ID = '01929f3e-7a1b-7c2d-8e3f-123456789abc';

export const STATUS = {
  kill_switch: { engaged: false, trigger: null, engaged_at: null },
  live: { enabled: false },
  autonomy: {
    domains: [
      { domain: 'finance', written: 'N3', effective: 'N2' },
      { domain: 'generaliste', written: 'N1', effective: 'N1' },
    ],
    capped: ['finance : N3 écrit, N2 signé'],
    problems: [],
  },
  approvals: { open: true, reason: null, pending: 1, granted: 0, locked: false },
  orders: { open: 2, total: 5 },
  reconciliation: { last_at: '2026-10-21T08:00:00+00:00', open_gaps: 0, awaiting_acknowledgement: false },
  loop: { last_day: '2026-10-16', completed_at: '2026-10-16T18:00:00+00:00' },
  budget: { defined: false, reason: 'budgets à définir (R7)', day_pct: null, month_pct: null },
};

export const STOP = {
  request_id: 'api-1',
  trigger: 'commande',
  elapsed_s: 1.25,
  target_s: 5,
  within_target: true,
  cancelled: 2,
  broker_cancelled: 0,
  unconfirmed: 0,
  unknown: 0,
  approvals_refused: 1,
  errors: [],
  alerts_failed: 0,
  clean: true,
};

export function request(approvalId = APPROVAL_ID) {
  return {
    approval_id: approvalId,
    intent_id: '01929f3e-0000-7000-8000-000000000001',
    environment: 'paper',
    summary: 'Achat de 3 CW8 à 512,40 EUR au plus',
    created_at: '2026-10-21T12:00:00+00:00',
    expires_at: '2026-10-21T12:15:00+00:00',
    attempts_left: 3,
    gate: { result: 'accepte', requested_quantity: 4, quantity: 3, failed_checks: ['secteur'] },
  };
}

export const GRANTED = {
  state: 'ACCORDEE',
  accepted: true,
  attempts_left: 3,
  locked: false,
  alerts_failed: 0,
  sending: { outcome: 'envoye', sent: [{ order: 'ENVOYE', reasons: [] }], notes: [] },
};

/** Every call lands in `events`, shared with the interaction, so their order can be checked. */
export function fakeApi(overrides = {}, events = []) {
  const answers = {
    settings: { owner_user_id: OWNER },
    status: STATUS,
    kill: STOP,
    pending: { open: true, reason: null, locked: false, requests: [request()] },
    approve: GRANTED,
    refuse: { state: 'REFUSEE' },
    daily: { text: 'Rapport quotidien CERVEAU' },
    alerts: { alerts: [] },
    ignored: { request_id: 'api-2' },
    ...overrides,
  };
  const calls = [];
  const api = {};
  for (const [name, answer] of Object.entries(answers)) {
    api[name] = async (...args) => {
      calls.push([name, ...args]);
      events.push(name);
      return typeof answer === 'function' ? answer(...args) : structuredClone(answer);
    };
  }
  return { api, calls, events };
}

export function fakeInteraction({
  kind = 'command',
  user = OWNER,
  guildId = null,
  context = InteractionContextType.BotDM,
  commandName,
  customId,
  options = {},
  fields = {},
  events = [],
  failOn = null,
} = {}) {
  const sent = [];
  const act = (name) => async (payload) => {
    events.push(name);
    if (failOn === name) throw new Error('Unknown interaction');
    sent.push([name, payload]);
  };
  return {
    user: { id: user },
    guildId,
    context,
    commandName,
    customId,
    options: { getString: (name) => options[name] ?? null },
    fields: { getTextInputValue: (name) => fields[name] },
    isChatInputCommand: () => kind === 'command',
    isButton: () => kind === 'button',
    isModalSubmit: () => kind === 'modal',
    deferReply: act('deferReply'),
    editReply: act('editReply'),
    followUp: act('followUp'),
    showModal: act('showModal'),
    reply: act('reply'),
    sent,
  };
}

export function memoryCursor(initial = { after: 0, posted: [] }) {
  const saves = [];
  return {
    saves,
    load: () => structuredClone(initial),
    save: (state) => saves.push(structuredClone(state)),
  };
}
