// What the bot does with an interaction. Lucas, in his private messages with the bot, is the
// only one answered: anyone else, anywhere else, is ignored and reported to the API for the
// journal, with neither identifier nor content (ADR-037, R5). The one-time code is relayed to
// the API and never logged, echoed or kept.

import { InteractionContextType } from 'discord.js';

import { describe } from './api.js';
import { CODE_FIELD, codeModal, parseCustomId } from './components.js';
import {
  approvalMessage,
  approveText,
  failureText,
  killFailure,
  killText,
  message,
  pendingText,
  refuseText,
  statusText,
} from './format.js';

export const KILL_REASON = 'arrêt demandé depuis Discord';
export const REFUSAL_REASON = 'refusée depuis Discord';
export const MAX_LISTED = 10;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Why an interaction is ignored, `utilisateur` or `salon`, or null when it is Lucas's. */
export function refusalOf(interaction, ownerId) {
  if (interaction.user?.id !== ownerId) return 'utilisateur';
  // The commands exist in the bot's private messages only; Discord may omit the context, but
  // never the server of an interaction that comes from one.
  const context = interaction.context ?? null;
  if (interaction.guildId != null || (context !== null && context !== InteractionContextType.BotDM)) {
    return 'salon';
  }
  return null;
}

export function createHandlers({ api, ownerId, log }) {
  async function respond(interaction, work) {
    await interaction.deferReply();
    let text;
    try {
      text = await work();
    } catch (error) {
      log(`échec : ${describe(error)}`);
      text = failureText(error);
    }
    await interaction.editReply(message(text));
  }

  const commands = new Map([
    ['status', (interaction) => respond(interaction, async () => statusText(await api.status()))],
    [
      'kill',
      async (interaction) => {
        const stopping = api.kill(KILL_REASON); // the stop leaves before the reply (D11)
        stopping.catch(() => {});
        await interaction.deferReply();
        let text;
        try {
          text = killText(await stopping);
        } catch (error) {
          log(`arrêt non confirmé : ${describe(error)}`);
          text = killFailure(error);
        }
        await interaction.editReply(message(text));
      },
    ],
    [
      'approbations',
      async (interaction) => {
        await interaction.deferReply();
        let pending;
        try {
          pending = await api.pending();
        } catch (error) {
          log(`échec : ${describe(error)}`);
          await interaction.editReply(message(failureText(error)));
          return;
        }
        await interaction.editReply(message(pendingText(pending, MAX_LISTED)));
        for (const request of pending.requests.slice(0, MAX_LISTED)) {
          await interaction.followUp(approvalMessage(request));
        }
      },
    ],
    [
      'rapport',
      (interaction) => {
        const day = interaction.options.getString('jour');
        return respond(interaction, async () => {
          if (day !== null && !DAY.test(day)) return 'Jour attendu au format AAAA-MM-JJ.';
          return (await api.daily(day ?? undefined)).text;
        });
      },
    ],
  ]);

  async function onCommand(interaction) {
    const run = commands.get(interaction.commandName);
    if (run === undefined) {
      log('commande inconnue ignorée');
      return;
    }
    await run(interaction);
  }

  async function onButton(interaction) {
    const parsed = parseCustomId(interaction.customId);
    if (parsed?.action === 'approve') {
      await interaction.showModal(codeModal(parsed.approvalId)); // within Discord's 3 s
    } else if (parsed?.action === 'refuse') {
      await respond(interaction, async () =>
        refuseText(await api.refuse(parsed.approvalId, REFUSAL_REASON)),
      );
    } else {
      log('bouton inconnu ignoré');
    }
  }

  async function onModal(interaction) {
    const parsed = parseCustomId(interaction.customId);
    if (parsed?.action !== 'code') {
      log('modale inconnue ignorée');
      return;
    }
    const code = interaction.fields.getTextInputValue(CODE_FIELD).trim();
    await respond(interaction, async () => approveText(await api.approve(parsed.approvalId, code)));
  }

  async function onInteraction(interaction) {
    const refusal = refusalOf(interaction, ownerId);
    if (refusal !== null) {
      log(`interaction ignorée (${refusal})`);
      try {
        await api.ignored(refusal);
      } catch (error) {
        log(`signalement impossible : ${describe(error)}`);
      }
      return;
    }
    try {
      if (interaction.isChatInputCommand()) await onCommand(interaction);
      else if (interaction.isButton()) await onButton(interaction);
      else if (interaction.isModalSubmit()) await onModal(interaction);
    } catch (error) {
      log(`interaction non traitée : ${describe(error)}`);
    }
  }

  return { onInteraction };
}
