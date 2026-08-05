const config = require('./config');
const poe = require('./poe');
const nodemailer = require('nodemailer');

class KeyManager {
  constructor() {
    this.keys = config.poeKeys.filter(k => k && k.key).map(k => ({
      ...k, balance: null, healthy: true, lastCheck: 0, lastError: ''
    }));
    this.alerted = false;
  }

  async refreshAll() {
    for (const k of this.keys) {
      try {
        k.balance = await poe.getBalance(k.key);
        k.healthy = k.balance > config.keyCriticalThresholdPoints;
        k.lastError = '';
        k.lastCheck = Date.now();
      } catch (e) {
        k.lastError = e.message;
        console.error('[keyManager] 余额查询失败', k.id, e.message);
      }
    }
    this.checkAlert();
  }

  pick() {
    const now = Date.now();
    // 冷却 60 秒后自动恢复
    this.keys.forEach(k => { if (!k.healthy && k.badAt && now - k.badAt > 60000) k.healthy = true; });
    const ok = this.keys.filter(k =>
      k.healthy && (k.balance === null || k.balance > config.keyCriticalThresholdPoints));
    if (!ok.length) return null;
    ok.sort((a, b) => (b.balance || 0) - (a.balance || 0));
    return ok[0];
  }

  markBad(id) {
    const k = this.keys.find(x => x.id === id);
    if (k) { k.healthy = false; k.badAt = Date.now(); }
    this.checkAlert();
  }

  checkAlert() {
    const usable = this.keys.filter(k => k.healthy && (k.balance || 0) > config.keyLowThresholdPoints);
    if (usable.length === 0 && !this.alerted) { this.alerted = true; this.sendAlert(); }
    if (usable.length > 0) this.alerted = false;
  }

  async sendAlert() {
    console.warn('[告警] 所有 Poe Key 点数已低于阈值，请尽快补充！');
    if (!config.alertEmail.enabled) return;
    try {
      const t = nodemailer.createTransport({
        host: config.alertEmail.host, port: config.alertEmail.port,
        secure: config.alertEmail.secure,
        auth: { user: config.alertEmail.user, pass: config.alertEmail.pass }
      });
      await t.sendMail({
        from: config.alertEmail.user, to: config.alertEmail.to,
        subject: '[Poe中转] API Key 余额告急',
        text: '所有 Poe API Key 积分已低于阈值，请尽快补充或添加新的 Key。\n\n' +
          this.keys.map(k => `${k.id}: ${k.balance} 积分 (healthy=${k.healthy})`).join('\n')
      });
      console.log('[告警] 邮件已发送');
    } catch (e) { console.error('[告警] 邮件发送失败', e.message); }
  }

  status() {
    return this.keys.map(k => ({
      id: k.id, balance: k.balance, healthy: k.healthy, lastError: k.lastError,
      lastCheck: k.lastCheck
    }));
  }
}

module.exports = new KeyManager();