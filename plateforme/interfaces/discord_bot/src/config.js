// The bot's settings come from the user's environment only, and no value is ever printed (R6).
// Whom it answers comes from the API (`GET /bot/settings`), read from config/interfaces.yaml.

export const DISCORD_TOKEN_ENV = 'DISCORD_BOT_TOKEN';
export const API_TOKEN_ENV = 'CERVEAU_API_TOKEN';
export const API_URL_ENV = 'CERVEAU_API_URL';
export const MIN_API_TOKEN_CHARS = 32;
const LOOPBACK = new Set(['127.0.0.1', 'localhost']);
const SNOWFLAKE = /^[1-9][0-9]{16,19}$/;

export class BotError extends Error {
  name = 'BotError';
}

export function readSettings(env) {
  const discordToken = env[DISCORD_TOKEN_ENV] ?? '';
  const apiToken = env[API_TOKEN_ENV] ?? '';
  if (discordToken.trim() === '') {
    throw new BotError(`${DISCORD_TOKEN_ENV} absente : le bot ne démarre pas`);
  }
  if (apiToken.length < MIN_API_TOKEN_CHARS) {
    throw new BotError(
      `${API_TOKEN_ENV} absente ou trop courte (${MIN_API_TOKEN_CHARS} caractères au moins) : ` +
        'le bot ne démarre pas',
    );
  }
  return { discordToken, apiToken, apiUrl: loopbackUrl(env[API_URL_ENV] ?? '') };
}

/** The API's origin, on the loopback only (D16): http://127.0.0.1:<port> or localhost. */
export function loopbackUrl(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new BotError(`${API_URL_ENV} absente ou illisible, par exemple http://127.0.0.1:<port>`);
  }
  const bare = url.pathname === '/' && !url.search && !url.hash && !url.username && !url.password;
  if (url.protocol !== 'http:' || !LOOPBACK.has(url.hostname) || !url.port || !bare) {
    throw new BotError(`${API_URL_ENV} doit viser la boucle locale : http://127.0.0.1:<port> (D16)`);
  }
  return url.origin;
}

/** the user's Discord identifier as the API gives it; anything else stops the bot. */
export function ownerId(settings) {
  const id = settings?.owner_user_id;
  if (typeof id !== 'string' || !SNOWFLAKE.test(id)) {
    throw new BotError("identifiant Discord de l'utilisateur illisible dans la réponse de l'API");
  }
  return id;
}
