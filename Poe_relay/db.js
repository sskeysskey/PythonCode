const fs = require('fs');
const path = require('path');
const Database = require('better-sqlite3');
const config = require('./config');

fs.mkdirSync(path.dirname(config.dbPath), { recursive: true });

if (!fs.existsSync(config.dbPath)) {
  const legacy = path.join(__dirname, 'data.db');
  if (fs.existsSync(legacy)) {
    try {
      fs.copyFileSync(legacy, config.dbPath);
      for (const ext of ['-wal', '-shm']) {
        if (fs.existsSync(legacy + ext)) fs.copyFileSync(legacy + ext, config.dbPath + ext);
      }
      console.log('[db] 已从旧位置 data.db 迁移数据到', config.dbPath);
    } catch (e) { console.error('[db] 旧库迁移失败', e.message); }
  }
}

const db = new Database(config.dbPath);
db.pragma('journal_mode = WAL');

db.exec(`
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL,
  credits REAL NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  title TEXT,
  model TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  model TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cost_credits REAL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS redeem_codes (
  code TEXT PRIMARY KEY,
  credits REAL NOT NULL,
  used_by INTEGER,
  used_at INTEGER,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS poe_usage (
  query_id TEXT PRIMARY KEY,
  key_id TEXT,
  bot_name TEXT,
  usage_type TEXT,
  cost_points INTEGER,
  creation_time INTEGER,
  log_id INTEGER,
  fetched_at INTEGER
);
CREATE TABLE IF NOT EXISTS model_calib (
  model TEXT PRIMARY KEY,
  factor REAL NOT NULL DEFAULT 1,
  samples INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER
);
/* 【新增】链接抓取成本校准：每个链接额外多少输入词元 */
CREATE TABLE IF NOT EXISTS url_calib (
  model TEXT PRIMARY KEY,
  tokens REAL NOT NULL DEFAULT 0,
  samples INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
  k TEXT PRIMARY KEY,
  v TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_log_user ON usage_log(user_id);
CREATE INDEX IF NOT EXISTS idx_poe_usage_time ON poe_usage(creation_time);
CREATE INDEX IF NOT EXISTS idx_poe_usage_log ON poe_usage(log_id);
`);

/* ---------- 轻量迁移 ---------- */
function columns(table) {
  return db.prepare(`PRAGMA table_info(${table})`).all().map(c => c.name);
}
function addCol(table, name, def) {
  if (!columns(table).includes(name)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${name} ${def}`);
}
[
  ['key_id', 'TEXT'],
  ['cached_tokens', 'INTEGER DEFAULT 0'],
  ['est_points', 'REAL'],
  ['est_credits', 'REAL'],
  ['pred_points', 'REAL'],
  ['charged_credits', 'REAL'],
  ['real_points', 'REAL'],
  ['status', 'TEXT'],
  ['started_at', 'INTEGER'],
  ['finished_at', 'INTEGER'],
  ['settled_at', 'INTEGER'],
  ['query_ids', 'TEXT'],
  ['kind', 'TEXT'],
  ['in_images', 'INTEGER DEFAULT 0'],
  ['out_images', 'INTEGER DEFAULT 0'],
  ['url_count', 'REAL DEFAULT 0'],
  ['url_raw_count', 'INTEGER DEFAULT 0'],
  ['url_extra_points', 'REAL DEFAULT 0'],
  ['base_credits', 'REAL'],
  ['settle_note', 'TEXT'],
  /* 【新增】 */
  ['reasoning_tokens', 'INTEGER DEFAULT 0'],
  ['settle_tries', 'INTEGER DEFAULT 0'],
].forEach(([n, d]) => addCol('usage_log', n, d));
db.exec(`CREATE INDEX IF NOT EXISTS idx_log_status ON usage_log(status)`);
db.exec(`CREATE INDEX IF NOT EXISTS idx_log_created ON usage_log(created_at)`);

[['raw', 'TEXT'], ['source_kind', 'TEXT'], ['matched_at', 'INTEGER']]
  .forEach(([n, d]) => addCol('poe_usage', n, d));

[['is_json', 'INTEGER DEFAULT 0'], ['reasoning', 'TEXT'], ['think_ms', 'INTEGER DEFAULT 0']]
  .forEach(([n, d]) => addCol('messages', n, d));

/* ---------- settings ---------- */
function getSetting(k, def = null) {
  const r = db.prepare('SELECT v FROM settings WHERE k=?').get(k);
  if (!r) return def;
  try { return JSON.parse(r.v); } catch { return r.v; }
}
function setSetting(k, v) {
  db.prepare('INSERT INTO settings (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v')
    .run(k, JSON.stringify(v));
}

module.exports = db;
module.exports.getSetting = getSetting;
module.exports.setSetting = setSetting;