// 所有可配置项集中在此。生产环境建议用 docker-compose 的 environment 覆盖敏感信息。
const path = require('path');

module.exports = {
  port: process.env.PORT || 3000,

  dbPath: process.env.DB_PATH || path.join(__dirname, 'data', 'app.db'),

  jwtSecret: process.env.JWT_SECRET || 'PLEASE-CHANGE-THIS-TO-A-LONG-RANDOM-SECRET',
  adminPassword: process.env.ADMIN_PASSWORD || 'admin-change-me',

  poeBaseUrl: 'https://api.poe.com',
  httpTimeoutMs: 25000,          // 【新增】所有上游 HTTP 的超时

  // ====== 多个 Poe API Key，余额不足自动切换 ======
  poeKeys: [
    { id: 'key1', key: process.env.POE_KEY_1 || 'sk-poe-wupWkYdv9cRfBxZWLHcVt3M0bFye2WPGJ4tvyA2knnI' },
    ...(process.env.POE_KEY_2 ? [{ id: 'key2', key: process.env.POE_KEY_2 }] : []),
    ...(process.env.POE_KEY_3 ? [{ id: 'key3', key: process.env.POE_KEY_3 }] : []),
  ],

  /* =========================================================
   * 计费核心（全部以 “Poe 积分(points)” 为内部单位）
   * ========================================================= */
  pointsPerUsd: 33000,
  sellMarkup: Number(process.env.SELL_MARKUP || 1.75),
  minChargePoints: 1,

  balanceSafetyRatio: Number(process.env.BALANCE_SAFETY_RATIO || 1.5),
  minRequiredCredits: 10,   // 另加一个绝对下限（点），太小的余额一律不给发

  pointRounding: 'component-ceil',

  cache: { writeMultiplier: 1.25, readMultiplier: 0.10 },

  /* ====== 发送前预估 ====== */
  estimate: {
    historyDays: 45,
    historyLimit: 300,
    minSamples: 3,
    promptWindow: 4,
    knn: 15,
    mainQuantile: 0.50,
    highQuantile: 0.90,
    highMinRatio: 1.6,
    minOutputTokens: 40,
    defaultOutputTokens: 500,
    maxOutputTokens: 12000,
    highOutputMultiplier: 3,
    buffer: 1.05,
    highBuffer: 1.15,
    assumeCacheWrite: true
  },

  /* =========================================================
   * 【新增·需求2】URL / 链接抓取成本维度
   * 模型看到链接会在服务端抓网页正文，这部分 token 不会出现在
   * usage.prompt_tokens 里，但 Poe 会照收积分。
   * 这里先用默认值预估，再由对账残差自动学习真实值。
   * ========================================================= */
  urlCost: {
    enabled: true,
    extraTokensPerUrl: 4500,
    maxUrlsCounted: 8,
    historyWeight: 0.25,     // 历史 user 消息里的旧链接权重
    assistantWeight: 0,      // 【新增】助手回复里的链接不会被重新抓取
    dedupe: true,
    ignoreImageUrl: true,
    learn: true,
    alpha: 0.35,
    minSamples: 1,
    minExtraTokens: 200,
    maxExtraTokens: 80000,
    highMultiplier: 1.8
  },

  /* =========================================================
   * 【新增】思考过程 (reasoning / chain-of-thought)
   * ========================================================= */
  reasoning: {
    enabled: true,
    parseTags: true,         // 解析 <think>/<thinking>/<reasoning> 标签
    maxChars: 200000,        // 单次最多保留多少思考字符（防爆库）
    persist: true,           // 存库，刷新页面后仍可展开查看
    billWhenExcluded: true   // usage 里 reasoning_tokens 明显未含在 completion 内时补计
  },

  /* 图片能力配置 */
  image: {
    enabled: true,
    maxUploadMB: 6,
    maxImagesPerMessage: 4,
    inputTokensPerImage: 800,
    defaultPointsPerImage: 1500,
    highImageCount: 2,

    modelPointsPerImage: {
      'GPT-Image-1': 1500,
      'GPT-Image-1-Mini': 400,
      'Imagen-3': 800,
      'Imagen-4': 1200,
      'FLUX-pro-1.1': 1500,
      'FLUX-schnell': 100,
      'Nano-Banana': 500,
      'Seedream-4': 800,
      'Ideogram-v3': 1200,
      'Recraft-V3': 1300,
      'Playground-v3': 400,
      'StableDiffusionXL': 200
    },

    // Poe 目录没标 output_modalities 时，用模型名关键词兜底判断是否为「出图模型」
    imageModelHints: [
      'imagen', 'flux', 'dall-e', 'dalle', 'stable-diffusion', 'stablediffusion', 'sdxl', 'sd3',
      'playground', 'nano-banana', 'seedream', 'midjourney', 'ideogram', 'recraft',
      'qwen-image', 'grok-image', 'gpt-image', 'photon', 'firefly', 'kolors', 'hidream'
    ]
  },

  calibration: { enabled: true, alpha: 0.3, minSamples: 2, min: 0.25, max: 6 },

  /* =========================================================
   * 【重写 v3】对账
   * ========================================================= */
  reconcile: {
    enabled: true,
    intervalMs: 60 * 1000,
    afterChatDelayMs: 25 * 1000,

    fetchLimit: 100,
    maxPages: 40,
    backfillDays: 7,

    matchWindowBeforeMs: 90 * 1000,
    matchWindowAfterMs: 15 * 60 * 1000,
    settleQuietMs: 90 * 1000,
    lateWindowMs: 30 * 60 * 1000,
    zeroLateWindowMs: 24 * 60 * 60 * 1000,   // 【新增】按0结算的记录 24h 内仍可被迟到条目修正
    pendingTimeoutMs: 2 * 60 * 60 * 1000,    // 2h 后进入宽松匹配阶段（原 6h 太久）

    zeroCostGuardRatio: 0.05,
    zeroCostGuardMinPred: 200,

    /* 宽松匹配 */
    looseAllowChatKind: true,        // 允许吸收被判成“网页聊天”的条目（分类可能不准）
    looseChatMaxDeltaMs: 3 * 60 * 1000,
    looseChatMinRatio: 0.25,
    looseChatMaxRatio: 5,

    /* 判 0 退款 */
    autoZeroWhenCovered: true,
    coverageWindowMs: 6 * 60 * 60 * 1000,

    /* unmatched 自动回炉 */
    reopenUnmatchedDays: 3,
    maxSettleTries: 5,

    maxFailBeforePause: 20,
    retryPerPage: 3,
    retryBaseMs: 4000
  },

  economics: {
    usdToRmb: 7.2,
    poeSubRmbPerMillionPoints: 144,
    apiRmbPerMillionPoints: 218,
    sellRmbPer10kCredits: 2.0
  },

  lowBalanceCreditsWarn: 3000,

  keyLowThresholdPoints: 50000,
  keyCriticalThresholdPoints: 2000,
  balanceRefreshMs: 5 * 60 * 1000,
  modelRefreshMs: 60 * 60 * 1000,

  alertEmail: {
    enabled: false,
    host: 'smtp.qq.com', port: 465, secure: true,
    user: 'you@qq.com', pass: 'your-smtp-auth-code', to: 'you@qq.com'
  },

  featuredModels: [
    'Claude-Opus-4.8',
    'Claude-Sonnet-4.6',
    'GPT-5.4',
    'Gemini-3.1-Flash-Lite',
    'GPT-Image-1'
  ],

  /* Poe /v1/models 不返回、但你确实能用的模型
   * imagePoints > 0 时会被识别为「出图模型」，按张计费 */
  extraModels: [
    // { id: 'Claude-Opus-5', input: 300, output: 1500, owned_by: 'anthropic' },
    // { id: 'Nano-Banana-Pro', input: 0, output: 0, owned_by: 'google', imagePoints: 900 },
  ],

  modelPointRates: {
    'Claude-Opus-4.8': { input: 142, output: 709 }
  },

  fallbackPricing: { prompt: 0.000003, completion: 0.000015 },

  showUpstreamDetail: true
};