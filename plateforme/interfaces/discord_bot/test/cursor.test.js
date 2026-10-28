import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';

import { BotError } from '../src/config.js';
import { fileCursor } from '../src/cursor.js';

const root = mkdtempSync(join(tmpdir(), 'cerveau-bot-'));
after(() => rmSync(root, { recursive: true, force: true }));

test('a missing cursor starts from the beginning without creating a file', () => {
  const path = join(root, 'absent', 'cursor.json');
  assert.deepEqual(fileCursor(path).load(), { after: 0, posted: [] });
  assert.equal(existsSync(path), false);
});

test('a saved cursor reads back the same, with no temporary file left', () => {
  const path = join(root, 'var', 'notify', 'cursor.json');
  const cursor = fileCursor(path);
  cursor.save({ after: 7, posted: ['01929f3e-7a1b-7c2d-8e3f-123456789abc'] });
  assert.deepEqual(cursor.load(), { after: 7, posted: ['01929f3e-7a1b-7c2d-8e3f-123456789abc'] });
  assert.equal(existsSync(`${path}.tmp`), false);
  assert.ok(readFileSync(path, 'utf8').endsWith('\n'));
});

test('an unreadable cursor stops the bot rather than post everything again', () => {
  const path = join(root, 'corrupt.json');
  for (const raw of [
    'pas du json',
    '[]',
    '{"after": -1, "posted": []}',
    '{"after": 1.5, "posted": []}',
    '{"after": 1, "posted": [1]}',
    '{"after": 1}',
  ]) {
    writeFileSync(path, raw, 'utf8');
    assert.throws(
      () => fileCursor(path).load(),
      (error) => error instanceof BotError && error.message.startsWith('curseur illisible'),
      raw,
    );
  }
});
