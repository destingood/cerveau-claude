// Where the bot keeps what it already posted: the last alert's sequence number and the approval
// requests it showed. A file it cannot read stops the bot rather than post everything again.

import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

import { BotError } from './config.js';

const isValid = (data) =>
  Number.isSafeInteger(data?.after) &&
  data.after >= 0 &&
  Array.isArray(data.posted) &&
  data.posted.every((id) => typeof id === 'string');

export function fileCursor(path) {
  return {
    load() {
      let raw;
      try {
        raw = readFileSync(path, 'utf8');
      } catch (error) {
        if (error.code === 'ENOENT') return { after: 0, posted: [] };
        throw error;
      }
      let data = null;
      try {
        data = JSON.parse(raw);
      } catch {
        // reported below
      }
      if (!isValid(data)) {
        throw new BotError(
          `curseur illisible (${path}) : sans lui, toutes les alertes seraient republiées`,
        );
      }
      return { after: data.after, posted: [...data.posted] };
    },
    save(state) {
      mkdirSync(dirname(path), { recursive: true });
      const temporary = `${path}.tmp`;
      writeFileSync(temporary, `${JSON.stringify(state)}\n`, 'utf8');
      renameSync(temporary, path); // a crash leaves the old cursor or the new one, never half
    },
  };
}
