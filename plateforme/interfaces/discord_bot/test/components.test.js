import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ApplicationIntegrationType,
  ButtonStyle,
  ComponentType,
  InteractionContextType,
  TextInputStyle,
} from 'discord.js';

import {
  CODE_FIELD,
  COMMANDS,
  approvalButtons,
  codeModal,
  parseCustomId,
} from '../src/components.js';
import { APPROVAL_ID } from './fakes.js';

test("four commands, in the bot's private messages only, and none rearms", () => {
  assert.deepEqual(
    COMMANDS.map((command) => command.name),
    ['status', 'kill', 'approbations', 'rapport'],
  );
  for (const command of COMMANDS) {
    assert.deepEqual(command.contexts, [InteractionContextType.BotDM]);
    assert.deepEqual(command.integration_types, [ApplicationIntegrationType.GuildInstall]);
  }
  const [day] = COMMANDS[3].options;
  assert.equal(day.name, 'jour');
  assert.equal(day.required, false);
});

test('an approval request offers Approuver and Refuser', () => {
  const [row] = approvalButtons(APPROVAL_ID).map((component) => component.toJSON());
  assert.equal(row.type, ComponentType.ActionRow);
  assert.deepEqual(
    row.components.map(({ custom_id, label, style }) => [custom_id, label, style]),
    [
      [`approve:${APPROVAL_ID}`, 'Approuver', ButtonStyle.Success],
      [`refuse:${APPROVAL_ID}`, 'Refuser', ButtonStyle.Danger],
    ],
  );
});

test('Approuver opens a modal that asks for the code in a label', () => {
  const modal = codeModal(APPROVAL_ID).toJSON();
  assert.equal(modal.custom_id, `code:${APPROVAL_ID}`);
  const [label] = modal.components;
  assert.equal(label.type, ComponentType.Label);
  assert.deepEqual(label.component, {
    type: ComponentType.TextInput,
    custom_id: CODE_FIELD,
    style: TextInputStyle.Short,
    min_length: 6,
    max_length: 8,
    required: true,
  });
});

test('only the custom ids the bot writes are understood', () => {
  assert.deepEqual(parseCustomId(`refuse:${APPROVAL_ID}`), {
    action: 'refuse',
    approvalId: APPROVAL_ID,
  });
  for (const customId of [
    `approve:${APPROVAL_ID.toUpperCase()}`,
    `approve:${APPROVAL_ID}:x`,
    `rearm:${APPROVAL_ID}`,
    'approve:../kill',
    '',
    undefined,
  ]) {
    assert.equal(parseCustomId(customId), null, String(customId));
  }
});
