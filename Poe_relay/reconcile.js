/**
 * 与 Poe 后台对齐的扣费对账器 v3
 *
 * v3 关键修复：
 *  1) source_kind='chat' 不再硬拒绝，改为“重罚分 + 超时后受限吸收”，
 *     解决 Poe 字段判定不准导致 API 调用永远 unmatched（如 9,202 / 6,174 那两条）
 *  2) 允许 0 积分条目参与匹配（Poe 确实会记 0 分行）
 *  3) 覆盖证明改为“同步水位线 poeSyncFloor + 最后成功抓取时间”，稀疏使用也能证明
 *  4) 判 0 退款前必须确认窗口内没有任何同 bot 的未绑定条目，杜绝把真实消费退掉
 *  5) 判 0 结算后 24h 内仍可被迟到条目二次结算
 *  6) unmatched 自动回炉重试（上限 maxSettleTries 次）
 *  7) 翻页加“未向更早推进 / 游标重复”熔断
 */
const config = require('./config');
const db = require('./db');
const poe = require('./poe');
const pricing = require('./pricing');
const keyManager = require('./keyManager');

const SYNC_FLOOR_KEY = 'poeSyncFloor';

let running = false;
let failCount = 0;
let disabled = false;
let lastRun = 0;
let lastError = '';
let lastFetched = Number(db.getSetting('poeLastFetched', 0)) || 0;
let lastInserted = 0;

const r2 = x => Math.round(x * 100) / 100;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const norm = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');

function botMatch(botName, model) {
    const a = norm(botName), b = norm(model);
    if (!a || !b) return false;
    return a === b || a.startsWith(b) || b.startsWith(a);
}

/* 时间单位自适应：微秒 / 毫秒 / 秒 都能吃 */
function toMs(v) {
    const n = Number(v) || 0;
    if (!n) return 0;
    if (n > 1e15) return Math.floor(n / 1000);
    if (n > 1e12) return Math.floor(n);
    if (n > 1e9) return Math.floor(n * 1000);
    return Math.floor(n);
}

/* 判断这条 Poe 用量记录来自 API 还是网页端聊天（尽量鲁棒） */
function classify(row) {
    const t = String((row && (row.usage_type ?? row.source ?? row.origin ?? row.type ?? row.category)) || '').toLowerCase();
    if (/api/.test(t)) return 'api';
    if (/chat|conversation|bot_?message|subscription|web|app/.test(t)) return 'chat';
    if (row && (row.chat_id != null || row.conversation_id != null || row.chat_code || row.chat_title)) return 'chat';
    let s = '';
    try { s = JSON.stringify(row || {}).toLowerCase(); } catch (e) { }
    if (/"api[_a-z]*"\s*:/.test(s) || /api[_-]?key/.test(s)) return 'api';
    return 'unknown';
}

/* ---------------- 拉取历史 ---------------- */
async function fetchPage(key, params) {
    const R = config.reconcile;
    let err;
    for (let i = 0; i < (R.retryPerPage || 3); i++) {
        try { return await poe.getPointsHistory(key, params); }
        catch (e) {
            err = e;
            if (e.status && e.status >= 400 && e.status < 500 && e.status !== 429) break;
            await sleep((R.retryBaseMs || 4000) * (i + 1));
        }
    }
    throw err;
}

async function fetchHistory(deep = false) {
    const R = config.reconcile;
    const now = Date.now();
    const floorTs = now - (R.backfillDays || 7) * 86400000;

    const oldest = db.prepare(
        `SELECT MIN(COALESCE(started_at,created_at)) t FROM usage_log WHERE status IN ('pending','unmatched')`
    ).get().t;

    const needFrom = deep ? floorTs
        : Math.max(floorTs, (oldest || now) - R.matchWindowBeforeMs - 120000);

    const exists = db.prepare('SELECT 1 FROM poe_usage WHERE query_id=?');
    const ins = db.prepare(`INSERT INTO poe_usage
      (query_id,key_id,bot_name,usage_type,source_kind,cost_points,creation_time,fetched_at,raw)
      VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(query_id) DO UPDATE SET
        cost_points=excluded.cost_points,
        source_kind=excluded.source_kind,
        usage_type=excluded.usage_type,
        raw=excluded.raw`);

    let inserted = 0;
    let okAny = false;
    const perKeyFloor = [];

    for (const k of keyManager.keys) {
        if (!k || !k.key) continue;
        let cursor = null, minSeen = Infinity, prevMin = Infinity, hitEnd = false;
        const seenCursor = new Set();

        for (let page = 0; page < (R.maxPages || 40); page++) {
            let res;
            try {
                res = await fetchPage(k.key, { limit: R.fetchLimit, startingAfter: cursor });
                failCount = 0; lastError = ''; okAny = true;
            } catch (e) {
                failCount++;
                lastError = (e && e.message) || String(e);
                console.error('[reconcile] 拉取用量历史失败', k.id, lastError);
                if (failCount >= (R.maxFailBeforePause || 20)) {
                    disabled = true;
                    console.error('[reconcile] 连续失败过多，已暂停（管理后台点“深度对账”恢复）');
                }
                break;
            }

            const rows = res.data || [];
            if (!rows.length) { hitEnd = true; break; }

            let minT = Infinity;
            db.transaction(list => {
                for (const r of list) {
                    const qid = String(r.query_id || r.id || '');
                    if (!qid) continue;
                    const t = toMs(r.creation_time);
                    if (t && t < minT) minT = t;
                    const isNew = !exists.get(qid);
                    ins.run(
                        qid, k.id, r.bot_name || r.model || '', String(r.usage_type || r.source || ''),
                        classify(r), Math.round(Number(r.cost_points) || 0),
                        t, Date.now(), JSON.stringify(r)
                    );
                    if (isNew) inserted++;
                }
            })(rows);

            if (minT < minSeen) minSeen = minT;

            const last = rows[rows.length - 1];
            const nc = last.query_id || last.id;
            if (!nc || seenCursor.has(nc)) { hitEnd = !nc; break; }
            seenCursor.add(nc);
            cursor = nc;

            if (res.has_more === false) { hitEnd = true; break; }
            if (minSeen >= prevMin) break;            // 没有向更早推进 -> 熔断
            prevMin = minSeen;
            if (minSeen <= needFrom) break;           // 已覆盖到需要的时间段
        }
        perKeyFloor.push(hitEnd ? 0 : (minSeen === Infinity ? now : minSeen));
    }

    if (okAny) {
        const runFloor = perKeyFloor.length ? Math.max(...perKeyFloor) : now;
        const prev = db.getSetting(SYNC_FLOOR_KEY, null);
        db.setSetting(SYNC_FLOOR_KEY, prev == null ? runFloor : Math.min(Number(prev), runFloor));
        lastFetched = Date.now();
        db.setSetting('poeLastFetched', lastFetched);
    }
    lastInserted = inserted;
    return inserted;
}

/* ---------------- 匹配打分 ---------------- */
function pairScore(log, row, opts = {}) {
    const loose = !!opts.loose;
    const R = config.reconcile;
    if (!row || !log) return null;
    if (row.log_id) return null;
    const kind = row.source_kind || 'unknown';
    if (kind === 'chat' && !loose) return null;
    if (log.key_id && row.key_id && log.key_id !== row.key_id) return null;
    if (!botMatch(row.bot_name, log.model)) return null;

    const mul = loose ? 3 : 1;
    const start = (log.started_at || log.created_at) - R.matchWindowBeforeMs * mul;
    const end = (log.finished_at || log.created_at) + R.matchWindowAfterMs * mul;
    if (row.creation_time < start || row.creation_time > end) return null;

    const ref = log.finished_at || log.created_at;
    let s = Math.abs(row.creation_time - ref) / 1000;
    if (kind !== 'api') s += 20;
    if (kind === 'chat') s += 150;
    if (log.status === 'settled') s += 60;

    const pred = log.pred_points || 0;
    if (pred > 0) {
        if (row.cost_points > 0) s += Math.min(120, Math.abs(Math.log(row.cost_points / pred)) * 30);
        else s += 100;
    }
    return s;
}

/* ---------------- 结算 ---------------- */
function applySettle(log, rows, addPoints, note) {
    const isLate = log.status === 'settled';
    const realPoints = Math.max(0, Math.round((isLate ? (log.real_points || 0) : 0) + (addPoints || 0)));
    const realCredits = realPoints > 0 ? pricing.pointsToCredits(realPoints) : 0;
    const diff = r2(realCredits - (log.charged_credits || 0));

    const oldIds = (isLate && log.query_ids) ? log.query_ids.split(',').filter(Boolean) : [];
    const ids = oldIds.concat((rows || []).map(r => r.query_id)).filter((v, i, a) => a.indexOf(v) === i);

    db.transaction(() => {
        if (diff !== 0) db.prepare('UPDATE users SET credits = credits - ? WHERE id=?').run(diff, log.user_id);
        db.prepare(`UPDATE usage_log SET real_points=?, cost_credits=?, charged_credits=?,
                status='settled', settled_at=?, query_ids=?, settle_note=? WHERE id=?`)
            .run(realPoints, realCredits, realCredits, Date.now(), ids.join(','), note || null, log.id);
        const up = db.prepare('UPDATE poe_usage SET log_id=?, matched_at=? WHERE query_id=?');
        for (const r of (rows || [])) up.run(log.id, Date.now(), r.query_id);
    })();

    learn(log, realPoints);
    return { realPoints, realCredits, diff };
}

/**
 * 学习：
 * - 无链接 → 校准模型费率系数
 * - 有链接 → 残差（扣掉已知费率校准后）归因给“链接抓取成本”
 */
function learn(log, realPoints) {
    const pred = log.pred_points || 0;
    if (pred <= 0 || realPoints <= 0) return;
    const urls = Number(log.url_count) || 0;
    if (urls > 0) {
        const predAdj = pred * pricing.calibFactor(log.model);
        const extra = realPoints - predAdj;
        if (extra > 0) pricing.updateUrlCalibration(log.model, urls, extra);
        else pricing.updateCalibration(log.model, pred, realPoints);
    } else {
        pricing.updateCalibration(log.model, pred, realPoints);
    }
}

function targetLogs() {
    const R = config.reconcile;
    const now = Date.now();
    const pend = db.prepare(`SELECT * FROM usage_log WHERE status='pending'`).all();
    const late = db.prepare(
        `SELECT * FROM usage_log WHERE status='settled'
          AND (settled_at > ? OR (COALESCE(real_points,0)<=0 AND settled_at > ?))`
    ).all(now - R.lateWindowMs, now - (R.zeroLateWindowMs || R.lateWindowMs));
    return pend.concat(late);
}

function matchAndSettle() {
    const R = config.reconcile;
    const now = Date.now();
    const logs = targetLogs();
    if (!logs.length) return 0;

    const minT = Math.min(...logs.map(l => (l.started_at || l.created_at))) - R.matchWindowBeforeMs;
    const rows = db.prepare(
        `SELECT * FROM poe_usage WHERE log_id IS NULL AND creation_time>=? AND creation_time<=?`
    ).all(minT, now + 60000);
    if (!rows.length) return 0;

    const pairs = [];
    for (const row of rows) {
        for (const log of logs) {
            const s = pairScore(log, row);
            if (s != null) pairs.push({ row, log, s });
        }
    }
    if (!pairs.length) return 0;
    pairs.sort((a, b) => a.s - b.s);

    const takenRow = new Set();
    const groups = new Map();
    for (const p of pairs) {
        if (takenRow.has(p.row.query_id)) continue;
        takenRow.add(p.row.query_id);
        if (!groups.has(p.log.id)) groups.set(p.log.id, { rows: [], points: 0 });
        const g = groups.get(p.log.id);
        g.rows.push(p.row);
        g.points += p.row.cost_points || 0;
    }

    let settled = 0;
    for (const [logId, g] of groups) {
        const log = db.prepare('SELECT * FROM usage_log WHERE id=?').get(logId);
        if (!log) continue;
        const isLate = log.status === 'settled';
        const age = now - (log.finished_at || log.created_at);

        if (!isLate) {
            if (age < R.settleQuietMs) continue;                        // 等分条到齐
            const pred = log.pred_points || 0;
            const guard = g.points <= pred * (R.zeroCostGuardRatio || 0)
                && pred >= (R.zeroCostGuardMinPred || 0);
            if (guard) {
                const explicitApiZero = g.rows.some(r => r.source_kind === 'api');
                if (!explicitApiZero && age < R.pendingTimeoutMs) continue;
            }
        } else if (!g.points) continue;                                 // 迟到吸收只吃有金额的

        applySettle(log, g.rows, g.points, isLate ? 'late-absorb' : 'auto');
        settled++;
    }
    return settled;
}

/* ---------------- 历史覆盖证明（v3：同步水位线） ---------------- */
function historyCovers(log) {
    const R = config.reconcile;
    const t = log.finished_at || log.created_at;
    const fl = db.getSetting(SYNC_FLOOR_KEY, null);
    const spanOk = fl != null && (Number(fl) === 0 || Number(fl) <= t - 60000);
    if (spanOk && lastFetched > t + R.matchWindowAfterMs) return true;

    // 兜底：本地已存在早于 t 和晚于 t 的条目
    const before = db.prepare('SELECT COUNT(*) c FROM poe_usage WHERE creation_time<? AND creation_time>?')
        .get(t, t - R.coverageWindowMs).c;
    const after = db.prepare('SELECT COUNT(*) c FROM poe_usage WHERE creation_time>? AND creation_time<?')
        .get(t, t + R.coverageWindowMs).c;
    return before > 0 && after > 0;
}

/* ---------------- 超时处理：宽松匹配 → 判0 → unmatched ---------------- */
function resolveTimeout() {
    const R = config.reconcile;
    const now = Date.now();
    const old = db.prepare(
        `SELECT * FROM usage_log WHERE status='pending' AND COALESCE(finished_at,created_at) < ?`
    ).all(now - R.pendingTimeoutMs);
    let n = 0;

    for (const log of old) {
        const from = (log.started_at || log.created_at) - R.matchWindowBeforeMs * 3;
        const to = (log.finished_at || log.created_at) + R.matchWindowAfterMs * 3;
        const cand = db.prepare(
            `SELECT * FROM poe_usage WHERE log_id IS NULL AND creation_time BETWEEN ? AND ?`
        ).all(from, to);

        const botCand = cand.filter(c => botMatch(c.bot_name, log.model));
        const scored = [];
        for (const c of botCand) {
            const s = pairScore(log, c, { loose: true });
            if (s == null) continue;
            if (c.source_kind === 'chat') {
                if (!R.looseAllowChatKind) continue;
                const dt = Math.abs(c.creation_time - (log.finished_at || log.created_at));
                if (dt > (R.looseChatMaxDeltaMs || 180000)) continue;
                const pred = log.pred_points || 0;
                if (pred > 0 && c.cost_points > 0) {
                    const rr = c.cost_points / pred;
                    if (rr < (R.looseChatMinRatio || 0.25) || rr > (R.looseChatMaxRatio || 5)) continue;
                }
            }
            scored.push({ c, s });
        }
        scored.sort((a, b) => a.s - b.s);
        const best = scored[0];

        if (best && best.c.cost_points > 0) {
            applySettle(log, [best.c], best.c.cost_points,
                best.c.source_kind === 'chat' ? 'loose-match-chatkind' : 'loose-match');
            n++; continue;
        }
        if (best && best.c.cost_points === 0 && best.c.source_kind !== 'chat') {
            applySettle(log, [best.c], 0, 'zero-row');
            n++; continue;
        }

        const covered = historyCovers(log);
        if (!botCand.length && covered && R.autoZeroWhenCovered) {
            applySettle(log, [], 0, 'zero-by-coverage');
            n++; continue;
        }
        const note = botCand.length ? 'candidate-rejected'
            : (covered ? 'no-match-but-covered' : 'history-not-synced');
        db.prepare(`UPDATE usage_log SET status='unmatched', settle_note=? WHERE id=?`).run(note, log.id);
    }
    return n;
}

/* unmatched 自动回炉 */
function reopenUnmatched() {
    const R = config.reconcile;
    const cutoff = Date.now() - (R.reopenUnmatchedDays || 3) * 86400000;
    const info = db.prepare(
        `UPDATE usage_log SET status='pending', settle_note='reopen',
            settle_tries=COALESCE(settle_tries,0)+1
         WHERE status='unmatched' AND created_at>=? AND COALESCE(settle_tries,0) < ?`
    ).run(cutoff, R.maxSettleTries || 5);
    return info.changes;
}

/* ---------------- 对外操作 ---------------- */
async function runOnce(force = false, deep = false) {
    if (!config.reconcile.enabled) return { skipped: 'disabled-by-config' };
    if (disabled && !force) return { skipped: 'auto-disabled', lastError };
    if (force) { disabled = false; failCount = 0; }
    if (running) return { skipped: 'busy' };
    running = true;
    try {
        const ins = await fetchHistory(deep || force);
        let reopened = 0;
        if (ins > 0 || deep || force) reopened = reopenUnmatched();
        const n1 = matchAndSettle();
        const m = resolveTimeout();
        const n2 = matchAndSettle();
        lastRun = Date.now();
        return { fetched: ins, reopened, settled: n1 + n2 + m, lastRun, disabled, lastError };
    } finally { running = false; }
}

function status() {
    const g = s => db.prepare(`SELECT COUNT(*) c FROM usage_log WHERE status=?`).get(s).c;
    const fl = db.getSetting(SYNC_FLOOR_KEY, null);
    return {
        pending: g('pending'), unmatched: g('unmatched'), settled: g('settled'),
        poeRows: db.prepare('SELECT COUNT(*) c FROM poe_usage').get().c,
        syncFloor: fl == null ? null : Number(fl),
        lastRun, lastFetched, lastInserted, disabled, lastError
    };
}

function problemList(limit = 40) {
    const R = config.reconcile;
    const logs = db.prepare(
        `SELECT id,user_id,model,kind,pred_points,charged_credits,base_credits,est_credits,url_count,
            status,settle_note,settle_tries,started_at,finished_at,created_at,key_id
     FROM usage_log WHERE status IN ('pending','unmatched') ORDER BY id DESC LIMIT ?`
    ).all(limit);
    return logs.map(l => {
        const from = (l.started_at || l.created_at) - R.matchWindowBeforeMs * 3;
        const to = (l.finished_at || l.created_at) + R.matchWindowAfterMs * 3;
        const candidates = db.prepare(
            `SELECT query_id,bot_name,usage_type,source_kind,cost_points,creation_time,log_id
       FROM poe_usage WHERE creation_time BETWEEN ? AND ? ORDER BY creation_time LIMIT 12`
        ).all(from, to);
        return { ...l, covered: historyCovers(l), candidates };
    });
}

function manualBind(logId, queryIdsStr) {
    const ids = String(queryIdsStr || '').split(/[\s,，]+/).filter(Boolean);
    if (!ids.length) throw new Error('请填写 query_id');
    const log = db.prepare('SELECT * FROM usage_log WHERE id=?').get(logId);
    if (!log) throw new Error('记录不存在');
    const get = db.prepare('SELECT * FROM poe_usage WHERE query_id=?');
    const rows = ids.map(q => get.get(q)).filter(Boolean);
    if (!rows.length) throw new Error('这些 query_id 不在本地库中，请先“深度对账”把历史拉全');
    const pts = rows.reduce((s, r) => s + (r.cost_points || 0), 0);
    const logNow = { ...log, status: log.status === 'settled' ? 'settled' : 'pending' };
    return applySettle(logNow, rows, pts, 'manual-bind');
}

function manualSettlePoints(logId, points) {
    const log = db.prepare('SELECT * FROM usage_log WHERE id=?').get(logId);
    if (!log) throw new Error('记录不存在');
    const p = Math.max(0, Math.round(Number(points) || 0));
    const cur = { ...log, status: 'pending', real_points: 0, query_ids: log.query_ids };
    return applySettle(cur, [], p, p === 0 ? 'manual-zero' : 'manual-points');
}

function retryUnmatched() {
    const info = db.prepare(
        `UPDATE usage_log SET status='pending', settle_note='retry', settle_tries=0 WHERE status='unmatched'`
    ).run();
    return info.changes;
}

function resetRange(hours) {
    const cutoff = Date.now() - (Number(hours) || 24) * 3600000;
    const logs = db.prepare(`SELECT * FROM usage_log WHERE created_at>=?`).all(cutoff);
    db.transaction(() => {
        for (const l of logs) {
            const base = (l.base_credits != null) ? l.base_credits : (l.charged_credits || 0);
            const diff = r2(base - (l.charged_credits || 0));
            if (diff !== 0) db.prepare('UPDATE users SET credits = credits - ? WHERE id=?').run(diff, l.user_id);
            db.prepare(`UPDATE usage_log SET charged_credits=?, cost_credits=?, real_points=NULL,
                  status='pending', settled_at=NULL, query_ids=NULL, settle_note='reset', settle_tries=0 WHERE id=?`)
                .run(base, base, l.id);
            db.prepare('UPDATE poe_usage SET log_id=NULL, matched_at=NULL WHERE log_id=?').run(l.id);
        }
    })();
    return logs.length;
}

function scheduleAfterChat() {
    setTimeout(() => runOnce().catch(() => { }), config.reconcile.afterChatDelayMs);
    setTimeout(() => runOnce().catch(() => { }), config.reconcile.afterChatDelayMs + 90 * 1000);
    setTimeout(() => runOnce().catch(() => { }), config.reconcile.afterChatDelayMs + 5 * 60 * 1000);
}

module.exports = {
    runOnce, status, scheduleAfterChat,
    problemList, manualBind, manualSettlePoints, retryUnmatched, resetRange
};