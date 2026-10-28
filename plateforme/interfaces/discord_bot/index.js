// CERVEAU's Discord bot (ADR-037). Only Lucas starts it (D22): `npm start` in this folder, with
// DISCORD_BOT_TOKEN, CERVEAU_API_TOKEN and CERVEAU_API_URL set and the internal API running.
// It refuses to start while config/interfaces.yaml leaves its owner A_DEFINIR (R7).

import { fileURLToPath } from 'node:url';

import { Client, Events } from 'discord.js';

import { ApiFailure, createApi } from './src/api.js';
import { COMMANDS } from './src/components.js';
import { BotError, ownerId, readSettings } from './src/config.js';
import { fileCursor } from './src/cursor.js';
import { failureText, message } from './src/format.js';
import { createHandlers } from './src/handlers.js';
import { POLL_MS, createPoller } from './src/poller.js';

const CURSOR = fileURLToPath(new URL('../../var/notify/discord_cursor.json', import.meta.url));
const log = (line) => console.log(`[cerveau-bot] ${line}`);

async function main() {
  const settings = readSettings(process.env);
  const api = createApi({ baseUrl: settings.apiUrl, token: settings.apiToken });
  const owner = ownerId(await api.settings());
  const cursor = fileCursor(CURSOR);
  cursor.load(); // an unreadable cursor stops the bot before it connects

  // No gateway intent: slash commands, buttons and modals reach the bot without one, and it
  // reads no message.
  const client = new Client({ intents: [] });
  const handlers = createHandlers({ api, ownerId: owner, log });
  client.on(Events.InteractionCreate, (interaction) => handlers.onInteraction(interaction));

  let timer;
  client.once(Events.ClientReady, async (ready) => {
    try {
      await ready.application.commands.set(COMMANDS);
      const lucas = await ready.users.fetch(owner);
      const poller = createPoller({
        api,
        send: (payload) => lucas.send(message(payload)),
        cursor,
        log,
      });
      timer = setInterval(() => poller.tick(), POLL_MS);
      await poller.tick();
      log('prêt');
    } catch (error) {
      log(`démarrage interrompu : ${error?.name ?? 'erreur'}`);
      process.exitCode = 1;
      await client.destroy();
    }
  });

  const stop = async () => {
    clearInterval(timer);
    await client.destroy();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  await client.login(settings.discordToken);
}

main().catch((error) => {
  // Known refusals carry a French message without any value; other errors, their kind only.
  let text = error?.name ?? 'erreur';
  if (error instanceof BotError) text = error.message;
  else if (error instanceof ApiFailure) text = failureText(error);
  console.error(`[cerveau-bot] ${text}`);
  process.exitCode = 1;
});
