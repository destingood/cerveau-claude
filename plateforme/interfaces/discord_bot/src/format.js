// The texts the user reads, in French. States, counts and percentages only (D12): the one message
// that names an amount is the approval request, whose summary comes from CERVEAU itself.
// Dates are Discord timestamps, which each client shows in its own time zone.

import { TimestampStyles, time } from 'discord.js';

import { ApiFailure } from './api.js';
import { approvalButtons } from './components.js';

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A payload that mentions nobody, whatever its text holds. */
export function message(payload) {
  const base = typeof payload === 'string' ? { content: payload } : payload;
  return { ...base, allowedMentions: { parse: [] } };
}

function when(iso, style = TimestampStyles.ShortDateTime) {
  const ms = Date.parse(iso ?? '');
  return Number.isNaN(ms) ? 'à une date inconnue' : time(new Date(ms), style);
}

function day(iso) {
  const match = DAY.exec(iso ?? '');
  return match ? `${match[3]}/${match[2]}/${match[1]}` : String(iso);
}

const decimal = (value) => String(value).replace('.', ',');

export function failureText(error) {
  if (!(error instanceof ApiFailure)) return 'erreur interne du bot';
  if (error.status === null) return 'API interne injoignable : est-elle lancée ?';
  if (error.status === 401) return "jeton refusé par l'API interne";
  return error.detail ?? `erreur de l'API interne (HTTP ${error.status})`;
}

export function statusText(status) {
  const { kill_switch: kill, autonomy, approvals, orders, reconciliation, loop, budget } = status;
  const levels = autonomy.domains.map(({ domain, written, effective }) =>
    written === effective ? `${domain} ${effective}` : `${domain} ${effective} (${written} écrit)`,
  );
  const lines = [
    '**État de CERVEAU**',
    kill.engaged
      ? `Kill switch : **ENGAGÉ** (${kill.trigger ?? 'déclencheur inconnu'}) ${when(kill.engaged_at)}.`
      : 'Kill switch : armé.',
    `Live : ${status.live.enabled ? '**ACTIVÉ**' : 'désactivé'}.`,
    `Niveaux en vigueur : ${levels.length ? levels.join(', ') : 'aucun domaine'}.`,
  ];
  if (autonomy.problems.length) {
    lines.push(`Signatures : ${autonomy.problems.length} problème(s), voir \`cerveau status\`.`);
  }
  lines.push(
    approvals.open
      ? `Approbations : ${approvals.pending} en attente, ${approvals.granted} accordée(s)` +
          `${approvals.locked ? ', **verrouillées**' : ''}.`
      : `Approbations : ${approvals.reason}.`,
    `Ordres : ${orders.open} ouvert(s) sur ${orders.total}.`,
    `Réconciliation : ${reconciliation.last_at ? `dernière ${when(reconciliation.last_at)}` : 'aucune'}` +
      ` ; ${reconciliation.open_gaps} écart(s) ouvert(s)` +
      `${reconciliation.awaiting_acknowledgement ? ', accusé de réception attendu' : ''}.`,
    loop.last_day
      ? `Boucle : dernière journée ${day(loop.last_day)}, terminée ${when(loop.completed_at)}.`
      : 'Boucle : aucune journée traitée.',
    budget.defined
      ? `Budget LLM : ${decimal(budget.day_pct)} % du jour, ${decimal(budget.month_pct)} % du mois.`
      : `Budget LLM : ${budget.reason}.`,
  );
  return lines.join('\n');
}

export function killText(stop) {
  let target = 'cible non définie';
  if (stop.target_s !== null) {
    const verdict = stop.within_target ? 'tenue' : '**DÉPASSÉE**';
    target = `cible de ${decimal(stop.target_s)} s ${verdict}`;
  }
  const lines = [
    `**Arrêt total engagé** en ${decimal(stop.elapsed_s)} s (${target}).`,
    `Ordres annulés : ${stop.cancelled} ; chez le courtier : ${stop.broker_cancelled} ; ` +
      `non confirmés : ${stop.unconfirmed} ; inconnus : ${stop.unknown}.`,
    `Approbations refusées : ${stop.approvals_refused}.`,
  ];
  if (stop.errors.length) lines.push(`Erreurs : ${stop.errors.length}, voir le journal d'audit.`);
  if (stop.alerts_failed) lines.push(`Alertes non envoyées : ${stop.alerts_failed}.`);
  lines.push(
    stop.clean ? 'Arrêt propre.' : '**Arrêt incomplet** : vérifie avec `cerveau status` dans un terminal.',
    'Le réarmement se fait seulement dans ton terminal (ADR-034).',
  );
  return lines.join('\n');
}

export function killFailure(error) {
  return `**Arrêt NON confirmé** : ${failureText(error)}.\nLance \`cerveau kill\` dans un terminal.`;
}

export function approvalText(request) {
  const { gate } = request;
  const failed = gate.failed_checks.length ? gate.failed_checks.join(', ') : 'aucun';
  return [
    `**Demande d'approbation** (compte ${request.environment})`,
    request.summary,
    `Porte de risque : ${gate.result ?? 'résultat inconnu'} ; quantité retenue ` +
      `${gate.quantity ?? '?'} sur ${gate.requested_quantity ?? '?'} demandée(s).`,
    `Contrôles en échec : ${failed}.`,
    `Échéance : ${when(request.expires_at)} (${when(request.expires_at, TimestampStyles.RelativeTime)}).`,
    `Essais de code restants : ${request.attempts_left}.`,
  ].join('\n');
}

export function approvalMessage(request) {
  return message({ content: approvalText(request), components: approvalButtons(request.approval_id) });
}

export function pendingText(pending, listed) {
  if (!pending.open) return `${pending.reason ?? 'registre des approbations fermé'}.`;
  const count = pending.requests.length;
  const locked = pending.locked ? ' ; approbations **verrouillées**' : '';
  if (!count) return `Aucune demande en attente${locked}.`;
  const more = count > listed ? ` ; les ${listed} plus anciennes suivent` : '';
  return `${count} demande(s) en attente${locked}${more}.`;
}

export function approveText(outcome) {
  const lines = [];
  if (outcome.accepted) {
    lines.push('Code accepté : intention **accordée**.');
    const sending = outcome.sending;
    if (sending) {
      lines.push(`Envoi au compte paper : ${sending.outcome}.`);
      for (const item of sending.sent) {
        const reasons = item.reasons.length ? ` (${item.reasons.join(', ')})` : '';
        lines.push(`Ordre ${item.order}${reasons}.`);
      }
      lines.push(...sending.notes);
    }
  } else {
    lines.push(`Code refusé. Essais restants : ${outcome.attempts_left}.`);
    if (outcome.state === 'REFUSEE') lines.push('Essais épuisés : la demande est **refusée**.');
  }
  if (outcome.locked) {
    lines.push("Approbations **verrouillées** après trop d'échecs : aucun code n'est accepté pour l'instant.");
  }
  if (outcome.alerts_failed) lines.push(`Alertes non envoyées : ${outcome.alerts_failed}.`);
  return lines.join('\n');
}

export function refuseText(answer) {
  return answer.state === 'REFUSEE' ? 'Demande **refusée**.' : `Demande : ${answer.state}.`;
}

export function alertText(alert) {
  return `**Alerte CERVEAU** : ${alert.text}`;
}
