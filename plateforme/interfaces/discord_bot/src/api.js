// The bot's only door into CERVEAU: the local internal API (ADR-037). The bot decides nothing;
// a refusal, a lock or a stop is the API's answer, relayed as it is.

export const TIMEOUT_MS = 10_000;

export class ApiFailure extends Error {
  name = 'ApiFailure';

  /** `status` is null when the API could not be reached; `detail` is the API's own text. */
  constructor(status, detail) {
    super(status === null ? 'API interne injoignable' : `API interne : HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

/** What the bot may log about an error: its kind and status, never its text. */
export function describe(error) {
  if (error instanceof ApiFailure) return `HTTP ${error.status ?? 'injoignable'}`;
  return error?.name ?? 'erreur';
}

export function createApi({ baseUrl, token, fetchImpl = globalThis.fetch, timeoutMs = TIMEOUT_MS }) {
  async function call(method, path, body) {
    const headers = { authorization: `Bearer ${token}` };
    if (body !== undefined) headers['content-type'] = 'application/json';
    let response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        redirect: 'error',
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch {
      throw new ApiFailure(null, null); // the cause may quote the request: it is dropped
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiFailure(response.status, typeof data?.detail === 'string' ? data.detail : null);
    }
    return data;
  }

  const id = (approvalId) => encodeURIComponent(approvalId);
  return {
    settings: () => call('GET', '/bot/settings'),
    status: () => call('GET', '/status'),
    kill: (reason) => call('POST', '/kill', { reason }),
    pending: () => call('GET', '/approvals/pending'),
    approve: (approvalId, code) => call('POST', `/approvals/${id(approvalId)}/approve`, { code }),
    refuse: (approvalId, reason) =>
      call('POST', `/approvals/${id(approvalId)}/refuse`, { reason }),
    daily: (day) =>
      call('GET', day ? `/reports/daily?day=${encodeURIComponent(day)}` : '/reports/daily'),
    alerts: (after, limit) => call('GET', `/alerts?after=${after}&limit=${limit}`),
    ignored: (kind) => call('POST', '/events/ignored', { kind }),
  };
}
