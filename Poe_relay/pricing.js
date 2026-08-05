const config = require('./config');
const db = require('./db');

let apiMap = {};
let customMap = {};
let modelMap = {};

const r2 = x => Math.round(x * 100) / 100;
const low = s => String(s || '').toLowerCase();

function rebuild() {
  modelMap = Object.assign({}, apiMap);
  for (const k in customMap) modelMap[k] = customMap[k];
}

function setModels(models) {
  apiMap = {};
  for (const m of models || []) {
    if (!m || !m.id) continue;
    const p = m.pricing || {};
    apiMap[low(m.id)] = {
      id: m.id,
      prompt: parseFloat(p.prompt) || 0,
      completion: parseFloat(p.completion) || 0,
      request: p.request != null ? (parseFloat(p.request) || 0) : 0,
      inputModal: (m.architecture && m.architecture.input_modalities) || ['text'],
      output: (m.architecture && m.architecture.output_modalities) || ['text'],
      owned_by: m.owned_by || ''
    };
  }
  rebuild();
}

function normalizeCustom(list) {
  const out = {};
  for (const it of list || []) {
    if (!it) continue;
    const id = String(it.id || '').trim();
    if (!id) continue;
    const inP = Number(it.input) || 0;
    const outP = Number(it.output) || 0;
    const imgP = Number(it.imagePoints) || 0;
    out[low(id)] = {
      id,
      owned_by: it.owned_by || 'custom',
      prompt: inP / 1000 / config.pointsPerUsd,
      completion: outP / 1000 / config.pointsPerUsd,
      request: 0,
      inputModal: ['text', 'image'],
      output: imgP > 0 ? ['image'] : ['text'],
      custom: true,
      pointRates: (inP || outP) ? { input: inP, output: outP } : null,
      imagePoints: imgP
    };
  }
  return out;
}
function setCustomModels(list) {
  customMap = normalizeCustom([...(config.extraModels || []), ...(list || [])]);
  rebuild();
}
setCustomModels([]);

function getModel(id) { return modelMap[low(id)]; }
function allModels() { return Object.values(modelMap); }
function customModelIds() { return Object.values(customMap).map(m => m.id); }

/* ---------------- 图片模型判定与费率 ---------------- */
let imgPtsIndex = null;
function imagePointsOverride(id) {
  if (!imgPtsIndex) {
    imgPtsIndex = {};
    const src = (config.image && config.image.modelPointsPerImage) || {};
    for (const k in src) imgPtsIndex[low(k)] = src[k];
  }
  return imgPtsIndex[low(id)];
}

function isImageModel(id) {
  const l = low(id);
  if (!l) return false;
  if (imagePointsOverride(l)) return true;
  const m = getModel(l);
  if (m) {
    if (m.imagePoints > 0) return true;
    if (Array.isArray(m.output) && m.output.includes('image')) return true;
    if (!m.custom && Array.isArray(m.output) && m.output.length && !m.output.includes('image')) return false;
  }
  const hints = (config.image && config.image.imageModelHints) || [];
  return hints.some(k => l.includes(k));
}

function isVisionModel(id) {
  const m = getModel(id);
  if (!m) return true;
  if (Array.isArray(m.inputModal) && m.inputModal.includes('image')) return true;
  return !!m.custom;
}

function pointsPerImage(id) {
  const o = imagePointsOverride(id);
  if (o) return Number(o) || 0;
  const m = getModel(id);
  if (m && m.imagePoints > 0) return m.imagePoints;
  const r = getRates(id);
  if (r.perRequest > 0) return r.perRequest;
  return (config.image && config.image.defaultPointsPerImage) || 1500;
}

/* ---------------- 费率 ---------------- */
let overrideIndex = null;
function findOverride(id) {
  if (!overrideIndex) {
    overrideIndex = {};
    for (const k in (config.modelPointRates || {})) overrideIndex[low(k)] = config.modelPointRates[k];
  }
  return overrideIndex[low(id)];
}

function getRates(modelId) {
  const o = findOverride(modelId);
  if (o) {
    return {
      inPer1k: Number(o.input) || 0,
      outPer1k: Number(o.output) || 0,
      perRequest: Number(o.request) || 0,
      cacheWriteMult: o.cacheWriteMultiplier != null ? o.cacheWriteMultiplier : config.cache.writeMultiplier,
      cacheReadMult: o.cacheReadMultiplier != null ? o.cacheReadMultiplier : config.cache.readMultiplier,
      source: 'config'
    };
  }
  const m = getModel(modelId);
  if (m && m.custom && m.pointRates && (m.pointRates.input || m.pointRates.output)) {
    return {
      inPer1k: m.pointRates.input,
      outPer1k: m.pointRates.output,
      perRequest: 0,
      cacheWriteMult: config.cache.writeMultiplier,
      cacheReadMult: config.cache.readMultiplier,
      source: 'custom'
    };
  }
  if (m && (m.prompt || m.completion)) {
    return {
      inPer1k: m.prompt * 1000 * config.pointsPerUsd,
      outPer1k: m.completion * 1000 * config.pointsPerUsd,
      perRequest: (m.request || 0) * config.pointsPerUsd,
      cacheWriteMult: config.cache.writeMultiplier,
      cacheReadMult: config.cache.readMultiplier,
      source: 'poe-api'
    };
  }
  return {
    inPer1k: config.fallbackPricing.prompt * 1000 * config.pointsPerUsd,
    outPer1k: config.fallbackPricing.completion * 1000 * config.pointsPerUsd,
    perRequest: 0,
    cacheWriteMult: config.cache.writeMultiplier,
    cacheReadMult: config.cache.readMultiplier,
    source: 'fallback'
  };
}

/* ---------------- 模型费率自动校准 ---------------- */
function calibFactor(modelId) {
  if (!config.calibration.enabled) return 1;
  const r = db.prepare('SELECT factor,samples FROM model_calib WHERE model=?').get(low(modelId));
  if (!r || r.samples < config.calibration.minSamples) return 1;
  return Math.min(config.calibration.max, Math.max(config.calibration.min, r.factor));
}
function updateCalibration(modelId, predPoints, realPoints) {
  if (!config.calibration.enabled) return;
  if (!predPoints || predPoints <= 0 || !realPoints || realPoints <= 0) return;
  const key = low(modelId);
  const ratio = realPoints / predPoints;
  const a = config.calibration.alpha;
  const row = db.prepare('SELECT factor,samples FROM model_calib WHERE model=?').get(key);
  let factor = ratio, samples = 1;
  if (row) { factor = row.factor * (1 - a) + ratio * a; samples = row.samples + 1; }
  factor = Math.min(config.calibration.max, Math.max(config.calibration.min, factor));
  db.prepare(`INSERT INTO model_calib (model,factor,samples,updated_at) VALUES (?,?,?,?)
              ON CONFLICT(model) DO UPDATE SET factor=excluded.factor,samples=excluded.samples,updated_at=excluded.updated_at`)
    .run(key, factor, samples, Date.now());
}
function allCalibration() {
  return db.prepare('SELECT model,factor,samples,updated_at FROM model_calib ORDER BY samples DESC').all();
}

/* =========================================================
 * URL / 链接维度
 * ========================================================= */
const URL_RE = /https?:\/\/[^\s<>()\[\]{}"'`，。；、！？]+/gi;
const IMG_EXT_RE = /\.(png|jpe?g|gif|webp|bmp|svg|ico|avif)(\?|#|$)/i;

function extractUrls(text) {
  const cfg = config.urlCost || {};
  if (!text) return [];
  const m = String(text).match(URL_RE) || [];
  const out = [];
  for (let u of m) {
    u = u.replace(/[.,;:!?)\]}'"，。；、]+$/, '');
    if (u.length < 12) continue;
    if (cfg.ignoreImageUrl && IMG_EXT_RE.test(u)) continue;
    out.push(u);
  }
  return out;
}

function analyzeUrls(messages) {
  const cfg = config.urlCost || {};
  const empty = { total: 0, unique: 0, lastCount: 0, weighted: 0, list: [] };
  if (!cfg.enabled) return empty;
  const arr = Array.isArray(messages) ? messages : [];
  if (!arr.length) return empty;

  const lastIdx = arr.length - 1;
  const best = new Map();
  let total = 0, lastCount = 0;

  arr.forEach((m, i) => {
    const role = (m && m.role) || 'user';
    const urls = extractUrls(msgText(m));
    if (!urls.length) return;
    total += urls.length;

    let w;
    if (i === lastIdx) { w = 1; lastCount += urls.length; }
    else if (role === 'assistant') w = (cfg.assistantWeight != null ? cfg.assistantWeight : 0);
    else w = (cfg.historyWeight != null ? cfg.historyWeight : 0.25);
    if (w <= 0) return;

    for (const u of urls) {
      const k = cfg.dedupe === false ? (u + '#' + i) : low(u);
      best.set(k, Math.max(best.get(k) || 0, w));
    }
  });

  let weighted = 0;
  for (const v of best.values()) weighted += v;
  weighted = Math.min(weighted, cfg.maxUrlsCounted || 8);

  return {
    total,
    unique: best.size,
    lastCount,
    weighted: Math.round(weighted * 100) / 100,
    list: [...best.keys()].slice(0, 20)
  };
}

function urlTokensPerUrl(modelId) {
  const cfg = config.urlCost || {};
  const def = cfg.extraTokensPerUrl || 4500;
  if (!cfg.enabled) return 0;
  if (!cfg.learn) return def;
  const r = db.prepare('SELECT tokens,samples FROM url_calib WHERE model=?').get(low(modelId));
  if (!r || r.samples < (cfg.minSamples || 1)) return def;
  return Math.min(cfg.maxExtraTokens || 80000, Math.max(cfg.minExtraTokens || 0, r.tokens));
}
function urlExtraTokens(modelId, weightedUrls) {
  if (!(weightedUrls > 0)) return 0;
  return Math.round(weightedUrls * urlTokensPerUrl(modelId));
}
function urlExtraPointsPerUrl(modelId) {
  const r = getRates(modelId);
  return urlTokensPerUrl(modelId) * (r.inPer1k / 1000) * calibFactor(modelId);
}
function updateUrlCalibration(modelId, weightedUrls, extraPoints) {
  const cfg = config.urlCost || {};
  if (!cfg.enabled || !cfg.learn) return;
  if (!(weightedUrls > 0) || !(extraPoints > 0)) return;
  const r = getRates(modelId);
  const perTok = (r.inPer1k / 1000) * calibFactor(modelId);
  if (!(perTok > 0)) return;

  let tokens = extraPoints / perTok / weightedUrls;
  tokens = Math.min(cfg.maxExtraTokens || 80000, Math.max(cfg.minExtraTokens || 0, tokens));

  const key = low(modelId);
  const row = db.prepare('SELECT tokens,samples FROM url_calib WHERE model=?').get(key);
  const a = cfg.alpha || 0.35;
  let t = tokens, s = 1;
  if (row) { t = row.tokens * (1 - a) + tokens * a; s = row.samples + 1; }
  db.prepare(`INSERT INTO url_calib (model,tokens,samples,updated_at) VALUES (?,?,?,?)
              ON CONFLICT(model) DO UPDATE SET tokens=excluded.tokens,samples=excluded.samples,updated_at=excluded.updated_at`)
    .run(key, t, s, Date.now());
}
function allUrlCalibration() {
  return db.prepare('SELECT model,tokens,samples,updated_at FROM url_calib ORDER BY samples DESC').all();
}

/* ---------------- token 估算 ---------------- */
function estimateTokens(text) {
  if (!text) return 0;
  const cjk = (text.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef]/g) || []).length;
  const rest = text.length - cjk;
  return Math.ceil(cjk * 1.0 + rest / 4);
}
function msgParts(msg) {
  let text = '', images = 0;
  if (!msg) return { text, images };
  const c = msg.content;
  if (typeof c === 'string') text = c;
  else if (Array.isArray(c)) {
    for (const p of c) {
      if (!p) continue;
      if (p.type === 'image_url' || p.image_url) images++;
      else if (typeof p.text === 'string') text += p.text + ' ';
    }
  }
  return { text, images };
}
function msgText(msg) { return msgParts(msg).text; }
function countInputImages(messages) {
  let n = 0;
  for (const m of messages || []) n += msgParts(m).images;
  return n;
}
function countPromptTokens(messages) {
  const perImg = (config.image && config.image.inputTokensPerImage) || 800;
  let t = 0;
  for (const m of messages || []) {
    const { text, images } = msgParts(m);
    t += estimateTokens(text) + 4 + images * perImg;
  }
  return t;
}

/* ---------------- 上游积分计算 ---------------- */
function upstreamPoints(modelId, {
  promptTokens = 0, completionTokens = 0, cachedTokens = 0, cacheWriteTokens = 0,
  outputImages = 0, extraInputTokens = 0
} = {}, { applyCalibration = false, round = true } = {}) {
  const k = applyCalibration ? calibFactor(modelId) : 1;

  if (isImageModel(modelId)) {
    const n = Math.max(1, outputImages || 0);
    const raw = pointsPerImage(modelId) * n * k;
    return round ? Math.max(1, Math.ceil(raw - 1e-9)) : raw;
  }

  const r = getRates(modelId);
  const inRate = (r.inPer1k / 1000) * k;
  const outRate = (r.outPer1k / 1000) * k;

  const fresh = Math.max(0, promptTokens - cachedTokens - cacheWriteTokens);
  const inRaw = fresh * inRate
    + cacheWriteTokens * inRate * r.cacheWriteMult
    + cachedTokens * inRate * r.cacheReadMult
    + Math.max(0, extraInputTokens) * inRate;
  const outRaw = completionTokens * outRate;
  const reqRaw = (r.perRequest || 0) * k;

  if (round && config.pointRounding === 'component-ceil') {
    const ce = (raw, tok) => {
      if (tok <= 0) return 0;
      if (raw <= 0) return 0;
      return Math.max(1, Math.ceil(raw - 1e-9));
    };
    return ce(inRaw, promptTokens + Math.max(0, extraInputTokens))
      + ce(outRaw, completionTokens)
      + (reqRaw > 0 ? Math.ceil(reqRaw) : 0);
  }
  return inRaw + outRaw + reqRaw;
}

function pointsToCredits(points) {
  const p = Math.max(config.minChargePoints, points || 0);
  return Math.round(p * config.sellMarkup * 100) / 100;
}

/* ---------------- 输出长度预测 ---------------- */
function quantile(sortedArr, q) {
  if (!sortedArr.length) return 0;
  const pos = (sortedArr.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  if (lo === hi) return sortedArr[lo];
  return sortedArr[lo] + (sortedArr[hi] - sortedArr[lo]) * (pos - lo);
}
function historySamples(modelId) {
  const e = config.estimate;
  return db.prepare(
    `SELECT prompt_tokens p, completion_tokens c FROM usage_log
     WHERE lower(model)=? AND completion_tokens>0 AND created_at>?
     ORDER BY id DESC LIMIT ?`
  ).all(low(modelId), Date.now() - e.historyDays * 86400000, e.historyLimit);
}
function predictOutput(modelId, promptTokens) {
  const e = config.estimate;
  const rows = historySamples(modelId).filter(r => r.c > 0);
  const clamp = v => Math.min(e.maxOutputTokens, Math.max(e.minOutputTokens, Math.round(v)));

  if (rows.length >= e.minSamples) {
    const base = (promptTokens || 1) + 20;
    let pool = rows.filter(r => {
      const ratio = ((r.p || 1) + 20) / base;
      return ratio <= e.promptWindow && ratio >= 1 / e.promptWindow;
    });
    let source = 'history-similar';
    if (pool.length < e.minSamples) { pool = rows; source = 'history-all'; }

    pool = pool
      .map(r => ({ c: r.c, d: Math.abs(Math.log(((r.p || 1) + 20) / base)) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, Math.max(e.minSamples, Math.min(pool.length, e.knn)))
      .map(x => x.c)
      .sort((a, b) => a - b);

    const main = quantile(pool, e.mainQuantile);
    const high = Math.max(quantile(pool, e.highQuantile), main * e.highMinRatio);
    return { main: clamp(main), high: clamp(high), samples: pool.length, total: rows.length, source };
  }
  return {
    main: clamp(e.defaultOutputTokens),
    high: clamp(e.defaultOutputTokens * e.highOutputMultiplier),
    samples: rows.length, total: rows.length, source: 'default'
  };
}
function expectedOutputTokens(modelId) { return predictOutput(modelId, 500).main; }

/* ---------------- 发送前预估 ---------------- */
function estimate(modelId, messages) {
  const e = config.estimate;
  const promptTokens = countPromptTokens(messages);
  const inputImages = countInputImages(messages);
  const r = getRates(modelId);
  const known = !!getModel(modelId) || r.source === 'config' || !!imagePointsOverride(modelId);
  const urls = analyzeUrls(messages);

  if (isImageModel(modelId)) {
    const per = pointsPerImage(modelId);
    const mainPts = upstreamPoints(modelId, { promptTokens, outputImages: 1 }, { applyCalibration: true });
    const highPts = upstreamPoints(modelId,
      { promptTokens, outputImages: (config.image.highImageCount || 2) }, { applyCalibration: true });
    return {
      kind: 'image',
      promptTokens, inputImages,
      outputTokens: 0, outputTokensHigh: 0,
      perImagePoints: per,
      urlCount: 0, urlUnique: 0, urlTokens: 0, urlPoints: 0,
      samples: 0, predictSource: 'image-per-unit',
      points: r2(mainPts), highPoints: r2(Math.max(highPts, mainPts)),
      credits: pointsToCredits(mainPts),
      highCredits: pointsToCredits(Math.max(highPts, mainPts)),
      rateSource: imagePointsOverride(modelId) ? 'config-image' : r.source,
      knownModel: known,
      calib: Math.round(calibFactor(modelId) * 1000) / 1000
    };
  }

  const historyTokens = (messages && messages.length > 1) ? countPromptTokens(messages.slice(0, -1)) : 0;
  const o = predictOutput(modelId, promptTokens);

  const urlTok = urlExtraTokens(modelId, urls.weighted);
  const urlTokHigh = Math.round(urlTok * ((config.urlCost && config.urlCost.highMultiplier) || 1.8));

  const noUrlPts = upstreamPoints(modelId,
    { promptTokens, completionTokens: o.main }, { applyCalibration: true });

  const mainPts = upstreamPoints(modelId,
    { promptTokens, completionTokens: o.main, extraInputTokens: urlTok },
    { applyCalibration: true }) * e.buffer;

  const highPts = upstreamPoints(modelId, {
    promptTokens,
    completionTokens: o.high,
    cacheWriteTokens: e.assumeCacheWrite ? historyTokens : 0,
    extraInputTokens: urlTokHigh
  }, { applyCalibration: true }) * e.highBuffer;

  return {
    kind: 'text',
    promptTokens, inputImages,
    outputTokens: o.main,
    outputTokensHigh: o.high,
    samples: o.samples,
    predictSource: o.source,
    urlCount: urls.weighted,
    urlUnique: urls.unique,
    urlTokens: urlTok,
    urlPoints: r2(Math.max(0, mainPts / e.buffer - noUrlPts)),
    points: r2(mainPts),
    highPoints: r2(Math.max(highPts, mainPts)),
    credits: pointsToCredits(mainPts),
    highCredits: pointsToCredits(Math.max(highPts, mainPts)),
    rateSource: r.source,
    knownModel: known,
    calib: Math.round(calibFactor(modelId) * 1000) / 1000
  };
}

function requiredCredits(estCredits) {
  const ratio = config.balanceSafetyRatio || 1;
  return Math.round(Math.max(estCredits * ratio, config.minRequiredCredits || 0) * 100) / 100;
}

module.exports = {
  setModels, setCustomModels, customModelIds,
  getModel, allModels, getRates,
  estimateTokens, countPromptTokens, countInputImages, msgText,
  isImageModel, isVisionModel, pointsPerImage,
  upstreamPoints, pointsToCredits, estimate, requiredCredits,
  predictOutput, expectedOutputTokens,
  updateCalibration, calibFactor, allCalibration,
  analyzeUrls, extractUrls, urlTokensPerUrl, urlExtraTokens,
  urlExtraPointsPerUrl, updateUrlCalibration, allUrlCalibration,
  MARKUP: config.sellMarkup
};