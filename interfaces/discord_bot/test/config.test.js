import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  API_TOKEN_ENV,
  API_URL_ENV,
  BotError,
  DISCORD_TOKEN_ENV,
  loopbackUrl,
  ownerId,
  readSettings,
} from '../src/config.js';

const API_TOKEN = 'a'.repeat(32);
const ENV = {
  [DISCORD_TOKEN_ENV]: 'discord-test-value',
  [API_TOKEN_ENV]: API_TOKEN,
  [API_URL_ENV]: 'http://127.0.0.1:8765',
};

test('the settings come from the environment, the API on the loopback', () => {
  assert.deepEqual(readSettings(ENV), {
    discordToken: 'discord-test-value',
    apiToken: API_TOKEN,
    apiUrl: 'http://127.0.0.1:8765',
  });
});

test('a missing bot token or a short API token stops the bot without showing a value', () => {
  assert.throws(() => readSettings({ ...ENV, [DISCORD_TOKEN_ENV]: ' ' }), BotError);
  const short = 'b'.repeat(31);
  assert.throws(
    () => readSettings({ ...ENV, [API_TOKEN_ENV]: short }),
    (error) => error instanceof BotError && !error.message.includes(short),
  );
  assert.throws(() => readSettings({ [DISCORD_TOKEN_ENV]: 'x', [API_URL_ENV]: ENV[API_URL_ENV] }), BotError);
});

test('the API is reached on the loopback only (D16)', () => {
  assert.equal(loopbackUrl('http://localhost:8765/'), 'http://localhost:8765');
  for (const raw of [
    '',
    'pas une url',
    'https://127.0.0.1:8765',
    'http://192.168.1.10:8765',
    'http://[::1]:8765',
    'http://evil.com:8765',
    'http://127.0.0.1.evil.com:8765',
    'http://127.0.0.1',
    'http://127.0.0.1:8765/api',
    'http://127.0.0.1:8765/?next=x',
    'http://127.0.0.1:8765/#x',
    'http://user:pw@127.0.0.1:8765',
  ]) {
    assert.throws(() => loopbackUrl(raw), BotError, raw);
  }
});

test("Lucas's identifier must be a Discord snowflake given as text", () => {
  assert.equal(ownerId({ owner_user_id: '123456789012345678' }), '123456789012345678');
  for (const settings of [
    { owner_user_id: 123456789012345678 },
    { owner_user_id: 'A_DEFINIR' },
    { owner_user_id: '012345678901234567' },
    { owner_user_id: '12345' },
    {},
    null,
  ]) {
    assert.throws(() => ownerId(settings), BotError);
  }
});
