// What the bot puts in front of the user: slash commands, the approval buttons and the code modal,
// built with discord.js 14.27's builders, which check Discord's limits (ADR-037).

import {
  ActionRowBuilder,
  ApplicationIntegrationType,
  ButtonBuilder,
  ButtonStyle,
  InteractionContextType,
  LabelBuilder,
  ModalBuilder,
  SlashCommandBuilder,
  TextInputBuilder,
  TextInputStyle,
} from 'discord.js';

export const CODE_FIELD = 'code';
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const CUSTOM_ID = new RegExp(`^(approve|refuse|code):(${UUID})$`);

// the user's private messages with the bot only: no server, no group, no user install.
const privateOnly = (command) =>
  command
    .setContexts(InteractionContextType.BotDM)
    .setIntegrationTypes(ApplicationIntegrationType.GuildInstall);

// There is no rearm command: rearming stays at the user's interactive terminal (ADR-034).
export const COMMANDS = [
  new SlashCommandBuilder()
    .setName('status')
    .setDescription('État de CERVEAU : kill switch, live, niveaux, approbations, ordres, budget'),
  new SlashCommandBuilder()
    .setName('kill')
    .setDescription('Arrêt total de CERVEAU, sans code (D11)'),
  new SlashCommandBuilder()
    .setName('approbations')
    .setDescription("Demandes d'approbation en attente"),
  new SlashCommandBuilder()
    .setName('rapport')
    .setDescription('Rapport quotidien')
    .addStringOption((option) =>
      option
        .setName('jour')
        .setDescription('AAAA-MM-JJ ; par défaut, la dernière journée traitée')
        .setMinLength(10)
        .setMaxLength(10),
    ),
].map((command) => privateOnly(command).toJSON());

export function approvalButtons(approvalId) {
  return [
    new ActionRowBuilder().addComponents(
      new ButtonBuilder()
        .setCustomId(`approve:${approvalId}`)
        .setLabel('Approuver')
        .setStyle(ButtonStyle.Success),
      new ButtonBuilder()
        .setCustomId(`refuse:${approvalId}`)
        .setLabel('Refuser')
        .setStyle(ButtonStyle.Danger),
    ),
  ];
}

export function codeModal(approvalId) {
  return new ModalBuilder()
    .setCustomId(`code:${approvalId}`)
    .setTitle("Code d'approbation")
    .addLabelComponents(
      new LabelBuilder()
        .setLabel('Code à usage unique')
        .setDescription("Les 6 chiffres de ton application d'authentification")
        .setTextInputComponent(
          new TextInputBuilder()
            .setCustomId(CODE_FIELD)
            .setStyle(TextInputStyle.Short)
            .setMinLength(6)
            .setMaxLength(8)
            .setRequired(true),
        ),
    );
}

/** `{action, approvalId}` from a custom id the bot wrote, or null for anything else. */
export function parseCustomId(customId) {
  const match = CUSTOM_ID.exec(customId ?? '');
  return match ? { action: match[1], approvalId: match[2] } : null;
}
