const config = require('./config');

function timeoutSignal(ms) {
  try { return AbortSignal.timeout(ms); } catch (e) { return undefined; }
}

async function fetchModels(key) {
  const headers = { Accept: 'application/json' };
  if (key) headers.Authorization = `Bearer ${key}`;

  const res = await fetch(`${config.poeBaseUrl}/v1/models`, {
    headers, signal: timeoutSignal(config.httpTimeoutMs)
  });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(`models fetch failed: ${res.status} ${t.slice(0, 200)}`);
  }
  const data = await res.json();
  let list = data.data || [];

  let guard = 0;
  let cursor = data.next_cursor || data.last_id || null;
  while (data.has_more && cursor && guard++ < 10) {
    const q = new URLSearchParams({ after: String(cursor) });
    const r2 = await fetch(`${config.poeBaseUrl}/v1/models?${q}`, {
      headers, signal: timeoutSignal(config.httpTimeoutMs)
    });
    if (!r2.ok) break;
    const d2 = await r2.json();
    const rows = d2.data || [];
    if (!rows.length) break;
    list = list.concat(rows);
    if (!d2.has_more) break;
    cursor = d2.next_cursor || d2.last_id || null;
  }
  return list;
}

async function getBalance(key) {
  const res = await fetch(`${config.poeBaseUrl}/usage/current_balance`, {
    headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' },
    signal: timeoutSignal(config.httpTimeoutMs)
  });
  if (!res.ok) throw new Error('balance fetch failed: ' + res.status);
  const data = await res.json();
  return data.current_point_balance;
}

async function getPointsHistory(key, { limit = 100, startingAfter = null } = {}) {
  const q = new URLSearchParams();
  q.set('limit', String(Math.min(Math.max(parseInt(limit) || 20, 1), 100)));
  if (startingAfter) q.set('starting_after', startingAfter);
  const res = await fetch(`${config.poeBaseUrl}/usage/points_history?${q.toString()}`, {
    headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' },
    signal: timeoutSignal(config.httpTimeoutMs)
  });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    const err = new Error(`points_history failed: ${res.status} ${t.slice(0, 200)}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function chatStream(key, payload, signal) {
  return fetch(`${config.poeBaseUrl}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    },
    body: JSON.stringify(payload),
    signal
  });
}

module.exports = { fetchModels, getBalance, getPointsHistory, chatStream };