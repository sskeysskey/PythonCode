const express = require('express');
const jwt = require('jsonwebtoken');
const crypto = require('crypto');
const path = require('path');

const config = require('./config');
const db = require('./db');
const poe = require('./poe');
const pricing = require('./pricing');
const keyManager = require('./keyManager');
const reconcile = require('./reconcile');

const app = express();
app.use(express.json({ limit: '40mb' }));

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Authorization, Content-Type');
  res.header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});
app.use(express.static(path.join(__dirname, 'public')));

/* ---------------- 工具 ---------------- */
const r2 = x => Math.round(x * 100) / 100;
function hashPass(pw) {
  const salt = crypto.randomBytes(16).toString('hex');
  return `${salt}:${crypto.scryptSync(pw, salt, 64).toString('hex')}`;
}
function verifyPass(pw, stored) {
  const [salt, h] = String(stored).split(':');
  const hh = crypto.scryptSync(pw, salt, 64).toString('hex');
  try { return crypto.timingSafeEqual(Buffer.from(h), Buffer.from(hh)); } catch { return false; }
}
function getUser(id) { return db.prepare('SELECT * FROM users WHERE id=?').get(id); }
function auth(req, res, next) {
  const h = req.headers.authorization || '';
  const token = h.startsWith('Bearer ') ? h.slice(7) : null;
  if (!token) return res.status(401).json({ error: '未登录' });
  try { req.userId = jwt.verify(token, config.jwtSecret).uid; next(); }
  catch { return res.status(401).json({ error: '登录已失效' }); }
}
function adminAuth(req, res, next) {
  const h = req.headers.authorization || '';
  const token = h.startsWith('Bearer ') ? h.slice(7) : null;
  if (!token) return res.status(401).json({ error: '未登录' });
  try {
    const p = jwt.verify(token, config.jwtSecret);
    if (!p.admin) return res.status(403).json({ error: '非管理员' });
    next();
  } catch { return res.status(401).json({ error: '登录已失效' }); }
}
function featuredList() {
  const s = db.getSetting('featuredModels', null);
  return Array.isArray(s) && s.length ? s : config.featuredModels;
}
function customList() {
  const s = db.getSetting('customModels', null);
  return Array.isArray(s) ? s : [];
}

/* 多模态消息规整 + 体积/数量校验 */
function normalizeMessages(messages) {
  const maxBytes = (config.image.maxUploadMB || 6) * 1024 * 1024;
  const maxPerMsg = config.image.maxImagesPerMessage || 4;
  const out = [];
  let images = 0;
  for (const m of messages || []) {
    if (!m || !m.role) continue;
    if (typeof m.content === 'string') { out.push({ role: m.role, content: m.content }); continue; }
    if (!Array.isArray(m.content)) continue;
    const parts = [];
    let n = 0;
    for (const p of m.content) {
      if (!p) continue;
      if (p.type === 'text' && typeof p.text === 'string') { parts.push({ type: 'text', text: p.text }); continue; }
      const url = p.image_url && typeof p.image_url === 'object' ? p.image_url.url : p.image_url;
      if (p.type === 'image_url' && typeof url === 'string') {
        if (url.startsWith('data:image/')) {
          const b64 = url.slice(url.indexOf(',') + 1);
          if (Math.ceil(b64.length * 3 / 4) > maxBytes) { const e = new Error('图片过大，请压缩后重试'); e.code = 400; throw e; }
        } else if (!/^https?:\/\//i.test(url)) continue;
        n++; images++;
        if (n > maxPerMsg) { const e = new Error('单条消息最多 ' + maxPerMsg + ' 张图片'); e.code = 400; throw e; }
        parts.push({ type: 'image_url', image_url: { url } });
      }
    }
    out.push({ role: m.role, content: parts.length ? parts : '' });
  }
  return { messages: out, images };
}

/* =========================================================
 * <think> 标签流式分离器
 * ========================================================= */
const THINK_OPEN = /<(think|thinking|reasoning)>/i;
const THINK_CLOSE = /<\/(think|thinking|reasoning)>/i;
function tailPartial(s) {
  const i = s.lastIndexOf('<');
  if (i < 0) return 0;
  const t = s.slice(i);
  if (t.length > 12) return 0;
  return /^<\/?[a-z]*$/i.test(t) ? t.length : 0;
}
function makeThinkSplitter() {
  let inThink = false, buf = '';
  return {
    feed(chunk, onText, onReason) {
      buf += chunk;
      while (buf) {
        if (!inThink) {
          const m = buf.match(THINK_OPEN);
          if (!m) {
            const keep = tailPartial(buf);
            const emit = keep ? buf.slice(0, buf.length - keep) : buf;
            buf = keep ? buf.slice(buf.length - keep) : '';
            if (emit) onText(emit);
            return;
          }
          if (m.index > 0) onText(buf.slice(0, m.index));
          buf = buf.slice(m.index + m[0].length);
          inThink = true;
        } else {
          const m = buf.match(THINK_CLOSE);
          if (!m) {
            const keep = tailPartial(buf);
            const emit = keep ? buf.slice(0, buf.length - keep) : buf;
            buf = keep ? buf.slice(buf.length - keep) : '';
            if (emit) onReason(emit);
            return;
          }
          if (m.index > 0) onReason(buf.slice(0, m.index));
          buf = buf.slice(m.index + m[0].length);
          inThink = false;
        }
      }
    },
    flush(onText, onReason) {
      if (!buf) return;
      (inThink ? onReason : onText)(buf);
      buf = '';
    }
  };
}

let modelsLoadedAt = 0, modelsCount = 0, modelsError = '';
async function refreshModels() {
  const k = keyManager.keys[0];
  const models = await poe.fetchModels(k && k.key);
  pricing.setModels(models);
  modelsLoadedAt = Date.now();
  modelsCount = models.length;
  modelsError = '';
  return models.length;
}

/* ---------------- 注册/登录 ---------------- */
app.post('/api/register', (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) return res.status(400).json({ error: '用户名和密码必填' });
  if (username.length < 3 || password.length < 6) return res.status(400).json({ error: '用户名≥3位，密码≥6位' });
  if (db.prepare('SELECT id FROM users WHERE username=?').get(username)) return res.status(400).json({ error: '用户名已存在' });
  const info = db.prepare('INSERT INTO users (username, pass_hash, credits, created_at) VALUES (?,?,?,?)')
    .run(username, hashPass(password), 0, Date.now());
  res.json({ token: jwt.sign({ uid: info.lastInsertRowid }, config.jwtSecret, { expiresIn: '30d' }) });
});
app.post('/api/login', (req, res) => {
  const { username, password } = req.body || {};
  const u = db.prepare('SELECT * FROM users WHERE username=?').get(username || '');
  if (!u || !verifyPass(password || '', u.pass_hash)) return res.status(401).json({ error: '用户名或密码错误' });
  res.json({ token: jwt.sign({ uid: u.id }, config.jwtSecret, { expiresIn: '30d' }) });
});
app.get('/api/me', auth, (req, res) => {
  const u = getUser(req.userId);
  res.json({
    username: u.username, credits: r2(u.credits),
    lowBalance: u.credits < config.lowBalanceCreditsWarn,
    markup: config.sellMarkup, showUpstream: config.showUpstreamDetail,
    safetyRatio: config.balanceSafetyRatio
  });
});

/* ---------------- 模型列表 ---------------- */
function modelBrief(m) {
  const r = pricing.getRates(m.id);
  const k = pricing.calibFactor(m.id);
  const img = pricing.isImageModel(m.id);
  return {
    id: m.id,
    owned_by: m.owned_by || '',
    kind: img ? 'image' : 'text',
    vision: pricing.isVisionModel(m.id),
    perImage: img ? r2(pricing.pointsPerImage(m.id) * k * config.sellMarkup) : null,
    poePerImage: img ? r2(pricing.pointsPerImage(m.id)) : null,
    inPer1k: r2(r.inPer1k * k * config.sellMarkup),
    outPer1k: r2(r.outPer1k * k * config.sellMarkup),
    poeInPer1k: r2(r.inPer1k),
    poeOutPer1k: r2(r.outPer1k),
    urlPerLink: img ? 0 : r2(pricing.urlExtraPointsPerUrl(m.id) * config.sellMarkup),
    src: r.source,
    custom: !!m.custom,
    output: m.output || ['text']
  };
}
function unknownBrief(id) {
  const img = pricing.isImageModel(id);
  return {
    id, owned_by: '', kind: img ? 'image' : 'text', vision: true,
    perImage: img ? r2(pricing.pointsPerImage(id) * config.sellMarkup) : null,
    inPer1k: null, outPer1k: null,
    poeInPer1k: null, poeOutPer1k: null, src: 'unknown',
    unknown: true, output: img ? ['image'] : ['text']
  };
}
app.get('/api/models', auth, (req, res) => {
  const all = pricing.allModels().map(modelBrief).sort((a, b) => a.id.localeCompare(b.id));
  const featured = featuredList().map(n => {
    const m = pricing.getModel(n);
    return m ? modelBrief(m) : unknownBrief(n);
  });
  res.json({
    featured, all, markup: config.sellMarkup,
    showUpstream: config.showUpstreamDetail,
    allowCustomModel: true,
    safetyRatio: config.balanceSafetyRatio,
    image: {
      enabled: !!config.image.enabled,
      maxImages: config.image.maxImagesPerMessage,
      maxUploadMB: config.image.maxUploadMB
    },
    modelsCount: all.length
  });
});
app.get('/api/models/search', auth, (req, res) => {
  const q = String(req.query.q || '').toLowerCase().split(/\s+/).filter(Boolean);
  const out = pricing.allModels()
    .filter(m => { const s = (m.id + ' ' + (m.owned_by || '')).toLowerCase(); return q.every(k => s.includes(k)); })
    .slice(0, 200).map(modelBrief);
  res.json(out);
});

/* ---------------- 图片代理 ---------------- */
const IMG_HOST_OK = [/(^|\.)poecdn\.net$/i, /(^|\.)poe\.com$/i, /(^|\.)quoracdn\.net$/i];
app.get('/api/imgproxy', async (req, res) => {
  try {
    const u = new URL(String(req.query.u || ''));
    if (u.protocol !== 'https:' || !IMG_HOST_OK.some(rx => rx.test(u.hostname)))
      return res.status(400).end('bad host');
    const r = await fetch(u.toString(), { headers: { 'User-Agent': 'Mozilla/5.0' } });
    if (!r.ok) return res.status(r.status).end();
    res.setHeader('Content-Type', r.headers.get('content-type') || 'image/png');
    res.setHeader('Cache-Control', 'public, max-age=604800');
    res.end(Buffer.from(await r.arrayBuffer()));
  } catch (e) { res.status(500).end(); }
});

/* ---------------- 消耗预估 ---------------- */
app.post('/api/estimate', auth, (req, res) => {
  const { model, messages } = req.body || {};
  if (!model || !messages) return res.status(400).json({ error: '参数缺失' });
  let norm;
  try { norm = normalizeMessages(messages); }
  catch (e) { return res.status(400).json({ error: e.message }); }

  const est = pricing.estimate(model, norm.messages);
  const u = getUser(req.userId);
  const required = pricing.requiredCredits(est.credits);
  res.json({
    kind: est.kind,
    credits: est.credits, highCredits: est.highCredits,
    poePoints: est.points, poeHighPoints: est.highPoints,
    perImagePoints: est.perImagePoints || null,
    promptTokens: est.promptTokens, inputImages: est.inputImages,
    outputTokens: est.outputTokens, outputTokensHigh: est.outputTokensHigh,
    urlCount: est.urlCount || 0, urlUnique: est.urlUnique || 0,
    urlTokens: est.urlTokens || 0, urlPoints: est.urlPoints || 0,
    samples: est.samples, predictSource: est.predictSource,
    rateSource: est.rateSource, knownModel: est.knownModel, calib: est.calib,
    markup: config.sellMarkup, showUpstream: config.showUpstreamDetail,
    balance: r2(u.credits),
    safetyRatio: config.balanceSafetyRatio,
    required,
    shortfall: r2(Math.max(0, required - u.credits)),
    enough: u.credits >= required
  });
});

/* ---------------- 会话 ---------------- */
app.post('/api/conversations', auth, (req, res) => {
  const { title, model } = req.body || {};
  const info = db.prepare('INSERT INTO conversations (user_id,title,model,created_at) VALUES (?,?,?,?)')
    .run(req.userId, title || '新对话', model || '', Date.now());
  res.json({ id: info.lastInsertRowid });
});
app.get('/api/conversations', auth, (req, res) => {
  res.json(db.prepare('SELECT id,title,model,created_at FROM conversations WHERE user_id=? ORDER BY id DESC').all(req.userId));
});
app.get('/api/conversations/:id/messages', auth, (req, res) => {
  const conv = db.prepare('SELECT * FROM conversations WHERE id=? AND user_id=?').get(req.params.id, req.userId);
  if (!conv) return res.status(404).json({ error: '会话不存在' });
  const rows = db.prepare(
    'SELECT role,content,is_json,reasoning,think_ms,created_at FROM messages WHERE conversation_id=? ORDER BY id'
  ).all(req.params.id);
  res.json(rows.map(r => {
    let content = r.content;
    if (r.is_json) { try { content = JSON.parse(r.content); } catch { } }
    return { role: r.role, content, reasoning: r.reasoning || '', thinkMs: r.think_ms || 0, created_at: r.created_at };
  }));
});
app.delete('/api/conversations/:id', auth, (req, res) => {
  const conv = db.prepare('SELECT id FROM conversations WHERE id=? AND user_id=?').get(req.params.id, req.userId);
  if (!conv) return res.status(404).json({ error: '会话不存在' });
  db.prepare('DELETE FROM conversations WHERE id=?').run(conv.id);
  db.prepare('DELETE FROM messages WHERE conversation_id=?').run(conv.id);
  res.json({ ok: true });
});

/* ---------------- 用户用量明细 ---------------- */
app.get('/api/usage', auth, (req, res) => {
  res.json(db.prepare(`SELECT id,model,kind,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens,
    in_images,out_images,url_count,est_credits,charged_credits,real_points,status,created_at
    FROM usage_log WHERE user_id=? ORDER BY id DESC LIMIT 40`).all(req.userId));
});

/* ---------------- 核心：聊天（SSE 流式）---------------- */
app.post('/api/chat', auth, async (req, res) => {
  const { model, messages, conversationId } = req.body || {};
  const user = getUser(req.userId);
  if (!model || !messages || !messages.length) return res.status(400).json({ error: '参数缺失' });

  let norm;
  try { norm = normalizeMessages(messages); }
  catch (e) { return res.status(400).json({ error: e.message }); }
  const msgs = norm.messages;
  const isImageModel = pricing.isImageModel(model);

  const urlInfo = isImageModel ? { weighted: 0, total: 0, unique: 0 } : pricing.analyzeUrls(msgs);
  const est = pricing.estimate(model, msgs);
  const required = pricing.requiredCredits(est.credits);

  if (user.credits < required) {
    return res.status(402).json({
      error: 'insufficient_credits',
      message: `余额不足：本次预估 ${est.credits} 点，为避免中途中断，需至少保留 ${required} 点（${config.balanceSafetyRatio}× 安全额度），当前 ${r2(user.credits)} 点。`,
      need: est.credits, required, ratio: config.balanceSafetyRatio, have: r2(user.credits)
    });
  }

  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  if (res.flushHeaders) res.flushHeaders();
  const send = obj => { try { if (!res.writableEnded) res.write(`data: ${JSON.stringify(obj)}\n\n`); } catch { } };

  const payload = { model, messages: msgs, stream: true, stream_options: { include_usage: true } };

  /* ===== 【修复】客户端断开检测 =====
   * 注意：Node16+ 的 req 'close' 在“请求体读完”时就会触发（express.json 已经读完了），
   * 用它会导致刚发起上游请求就被 abort，表现为“上游服务异常”。必须用 res 'close'。 */
  const ac = new AbortController();
  let clientGone = false, finishedFlag = false, connTimedOut = false;
  res.on('close', () => {
    if (finishedFlag || res.writableEnded) return;
    clientGone = true;
    try { ac.abort(); } catch { }
  });

  /* ===== 连接上游（只对“连接阶段”做超时，拿到响应头后立刻清除） ===== */
  let poeRes = null, usedKey = null, connErr = null;
  const tryKeys = Math.max(1, keyManager.keys.length);
  for (let i = 0; i < tryKeys; i++) {
    usedKey = keyManager.pick();
    if (!usedKey) {
      send({ type: 'error', error: '暂无可用通道，请联系管理员（所有 Key 均不可用或余额不足）' });
      return res.end();
    }
    const timer = setTimeout(() => { connTimedOut = true; try { ac.abort(); } catch { } }, 60000);
    try {
      poeRes = await poe.chatStream(usedKey.key, payload, ac.signal);
      clearTimeout(timer);
    } catch (e) {
      clearTimeout(timer);
      poeRes = null;
      if (clientGone) return res.end();                       // 用户自己取消了
      connErr = e;
      console.error('[chat] 连接上游失败', usedKey.id, e && e.message);
      if (connTimedOut) break;                                // 超时就不再重试了
      continue;                                               // 网络抖动 -> 换下一把 key，但不拉黑
    }
    // 只有明确的鉴权/欠费/封禁才拉黑这把 key
    if (poeRes.status === 401 || poeRes.status === 402 || poeRes.status === 403) {
      keyManager.markBad(usedKey.id);
      poeRes = null;
      continue;
    }
    break;
  }

  if (!poeRes || !poeRes.ok) {
    let msg;
    if (!poeRes) {
      msg = connTimedOut
        ? '连接上游超时（60秒无响应），请稍后重试'
        : ('连接上游失败：' + ((connErr && connErr.message) || '未知网络错误'));
    } else {
      let body = '';
      try { body = await poeRes.text(); } catch { }
      let detail = '';
      try { const j = JSON.parse(body); detail = (j.error && (j.error.message || j.error)) || j.message || ''; } catch { }
      if (!detail) detail = body ? body.slice(0, 300) : '';
      msg = `上游 ${poeRes.status}${detail ? '：' + detail : ''}`;
      if (poeRes.status === 400 || poeRes.status === 404) {
        msg += `（模型 "${model}" 可能不支持 API 调用，或不支持图片输入，请确认名称/能力）`;
      }
      console.error('[chat] 上游返回错误', poeRes.status, body.slice(0, 500));
    }
    send({ type: 'error', error: msg });
    return res.end();
  }

  const startedAt = Date.now();
  const logId = db.prepare(`INSERT INTO usage_log
    (user_id,model,kind,key_id,prompt_tokens,completion_tokens,cached_tokens,in_images,out_images,
     url_count,url_raw_count,est_points,est_credits,charged_credits,cost_credits,status,started_at,created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(user.id, model, isImageModel ? 'image' : 'text', usedKey.id, 0, 0, 0, norm.images, 0,
      urlInfo.weighted || 0, urlInfo.total || 0,
      est.points, est.credits, 0, 0, 'pending', startedAt, startedAt).lastInsertRowid;

  if (isImageModel) send({ type: 'status', text: '图片生成中，通常需要 10~40 秒…' });
  else if (urlInfo.weighted > 0) send({ type: 'status', text: '检测到链接，模型可能会抓取网页内容（会额外消耗积分）…' });

  /* ---------- 流式读取（含思考过程） ---------- */
  const RCFG = config.reasoning || {};
  let fullText = '', reasonText = '', usage = null;
  let thinkStart = 0, thinkEnd = 0;

  const emitText = t => {
    if (!t) return;
    if (thinkStart && !thinkEnd) thinkEnd = Date.now();
    fullText += t;
    send({ type: 'delta', text: t });
  };
  const emitReason = t => {
    if (!t || !RCFG.enabled) return;
    if (!thinkStart) { thinkStart = Date.now(); send({ type: 'thinking_start' }); }
    if (reasonText.length < (RCFG.maxChars || 200000)) {
      reasonText += t;
      send({ type: 'reasoning', text: t });
    }
  };
  const splitter = (RCFG.enabled && RCFG.parseTags !== false) ? makeThinkSplitter() : null;
  const pushContent = d => {
    if (splitter) splitter.feed(d, emitText, emitReason);
    else emitText(d);
  };

  const reader = poeRes.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done: rdone, value } = await reader.read();
      if (rdone) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (data === '[DONE]') continue;
        try {
          const obj = JSON.parse(data);
          if (obj.usage) usage = obj.usage;
          const ch = obj.choices && obj.choices[0];
          const delta = (ch && (ch.delta || ch.message)) || null;
          if (!delta) continue;

          const rc = delta.reasoning_content || delta.reasoning || delta.thinking
            || (delta.reasoning_details && delta.reasoning_details.text);
          if (typeof rc === 'string' && rc) emitReason(rc);

          let d = delta.content;
          if (Array.isArray(d)) d = d.map(x => (typeof x === 'string' ? x : (x && x.text) || '')).join('');
          if (!d && delta && Array.isArray(delta.images)) {
            d = delta.images.map(im => `\n![image](${(im.image_url && im.image_url.url) || im.url || ''})\n`).join('');
          }
          if (d) pushContent(d);
        } catch { }
      }
    }
    if (splitter) splitter.flush(emitText, emitReason);
  } catch (e) {
    if (!clientGone) send({ type: 'error', error: '流式读取中断: ' + e.message });
  }
  const finishedAt = Date.now();
  if (thinkStart && !thinkEnd) thinkEnd = finishedAt;
  const thinkMs = thinkStart ? Math.max(0, thinkEnd - thinkStart) : 0;

  /* ---- 临时结算，随后由对账器修正为 Poe 真实积分 ---- */
  let pt, ct, cached = 0, rtok = 0;
  if (usage) {
    pt = usage.prompt_tokens || 0;
    ct = usage.completion_tokens || 0;
    const dd = usage.prompt_tokens_details || {};
    cached = dd.cached_tokens || 0;
    const cd = usage.completion_tokens_details || {};
    rtok = cd.reasoning_tokens || 0;
    if (RCFG.billWhenExcluded !== false && rtok > 0 && rtok >= ct) ct = ct + rtok;
  } else {
    pt = est.promptTokens;
    rtok = pricing.estimateTokens(reasonText);
    ct = pricing.estimateTokens(fullText) + rtok;
  }

  const outImages = isImageModel
    ? Math.max(1, (fullText.match(/!\[[^\]]*\]\([^)]+\)/g) || []).length)
    : (fullText.match(/!\[[^\]]*\]\([^)]+\)/g) || []).length;

  const base = { promptTokens: pt, completionTokens: ct, cachedTokens: cached, outputImages: outImages };

  const predPoints = pricing.upstreamPoints(model, base, { applyCalibration: false });

  const urlTokens = isImageModel ? 0 : pricing.urlExtraTokens(model, urlInfo.weighted);
  const chargeNoUrl = pricing.upstreamPoints(model, base, { applyCalibration: true });
  const chargePoints = pricing.upstreamPoints(model,
    Object.assign({}, base, { extraInputTokens: urlTokens }), { applyCalibration: true });
  const urlExtraPoints = Math.max(0, chargePoints - chargeNoUrl);
  const charged = pricing.pointsToCredits(chargePoints);

  db.transaction(() => {
    db.prepare('UPDATE users SET credits = credits - ? WHERE id=?').run(charged, user.id);
    db.prepare(`UPDATE usage_log SET prompt_tokens=?,completion_tokens=?,reasoning_tokens=?,cached_tokens=?,out_images=?,
      pred_points=?,url_extra_points=?,charged_credits=?,base_credits=?,cost_credits=?,finished_at=?,status=? WHERE id=?`)
      .run(pt, ct, rtok, cached, outImages, predPoints, urlExtraPoints, charged, charged, charged, finishedAt,
        config.reconcile.enabled ? 'pending' : 'final', logId);
  })();

  if (conversationId) {
    const conv = db.prepare('SELECT id FROM conversations WHERE id=? AND user_id=?').get(conversationId, user.id);
    if (conv) {
      const lastUser = msgs[msgs.length - 1];
      const isJson = typeof lastUser.content !== 'string';
      const uc = isJson ? JSON.stringify(lastUser.content) : lastUser.content;
      db.prepare('INSERT INTO messages (conversation_id,role,content,is_json,created_at) VALUES (?,?,?,?,?)')
        .run(conversationId, 'user', uc, isJson ? 1 : 0, Date.now());
      db.prepare('INSERT INTO messages (conversation_id,role,content,is_json,reasoning,think_ms,created_at) VALUES (?,?,?,?,?,?,?)')
        .run(conversationId, 'assistant', fullText, 0,
          (RCFG.persist !== false ? reasonText : ''), thinkMs, Date.now());
    }
  }

  finishedFlag = true;
  const newBal = r2(getUser(user.id).credits);
  send({
    type: 'done', cost: charged, balance: newBal,
    promptTokens: pt, completionTokens: ct, reasoningTokens: rtok, cachedTokens: cached,
    thinkMs,
    urlCount: urlInfo.weighted || 0, urlPoints: Math.round(urlExtraPoints),
    outImages, kind: isImageModel ? 'image' : 'text',
    poePoints: Math.round(chargePoints),
    estCredits: est.credits,
    pendingSettle: config.reconcile.enabled,
    lowBalance: newBal < config.lowBalanceCreditsWarn
  });
  if (!res.writableEnded) res.end();
  if (config.reconcile.enabled) reconcile.scheduleAfterChat();
});

/* ---------------- 兑换码充值 ---------------- */
app.post('/api/redeem', auth, (req, res) => {
  const { code } = req.body || {};
  if (!code) return res.status(400).json({ error: '请输入兑换码' });
  const c = code.trim().toUpperCase();
  const row = db.prepare('SELECT * FROM redeem_codes WHERE code=?').get(c);
  if (!row) return res.status(404).json({ error: '兑换码无效' });
  if (row.used_by) return res.status(400).json({ error: '兑换码已被使用' });
  db.transaction(() => {
    db.prepare('UPDATE redeem_codes SET used_by=?, used_at=? WHERE code=?').run(req.userId, Date.now(), c);
    db.prepare('UPDATE users SET credits = credits + ? WHERE id=?').run(row.credits, req.userId);
  })();
  res.json({ added: row.credits, balance: r2(getUser(req.userId).credits) });
});

/* ---------------- 管理后台 ---------------- */
app.post('/api/admin/login', (req, res) => {
  if ((req.body || {}).password !== config.adminPassword) return res.status(401).json({ error: '密码错误' });
  res.json({ token: jwt.sign({ admin: true }, config.jwtSecret, { expiresIn: '7d' }) });
});

app.post('/api/admin/codes', adminAuth, (req, res) => {
  const { credits, count, rmb } = req.body || {};
  const n = Math.min(parseInt(count) || 1, 500);
  let cr = parseFloat(credits);
  if ((!cr || cr <= 0) && parseFloat(rmb) > 0) {
    cr = Math.round(parseFloat(rmb) / config.economics.sellRmbPer10kCredits * 10000);
  }
  if (!cr || cr <= 0) return res.status(400).json({ error: '面值非法' });
  const codes = [];
  const stmt = db.prepare('INSERT INTO redeem_codes (code,credits,created_at) VALUES (?,?,?)');
  for (let i = 0; i < n; i++) {
    const code = 'POE-' + crypto.randomBytes(6).toString('hex').toUpperCase();
    stmt.run(code, cr, Date.now());
    codes.push(code);
  }
  res.json({ codes, creditsEach: cr });
});

app.post('/api/admin/topup', adminAuth, (req, res) => {
  const { username, credits, mode } = req.body || {};
  const u = db.prepare('SELECT * FROM users WHERE username=?').get(username || '');
  if (!u) return res.status(404).json({ error: '用户不存在' });
  const v = parseFloat(credits) || 0;
  if (mode === 'set') db.prepare('UPDATE users SET credits=? WHERE id=?').run(v, u.id);
  else db.prepare('UPDATE users SET credits = credits + ? WHERE id=?').run(v, u.id);
  res.json({ ok: true, balance: r2(getUser(u.id).credits) });
});

app.get('/api/admin/keys', adminAuth, (req, res) => {
  res.json({ keys: keyManager.status(), markup: config.sellMarkup, pointsPerUsd: config.pointsPerUsd });
});
app.post('/api/admin/refresh', adminAuth, async (req, res) => {
  await keyManager.refreshAll();
  res.json({ keys: keyManager.status() });
});

/* ---- 对账相关 ---- */
app.post('/api/admin/reconcile', adminAuth, async (req, res) => {
  const deep = !!(req.body && req.body.deep);
  const r = await reconcile.runOnce(true, deep);
  res.json({ ...r, status: reconcile.status() });
});
app.get('/api/admin/problems', adminAuth, (req, res) => res.json(reconcile.problemList()));
app.get('/api/admin/poe-usage', adminAuth, (req, res) => {
  const n = Math.min(parseInt(req.query.limit) || 60, 300);
  res.json(db.prepare(`SELECT query_id,key_id,bot_name,usage_type,source_kind,cost_points,creation_time,log_id,raw
    FROM poe_usage ORDER BY creation_time DESC LIMIT ?`).all(n));
});
app.post('/api/admin/reconcile/bind', adminAuth, (req, res) => {
  try {
    const { logId, queryIds } = req.body || {};
    res.json({ ok: true, ...reconcile.manualBind(logId, queryIds) });
  } catch (e) { res.status(400).json({ error: e.message }); }
});
app.post('/api/admin/reconcile/points', adminAuth, (req, res) => {
  try {
    const { logId, points } = req.body || {};
    res.json({ ok: true, ...reconcile.manualSettlePoints(logId, points) });
  } catch (e) { res.status(400).json({ error: e.message }); }
});
app.post('/api/admin/reconcile/retry', adminAuth, (req, res) => {
  res.json({ ok: true, moved: reconcile.retryUnmatched() });
});
app.post('/api/admin/reconcile/reset', adminAuth, (req, res) => {
  const hours = (req.body && req.body.hours) || 24;
  res.json({ ok: true, reset: reconcile.resetRange(hours) });
});

app.get('/api/admin/models', adminAuth, (req, res) => {
  const q = String(req.query.q || '').toLowerCase().split(/\s+/).filter(Boolean);
  const all = pricing.allModels();
  const list = all
    .filter(m => { const s = (m.id + ' ' + (m.owned_by || '')).toLowerCase(); return q.every(k => s.includes(k)); })
    .sort((a, b) => a.id.localeCompare(b.id))
    .slice(0, 300)
    .map(m => {
      const r = pricing.getRates(m.id);
      const img = pricing.isImageModel(m.id);
      return {
        id: m.id, owned_by: m.owned_by || '', custom: !!m.custom, src: r.source,
        kind: img ? 'image' : 'text',
        perImage: img ? r2(pricing.pointsPerImage(m.id)) : null,
        vision: pricing.isVisionModel(m.id),
        inPer1k: r2(r.inPer1k), outPer1k: r2(r.outPer1k)
      };
    });
  res.json({ total: all.length, loadedAt: modelsLoadedAt, error: modelsError, list });
});
app.post('/api/admin/models/refresh', adminAuth, async (req, res) => {
  try { const n = await refreshModels(); res.json({ ok: true, count: n }); }
  catch (e) { modelsError = e.message; res.status(500).json({ error: e.message }); }
});

app.get('/api/admin/stats', adminAuth, (req, res) => {
  const users = db.prepare('SELECT COUNT(*) c, SUM(credits) s FROM users').get();
  const usage = db.prepare(`SELECT COUNT(*) c, SUM(cost_credits) s, SUM(real_points) rp,
    SUM(pred_points) pp, SUM(out_images) oi, SUM(url_raw_count) uc, SUM(reasoning_tokens) rt FROM usage_log`).get();
  const realPts = usage.rp || 0;
  const ec = config.economics;
  res.json({
    userCount: users.c,
    totalUserCredits: r2(users.s || 0),
    totalCalls: usage.c,
    totalImages: usage.oi || 0,
    totalUrls: usage.uc || 0,
    totalReasoningTokens: usage.rt || 0,
    totalChargedCredits: r2(usage.s || 0),
    upstreamRealPoints: Math.round(realPts),
    upstreamPredPoints: Math.round(usage.pp || 0),
    revenueRmb: r2((usage.s || 0) / 10000 * ec.sellRmbPer10kCredits),
    costRmbSub: r2(realPts / 1e6 * ec.poeSubRmbPerMillionPoints),
    costRmbApi: r2(realPts / 1e6 * ec.apiRmbPerMillionPoints),
    markup: config.sellMarkup,
    safetyRatio: config.balanceSafetyRatio,
    reconcile: reconcile.status(),
    featuredModels: featuredList(),
    modelsCount: pricing.allModels().length,
    modelsLoadedAt, modelsError
  });
});

app.get('/api/admin/usage', adminAuth, (req, res) => {
  res.json(db.prepare(`SELECT l.id,u.username,l.model,l.kind,l.prompt_tokens,l.completion_tokens,l.reasoning_tokens,
    l.cached_tokens,l.in_images,l.out_images,l.url_raw_count,l.url_count,l.url_extra_points,l.est_credits,l.pred_points,
    l.real_points,l.charged_credits,l.base_credits,l.status,l.settle_note,l.created_at
    FROM usage_log l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 50`).all());
});
app.get('/api/admin/calibration', adminAuth, (req, res) => res.json(pricing.allCalibration()));
app.get('/api/admin/urlcalib', adminAuth, (req, res) => {
  const rows = pricing.allUrlCalibration().map(r => ({
    ...r,
    pointsPerUrl: r2(pricing.urlExtraPointsPerUrl(r.model))
  }));
  res.json({ rows, defaultTokens: (config.urlCost || {}).extraTokensPerUrl || 0 });
});

app.get('/api/admin/settings', adminAuth, (req, res) => {
  res.json({ featuredModels: featuredList(), customModels: customList() });
});
app.post('/api/admin/settings', adminAuth, (req, res) => {
  const { featuredModels, customModels } = req.body || {};
  const out = { ok: true };
  let touched = false;

  if (Array.isArray(customModels)) {
    const clean = customModels.map(x => ({
      id: String((x && x.id) || '').trim(),
      input: Number(x && x.input) || 0,
      output: Number(x && x.output) || 0,
      owned_by: String((x && x.owned_by) || 'custom').trim(),
      imagePoints: Number(x && x.imagePoints) || 0
    })).filter(x => x.id).slice(0, 100);
    db.setSetting('customModels', clean);
    pricing.setCustomModels(clean);
    out.customModels = clean;
    touched = true;
  }
  if (Array.isArray(featuredModels)) {
    const clean = featuredModels.map(s => String(s).trim()).filter(Boolean).slice(0, 20);
    db.setSetting('featuredModels', clean);
    out.featuredModels = clean;
    out.missing = clean.filter(n => !pricing.getModel(n));
    touched = true;
  }
  if (!touched) return res.status(400).json({ error: '参数缺失' });
  res.json(out);
});

/* ---------------- 启动 ---------------- */
async function boot() {
  pricing.setCustomModels(customList());

  try {
    const n = await refreshModels();
    console.log(`[启动] 已加载 ${n} 个 Poe 模型 + ${pricing.customModelIds().length} 个自定义模型；` +
      `1USD≈${config.pointsPerUsd}积分；售价倍率=${config.sellMarkup}；余额安全系数=${config.balanceSafetyRatio}`);
    for (const f of featuredList()) {
      if (!pricing.getModel(f)) console.warn(`[警告] 常用模型 "${f}" 不在 Poe 目录里，将按兜底价预估`);
    }
  } catch (e) {
    modelsError = e.message;
    console.error('[启动] 拉取模型失败，将使用兜底价:', e.message);
  }
  setInterval(() => refreshModels().catch(e => { modelsError = e.message; }), config.modelRefreshMs);

  await keyManager.refreshAll();
  setInterval(() => keyManager.refreshAll().catch(() => { }), config.balanceRefreshMs);

  if (config.reconcile.enabled) {
    setTimeout(() => reconcile.runOnce(true, true).catch(() => { }), 8000);
    setInterval(() => reconcile.runOnce().catch(() => { }), config.reconcile.intervalMs);
  }

  app.listen(config.port, () => console.log(`服务已启动 :${config.port}`));
}
boot();