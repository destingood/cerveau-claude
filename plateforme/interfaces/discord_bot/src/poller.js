// Every POLL_MS, the bot posts to the user the alerts of the Discord outbox (ADR-038) and the
// approval requests he has not seen yet. A cursor saved after each post means a restart neither
// loses nor repeats an alert; a failed post is tried again at the next round.

import { ApiFailure, describe } from './api.js';
import { alertText, approvalMessage } from './format.js';

export const POLL_MS = 15_000;
export const ALERT_BATCH = 50;

export function createPoller({ api, send, cursor, log }) {
  let state = cursor.load();
  let running = false;

  function save(next) {
    state = next;
    cursor.save(state);
  }

  async function alertMessage(alert) {
    if (alert.kind !== 'rapport_quotidien') return alertText(alert);
    try {
      return (await api.daily(alert.ref)).text; // the report itself, with the audit head (D13)
    } catch (error) {
      if (error instanceof ApiFailure && error.status === null) throw error; // next round
      log(`rapport indisponible : ${describe(error)}`);
      return alertText(alert);
    }
  }

  async function postAlerts() {
    for (;;) {
      const { alerts } = await api.alerts(state.after, ALERT_BATCH);
      for (const alert of alerts) {
        await send(await alertMessage(alert));
        save({ ...state, after: alert.seq });
      }
      if (alerts.length < ALERT_BATCH) return;
    }
  }

  async function postApprovals() {
    const { requests } = await api.pending();
    for (const request of requests) {
      if (state.posted.includes(request.approval_id)) continue;
      await send(approvalMessage(request));
      save({ ...state, posted: [...state.posted, request.approval_id] });
    }
    const waiting = new Set(requests.map((request) => request.approval_id));
    const kept = state.posted.filter((id) => waiting.has(id));
    if (kept.length !== state.posted.length) save({ ...state, posted: kept });
  }

  /** One round; false when another round is still running or this one stopped on an error. */
  async function tick() {
    if (running) return false;
    running = true;
    try {
      await postAlerts();
      await postApprovals();
      return true;
    } catch (error) {
      log(`relève interrompue : ${describe(error)}`);
      return false;
    } finally {
      running = false;
    }
  }

  return { tick, state: () => state };
}
