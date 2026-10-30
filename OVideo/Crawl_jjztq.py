# -*- coding: utf-8 -*-
"""
jjztq.cn 分类页爬取脚本（当前仅 Movie，已预留 Drama/Anime/Show 扩展）

【默认用法】
    python Crawl_jjztq.py                 # curl_cffi 直连抓取；被拦截时自动降级真实 Chrome
    python Crawl_jjztq.py pages=3         # 分类页向后翻 3 页（默认只抓第 1 页）
    python Crawl_jjztq.py backfill        # 补全模式
    python Crawl_jjztq.py nobrowser       # 禁用浏览器兜底（纯直连）
    python Crawl_jjztq.py browser         # 强制全部走真实 Chrome
    python Crawl_jjztq.py headless        # 浏览器无头（不推荐）
【若站点启用了 Cloudflare】
    1) osascript -e 'quit app "Google Chrome"'
    2) python Crawl_jjztq.py open         # 启动带调试端口的 Chrome，手动过一次验证
    3) python Crawl_jjztq.py cdp          # 附着该 Chrome，同步 cookie 后直连高速抓取
参数可组合，例如：python Crawl_jjztq.py cdp pages=2
【单个详情页】见同目录 Crawl_jjztq_single.py
【白名单】WHITELIST_NAMES 中的影片不分分类，跳过一切过滤规则（年份/地区/黑名单/集数上限/追加渠道限制）
"""

import os
import re
import sys
import copy
import json
import time
import glob
import random
import shutil
import socket
import hashlib
import platform
import subprocess
import atexit
from collections import Counter
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import urlopen
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString, Tag

from curl_cffi import requests as cffi

try:
    import fcntl
except ImportError:          # Windows 无 fcntl，锁功能自动失效
    fcntl = None


# ================= 日志双写控制器 =================
class DualLogger:
    """同时将输出写入终端和磁盘日志文件"""
    def __init__(self, log_filepath):
        self.terminal = sys.stdout
        self.log_file = open(log_filepath, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.terminal.flush()
        self.log_file.write(message)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self):
        return getattr(self.terminal, "isatty", lambda: False)()


def setup_logging(tag=""):
    if isinstance(sys.stdout, DualLogger):      # 防止重复包装
        return
    log_dir = os.path.join(os.path.dirname(JSON_PATH), "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    log_file = os.path.join(log_dir, f"crawl_{SITE_KEY}{suffix}_{ts}.log")
    logger = DualLogger(log_file)
    sys.stdout = logger
    sys.stderr = logger
    print(f">>> [日志] 本次抓取日志将同步记录至: {log_file}")


# ================= 防止系统休眠控制 =================
_caffeinate_proc = None

def start_caffeinate():
    global _caffeinate_proc
    if platform.system() == 'Darwin':
        try:
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-idmu"])
            print(">>> [系统] 已开启防休眠模式 (caffeinate)")
        except Exception as e:
            print(f">>> [系统] 无法启动 caffeinate: {e}")

def stop_caffeinate():
    global _caffeinate_proc
    if _caffeinate_proc:
        try:
            _caffeinate_proc.terminate()
            print(">>> [系统] 已关闭防休眠模式")
        except Exception as e:
            print(f">>> [系统] 关闭 caffeinate 时出错: {e}")
        _caffeinate_proc = None

atexit.register(stop_caffeinate)


# ============== 站点及业务配置 ==============
DOMAIN        = "http://jjztq.cn"
SITE_HOST     = "jjztq.cn"                 # 用于识别「本站线路」（episode 链接域名）
SITE_KEY      = "jjztq"                    # 用于 url/url1/url2 键中识别本站
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
TARGET_COMPARE_CHANNEL = "shangxidq"          # 目标比对排序渠道
ENABLE_shangxidq_RULE     = True              # 新增渠道时是否启用 shangxidq 仲裁
REQUEST_TIMEOUT = 20
SLEEP_BETWEEN   = 1.0                      # 每条之间的基础间隔（会加随机抖动）

# —— 年份过滤：只抓这些年份 ——
ALLOWED_YEARS        = {"2026"}
SKIP_IF_YEAR_UNKNOWN = True                # 详情页解析不到年份时是否跳过

# —— 列表页 ——
MAX_LIST_PAGES     = 1                     # 每个分类最多翻几页（命令行 pages=N 可覆盖）
DETAIL_URL_PATTERN = re.compile(r"/zt/\d+\.html")   # 只认这种详情页链接，排除广告等

# 分类页（Drama 等后续需要时取消注释即可）
LIST_PAGES = [
    ("http://jjztq.cn/jj/1.html", "Movie", "电影(1)"),
    # ("http://jjztq.cn/jj/15.html", "Drama", "电视剧(2)"),
    # ("http://jjztq.cn/jj/3.html", "Show",  "综艺(3)"),
    # ("http://jjztq.cn/jj/4.html", "Anime", "动漫(4)"),
]

# 这些线路在存在其他渠道时需要排到最后
LOW_PRIORITY_LINES = ("阿里云", "线路1")

ALL_GROUPS           = ("Movie", "Drama", "Show", "Anime")
SERIAL_GROUPS        = ("Drama", "Anime", "Show")   # 连载类：按集数规则处理
ADD_CHANNEL_GROUPS   = ("Movie", "Drama", "Anime")  # 已有记录允许追加本站渠道的分类（同 shangxidq）
YEAR_CONFLICT_GROUPS = ("Movie",)                   # 名称去重时校验年份冲突的分类（防翻拍片误合并）

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "日本"]
FILTER_REGIONS_BY_GROUP = {
    "Movie": ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "Drama": ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产",
              "泰国", "台湾", "中国台湾", "日本"],
    "Anime": ["中国", "大陆", "内地", "国产", "中国大陆", "中国内地", "国产剧",
              "泰国", "台湾", "中国台湾", "日本"],
}

BLACKLIST_NAMES = [
    "天堂之剑", "定海神针：九尾三世劫", "机甲少女破时空战记", "永恒和一日",
    "无名传奇", "魔彩王国历险记", "阿松与阿暖", "欲望的陷阱", "轻松熊", "家1",
    "人生赢家", "判决", "判决墨西哥剧", "后门", "校规101", "校规", "无人区",
    "第二盘",
]
BLACKLIST_URLS = []
# 白名单：不分分类，跳过一切过滤规则（优先级高于黑名单）
WHITELIST_NAMES = ["二十世纪电气目录", "茶啊二中 第六季", "猫与龙",
                   "骸骨骑士大人异世界冒险中Ⅱ", "炒翻天", "什么意思夫妇",
                   "超超超超超喜欢你的100个女朋友 第三季", "神探之痕迹",
                   "虽然我不是完美恶女～雏宫蝶鼠替换传～",
                   "暗芝居 第十七季", "鬼之花嫁", "成长秀～向日葵马戏团～"]

QIANGXIAN_KEYWORDS = ['TC', 'TS', '抢先', 'HC']
TC_LOCK_NAMES = {}

EMPTY_VALUES = {"未知", "内详", "暂无", "/", "-", "无"}
INVALID_EPISODE_NAMES = {"立即播放", "收藏", "播放", "下载"}
MAX_EPISODES = 30

# ============ 数据安全相关配置 ============
BACKUP_DIR = os.path.join(os.path.dirname(JSON_PATH), "backup")
BAK_FILE = JSON_PATH + ".bak"
REJECTED_FILE = JSON_PATH + ".rejected.json"
LOCK_FILE = JSON_PATH + ".lock"
MAX_BACKUPS = 20
ALLOW_SHRINK_RATIO = 0.90
SHRINK_GUARD_MIN_ITEMS = 20
ALLOW_FRESH_START = False

_BASELINE_TOTAL = 0
_LOAD_OK = False
_LAST_SIG = None          # 上次读/写后主文件的 (mtime_ns, size)，用于检测外部并发修改
_LOCK_FH = None

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 5.0

# ============== 浏览器 / Cloudflare 兜底配置 ==============
USER_DATA_DIR   = os.path.expanduser("~/.jjztq_chrome_profile")
BROWSER_CHANNEL = "chrome"
HEADLESS        = False
CDP_PORT        = 9223          # 与 shangxidq(9222) 错开，可同时运行
CDP_ENDPOINT    = f"http://127.0.0.1:{CDP_PORT}"
USE_CDP         = False
FORCE_BROWSER   = False         # True：所有页面都走浏览器
BROWSER_FALLBACK = True         # 直连被拦截时是否自动启用浏览器
NAV_TIMEOUT_MS  = 60000
IMPERSONATE_CANDIDATES = ["chrome", "chrome124", "chrome120", "chrome110"]
DIRECT_BLOCK_LIMIT = 3          # 同步 cookie 后直连仍连续被拦 N 次，则后续优先走浏览器

CHALLENGE_WAIT   = 600
CHALLENGE_GRACE  = 10
PASS_STABLE_HITS = 3
POLL_INTERVAL    = 1.5
SITE_READY_TIMEOUT = 8
PAGE_SETTLE      = 1.0
AUTO_CLICK_TURNSTILE   = True
AUTO_CLICK_FIRST_DELAY = 8
AUTO_CLICK_EVERY       = 15

CHALLENGE_MARKERS = (
    "Just a moment", "challenges.cloudflare.com/turnstile", "__cf_chl", "cf_chl_opt",
    "cf-challenge", "challenge-platform", "Checking your browser", "Verifying you are human",
    "Enable JavaScript and cookies to continue", "需要先验证您是真人", "正在验证您是否是真人",
)
SITE_MARKERS = ("myui-vodlist", "myui-content", "myui-panel", "myui-header")


# ============== 异常类型 ==============
class FetchError(Exception):
    pass

class NoRetryFetchError(FetchError):
    pass

class ConcurrentWriteError(Exception):
    """检测到 JSON 被其他进程修改，必须中止，避免覆盖别人的数据"""
    pass


# ==========================================================
#                    数据安全：锁 / 备份
# ==========================================================
def acquire_run_lock():
    """同一时间只允许一个爬虫写 OVideos.json（需其他爬虫也加同样的锁才完全生效）"""
    global _LOCK_FH
    if fcntl is None or _LOCK_FH is not None:
        return
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    _LOCK_FH = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(">>> [锁] ⏳ 另一个爬虫正在写入 OVideos.json，等待其结束 ...")
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX)
    print(">>> [锁] 已获得数据文件独占锁 🔒")

def release_run_lock():
    global _LOCK_FH
    if fcntl is None or _LOCK_FH is None:
        return
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _LOCK_FH.close()
    except Exception:
        pass
    _LOCK_FH = None
    print(">>> [锁] 已释放数据文件锁 🔓")

def _file_sig(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None

def count_items(data: dict) -> int:
    if not isinstance(data, dict):
        return 0
    return sum(len(v) for v in data.values() if isinstance(v, list))

def _read_json_strict(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    if not txt.strip():
        raise ValueError("文件内容为空（0 字节或全空白）")
    data = json.loads(txt)
    if not isinstance(data, dict):
        raise ValueError(f"顶层结构不是 dict，而是 {type(data).__name__}")
    return data

def _backup_candidates() -> list:
    cands = [BAK_FILE]
    try:
        cands.extend(sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")), reverse=True))
    except Exception:
        pass
    return cands

def snapshot_backup(path: str):
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"OVideos_{ts}.json")
        shutil.copy2(path, dst)
        print(f">>> [备份] 启动快照已保存: {dst}")
        snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")))
        if len(snaps) > MAX_BACKUPS:
            for old in snaps[:len(snaps) - MAX_BACKUPS]:
                try:
                    os.remove(old)
                except Exception:
                    pass
    except Exception as e:
        print(f">>> [备份] 创建启动快照失败: {e}")

def _quarantine_corrupt(path: str):
    """【修复】把损坏的主文件挪开，防止后续 save_json 把它复制成 .bak 覆盖掉好备份"""
    if not os.path.exists(path):
        return
    dst = f"{path}.corrupt_{time.strftime('%Y%m%d_%H%M%S')}"
    try:
        os.replace(path, dst)
        print(f">>> [隔离] 损坏的主文件已移至: {dst}")
    except Exception as e:
        print(f">>> [隔离] 移动损坏文件失败: {e}")

def _empty_db():
    return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

def load_existing(path: str) -> dict:
    global _BASELINE_TOTAL, _LOAD_OK, _LAST_SIG
    main_exists = os.path.exists(path)
    main_size = os.path.getsize(path) if main_exists else -1

    if main_exists and main_size > 0:
        try:
            data = _read_json_strict(path)
            _BASELINE_TOTAL = count_items(data)
            _LOAD_OK = True
            _LAST_SIG = _file_sig(path)
            print(f">>> [读取] 主文件正常: {path} ({main_size/1024:.1f} KB, {_BASELINE_TOTAL} 条)")
            return data
        except Exception as e:
            print(f"\n❌ [严重] 主数据文件损坏，无法解析: {e}")
    elif main_exists:
        print(f"\n❌ [严重] 主数据文件为 0 字节: {path}")

    if main_exists:
        for cand in _backup_candidates():
            if not os.path.exists(cand) or os.path.getsize(cand) == 0:
                continue
            try:
                data = _read_json_strict(cand)
            except Exception:
                continue
            _BASELINE_TOTAL = count_items(data)
            _LOAD_OK = True
            print(f"✅ [恢复] 已从备份恢复数据: {cand} ({_BASELINE_TOTAL} 条)")
            _quarantine_corrupt(path)
            save_json(data, force=True, quiet=False)
            return data

        if not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print("脚本已终止：为防止用空数据覆盖你的历史库，本次不会写入任何内容。")
            print("!" * 70 + "\n")
            sys.exit(1)
        _quarantine_corrupt(path)
    else:
        # 主文件不存在：如果有备份，多半是路径/磁盘问题，不要悄悄从零建库
        has_backup = any(os.path.exists(c) and os.path.getsize(c) > 0 for c in _backup_candidates())
        if has_backup and not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print(f"主数据文件不存在：{path}")
            print("但检测到备份文件存在，可能是路径错误或文件被误删。脚本已终止。")
            print(f"请从 {BAK_FILE} 或 {BACKUP_DIR} 手动恢复，或将 ALLOW_FRESH_START 改为 True。")
            print("!" * 70 + "\n")
            sys.exit(1)

    _BASELINE_TOTAL = 0
    _LOAD_OK = True
    _LAST_SIG = _file_sig(path)
    return _empty_db()

def save_json(data: dict, force: bool = False, quiet: bool = True) -> bool:
    global _BASELINE_TOTAL, _LAST_SIG
    if not _LOAD_OK:
        print("  [拒绝保存] 初始数据未成功加载，禁止写盘")
        return False
    if not isinstance(data, dict):
        return False

    # —— 并发写保护：文件在我们读取之后被其他进程改过 ——
    if not force and _file_sig(JSON_PATH) != _LAST_SIG:
        try:
            with open(REJECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        raise ConcurrentWriteError(
            f"检测到 {JSON_PATH} 在本脚本运行期间被其他进程修改（可能有其他爬虫同时在跑）。"
            f"为避免覆盖对方数据，已中止。本次内存数据已另存到 {REJECTED_FILE}")

    total = count_items(data)
    if (not force) and _BASELINE_TOTAL >= SHRINK_GUARD_MIN_ITEMS and total < _BASELINE_TOTAL * ALLOW_SHRINK_RATIO:
        print(f"\n  ⛔ [拒绝保存] 条目数异常缩水：{_BASELINE_TOTAL} -> {total}")
        try:
            with open(REJECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"  [提示] 可疑数据已另存到 {REJECTED_FILE}，主文件未被修改\n")
        except Exception:
            pass
        return False

    try:
        payload = json.dumps(data, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"  [错误] JSON 序列化失败: {e}")
        return False
    if len(payload.strip()) < 10:
        return False

    tmp_file = JSON_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
        if os.path.exists(JSON_PATH) and os.path.getsize(JSON_PATH) > 0:
            try:
                shutil.copy2(JSON_PATH, BAK_FILE)
            except Exception:
                pass
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        _read_json_strict(tmp_file)
        os.replace(tmp_file, JSON_PATH)
        _LAST_SIG = _file_sig(JSON_PATH)
        _BASELINE_TOTAL = max(_BASELINE_TOTAL, total)
        if not quiet:
            print(f"  [已保存] 共 {total} 条")
        return True
    except Exception as e:
        print(f"  [错误] 实时保存失败: {e}")
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass
        return False


# ==========================================================
#                    CDP：启动 / 探测 Chrome
# ==========================================================
def cdp_alive(port=CDP_PORT, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except Exception:
        return False
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            json.loads(r.read().decode("utf-8", "ignore"))
        return True
    except Exception:
        return False

def cdp_launch_command():
    return ('open -na "Google Chrome" --args \\\n'
            f'  --user-data-dir="{USER_DATA_DIR}" \\\n'
            f'  --remote-debugging-port={CDP_PORT} \\\n'
            f'  {DOMAIN}/')

def launch_chrome_for_cdp(open_url=True):
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    if cdp_alive():
        print(f">>> [CDP] 端口 {CDP_PORT} 已在监听，无需重复启动。")
        return True
    print(">>> [CDP] 正在启动 Chrome（若已有 Chrome 在运行，请先 ⌘Q 完全退出！）")
    args = [f"--user-data-dir={USER_DATA_DIR}", f"--remote-debugging-port={CDP_PORT}",
            "--no-first-run", "--no-default-browser-check"]
    if open_url:
        args.append(DOMAIN + "/")
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-na", "Google Chrome", "--args"] + args)
        else:
            subprocess.Popen(["google-chrome"] + args)
    except Exception as e:
        print(f"!!! 启动失败：{e}\n请手动执行：\n{cdp_launch_command()}")
        return False
    for _ in range(30):
        time.sleep(1)
        if cdp_alive():
            print(f">>> [CDP] Chrome 已就绪（端口 {CDP_PORT}）。如有验证请手动通过，然后执行：")
            print("        python Crawl_jjztq.py cdp")
            return True
    print("!!! 等待调试端口超时。请先执行：osascript -e 'quit app \"Google Chrome\"' 再重试。")
    print("    或手动执行：\n" + cdp_launch_command())
    return False


# ==========================================================
#                   真实浏览器（兜底层）
# ==========================================================
_STATE_JS = """
() => {
  const q = s => !!document.querySelector(s);
  const hasSite = q('ul.myui-vodlist') || q('[class*="myui-content"]') ||
                  q('[class*="myui-panel"]') || q('[class*="myui-header"]') ||
                  q('a[href*="/zt/"]');
  const cfFrame = Array.from(document.querySelectorAll('iframe'))
                       .some(f => (f.src || '').includes('challenges.cloudflare.com'));
  const hasChl  = cfFrame || q('#challenge-form') || q('#challenge-running') ||
                  q('#cf-challenge-running') || q('.cf-turnstile') ||
                  q('#turnstile-wrapper') || q('#challenge-stage');
  const title   = document.title || '';
  const titleChl = /just a moment|attention required|checking your browser|verify|请稍候|稍等|安全检查/i.test(title);
  const len = (document.body && document.body.innerText) ? document.body.innerText.length : 0;
  return { hasSite, hasChl, titleChl, len, title };
}
"""

def _looks_like_challenge(html: str) -> bool:
    if not html:
        return True
    if any(m in html for m in SITE_MARKERS):
        return False
    if any(m in html[:10000] for m in CHALLENGE_MARKERS):
        return True
    return len(html) < 500     # 过短且无站点结构，视为异常页


class BrowserHelper:
    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None
        self._browser = None
        self.ua = ""

    @property
    def started(self):
        return self._ctx is not None

    def start(self):
        if self._ctx is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise FetchError("需要浏览器兜底但未安装 playwright：pip install playwright && playwright install chromium")

        self._pw = sync_playwright().start()
        if USE_CDP:
            if not cdp_alive():
                print(f"\n!!! 没有检测到可用的 Chrome 调试端口 {CDP_ENDPOINT}")
                print("请先执行：python Crawl_jjztq.py open   或手动执行：")
                print(cdp_launch_command())
                raise FetchError("CDP 端口不可用")
            print(f">>> [CDP] 正在附着到已运行的 Chrome：{CDP_ENDPOINT}")
            self._browser = self._pw.chromium.connect_over_cdp(CDP_ENDPOINT)
            self._ctx = (self._browser.contexts[0]
                         if self._browser.contexts else self._browser.new_context())
        else:
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            print(f">>> [浏览器] 启动真实 Chrome（profile: {USER_DATA_DIR}）")
            kw = dict(
                user_data_dir=USER_DATA_DIR, headless=HEADLESS, locale="zh-CN",
                timezone_id="Asia/Shanghai", viewport={"width": 1360, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                      "--no-default-browser-check", "--start-maximized"],
                ignore_default_args=["--enable-automation"],
            )
            if BROWSER_CHANNEL:
                kw["channel"] = BROWSER_CHANNEL
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**kw)
            except Exception as e:
                print(f">>> [浏览器] 用系统 Chrome 启动失败({e})，改用 Playwright 自带 Chromium")
                kw.pop("channel", None)
                self._ctx = self._pw.chromium.launch_persistent_context(**kw)
            try:
                self._ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except Exception:
                pass

        self._ctx.set_default_timeout(NAV_TIMEOUT_MS)
        self._ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self._page = self._pick_page()
        try:
            self.ua = self._page.evaluate("() => navigator.userAgent") or ""
        except Exception:
            self.ua = ""

    def _pick_page(self):
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        for p in pages:
            try:
                if SITE_HOST in (p.url or ""):
                    return p
            except Exception:
                continue
        return pages[0] if pages else self._ctx.new_page()

    def cookies(self):
        if not self._ctx:
            return {}
        try:
            return {c["name"]: c["value"] for c in self._ctx.cookies(DOMAIN)}
        except Exception:
            return {}

    def close(self):
        try:
            if self._ctx and not USE_CDP:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = self._page = self._browser = None

    def _page_state(self):
        try:
            info = self._page.evaluate(_STATE_JS)
        except Exception:
            return "unknown", ""
        try:
            html = self._page.content()
        except Exception:
            html = ""
        try:
            cf_frame = any("challenges.cloudflare.com" in (f.url or "") for f in self._page.frames)
        except Exception:
            cf_frame = False
        if info.get("hasSite"):
            return "site", html
        if info.get("hasChl") or info.get("titleChl") or cf_frame:
            return "challenge", html
        return "unknown", html

    def _notify_challenge(self, url):
        print("\a", end="", flush=True)
        print("\n" + "=" * 72)
        print("  ⚠️  检测到人机验证页面，脚本已暂停")
        print("  👉  请切到 Chrome 窗口完成验证")
        print(f"  ⏳  至少等 {CHALLENGE_GRACE} 秒，最长等 {CHALLENGE_WAIT} 秒。URL: {url}")
        if not USE_CDP:
            print("  💡 反复过不去时：osascript -e 'quit app \"Google Chrome\"' → "
                  "python Crawl_jjztq.py open → 手动过验证 → python Crawl_jjztq.py cdp")
        print("=" * 72 + "\n")
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        if platform.system() == "Darwin":
            try:
                subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'],
                               check=False, capture_output=True)
            except Exception:
                pass

    def _try_click_turnstile(self) -> bool:
        try:
            for fr in self._page.frames:
                if "challenges.cloudflare.com" not in (fr.url or ""):
                    continue
                for sel in ("input[type=checkbox]", "#challenge-stage input[type=checkbox]",
                            "label.ctp-checkbox-label", "#cf-stage input"):
                    try:
                        loc = fr.locator(sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.click(timeout=2000)
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    def _wait_until_ready(self, url, _depth=0):
        soft_deadline = time.time() + SITE_READY_TIMEOUT
        hard_deadline = time.time() + CHALLENGE_WAIT
        challenge_seen, grace_until, next_click_at, last_tip, stable = False, 0.0, 0.0, 0.0, 0
        html = ""
        while True:
            state, html = self._page_state()
            if state == "site" and not (challenge_seen and time.time() < grace_until):
                stable += 1
                if stable >= (PASS_STABLE_HITS if challenge_seen else 1):
                    if challenge_seen:
                        print("    ✅ 人机验证已通过，继续抓取\n")
                        time.sleep(1.0)
                        cur = (self._page.url or "").split("#")[0].rstrip("/")
                        tgt = url.split("#")[0].rstrip("/")
                        if _depth == 0 and cur != tgt:
                            self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                            time.sleep(PAGE_SETTLE)
                            return self._wait_until_ready(url, _depth=1)
                        try:
                            html = self._page.content()
                        except Exception:
                            pass
                    return html
            else:
                stable = 0

            if state == "challenge":
                if not challenge_seen:
                    challenge_seen = True
                    self._notify_challenge(url)
                    grace_until = time.time() + CHALLENGE_GRACE
                    next_click_at = time.time() + AUTO_CLICK_FIRST_DELAY
                    last_tip = time.time()
                if AUTO_CLICK_TURNSTILE and time.time() >= next_click_at:
                    if self._try_click_turnstile():
                        print("    [自动] 已尝试点击 Turnstile 复选框")
                    next_click_at = time.time() + AUTO_CLICK_EVERY

            if challenge_seen:
                if time.time() - last_tip > 20:
                    print(f"    ... 仍在等待人机验证（剩余 {int(hard_deadline - time.time())}s）")
                    last_tip = time.time()
                if time.time() > hard_deadline:
                    raise FetchError(f"等待人机验证超时: {url}")
            elif time.time() > soft_deadline:
                return html
            time.sleep(POLL_INTERVAL)

    def get_html(self, url):
        self.start()
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        status = resp.status if resp else 0
        if status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        time.sleep(PAGE_SETTLE)
        html = self._wait_until_ready(url)
        if status >= 500 or status == 429:
            state, _ = self._page_state()
            if state != "site":
                raise FetchError(f"HTTP {status}: {url}")
        return html

    def get_bytes(self, url):
        self.start()
        r = self._ctx.request.get(url, timeout=REQUEST_TIMEOUT * 1000,
                                  headers={"Referer": DOMAIN + "/"})
        if r.status == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status >= 400:
            raise FetchError(f"HTTP {r.status}: {url}")
        return r.body()


# ==========================================================
#              抓取层：curl_cffi 直连 + 浏览器兜底
# ==========================================================
def decode_html(content: bytes, content_type: str = "") -> str:
    """自动识别 UTF-8 / GBK 编码"""
    if not content:
        return ""
    enc = None
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w\-]+)', content[:4096], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    cands = []
    if enc:
        enc = enc.lower()
        if enc in ("gb2312", "gbk", "gb_2312-80"):
            enc = "gb18030"
        cands.append(enc)
    cands += ["utf-8", "gb18030"]
    for e in cands:
        try:
            return content.decode(e)
        except Exception:
            continue
    return content.decode("utf-8", "replace")


class Fetcher:
    def __init__(self):
        self.browser = BrowserHelper()
        self._session = None
        self._cookies = {}
        self._started = False
        self._prefer_browser = False
        self._blocked_after_sync = 0

    def _get_session(self):
        if self._session is not None:
            return self._session
        last_err = None
        for imp in IMPERSONATE_CANDIDATES:
            try:
                s = cffi.Session(impersonate=imp)
                s.headers.update({
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                })
                print(f">>> [直连] curl_cffi 使用 TLS 指纹: {imp}")
                self._session = s
                return s
            except Exception as e:
                last_err = e
        raise FetchError(f"无法创建 curl_cffi Session: {last_err}")

    def sync_from_browser(self):
        if not self.browser.started:
            return
        self._cookies = self.browser.cookies()
        s = self._get_session()
        if self.browser.ua:
            s.headers["User-Agent"] = self.browser.ua
        print(f">>> [同步] 已从浏览器同步 {len(self._cookies)} 个 cookie 到直连通道"
              f"（cf_clearance: {'有 ✅' if 'cf_clearance' in self._cookies else '无'}）")

    def start(self):
        if self._started:
            return
        self._started = True
        if FORCE_BROWSER or USE_CDP:
            self.browser.start()
            self.sync_from_browser()
        print(">>> [预热] 访问首页检查连通性 ...")
        try:
            self.get_html(DOMAIN + "/")
            print(">>> [预热] 站点可正常访问 ✅")
        except Exception as e:
            print(f">>> [预热] 异常（不致命，继续）：{e}")

    def close(self):
        self.browser.close()
        try:
            if self._session:
                self._session.close()
        except Exception:
            pass
        self._session = None

    def _direct_get(self, url, referer=None):
        s = self._get_session()
        headers = {"Referer": referer} if referer else None
        cookies = self._cookies if (self._cookies and SITE_HOST in url) else None
        return s.get(url, headers=headers, cookies=cookies,
                     timeout=REQUEST_TIMEOUT, allow_redirects=True)

    def _browser_html(self, url):
        html = self.browser.get_html(url)
        self.sync_from_browser()
        return html

    def get_html(self, url):
        if not self._started:
            self.start()
        if FORCE_BROWSER or self._prefer_browser:
            return self.browser.get_html(url)
        try:
            r = self._direct_get(url, referer=DOMAIN + "/")
        except Exception as e:
            raise FetchError(f"网络请求异常: {e}")
        if r.status_code == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status_code == 429:
            raise FetchError(f"HTTP 429 请求过快: {url}")
        html = decode_html(r.content, r.headers.get("content-type", ""))
        blocked = r.status_code in (403, 503) or _looks_like_challenge(html)
        if not blocked:
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}: {url}")
            if self.browser.started:
                self._blocked_after_sync = 0
            return html

        if not BROWSER_FALLBACK:
            raise FetchError(f"疑似拦截/挑战页 (HTTP {r.status_code})，已禁用浏览器兜底: {url}")
        if self.browser.started:
            self._blocked_after_sync += 1
            if self._blocked_after_sync >= DIRECT_BLOCK_LIMIT:
                print("    [直连] 同步 cookie 后仍多次被拦，后续页面改为优先走浏览器")
                self._prefer_browser = True
        print(f"    [直连] 命中拦截/挑战页 (HTTP {r.status_code})，切换真实浏览器处理 ...")
        return self._browser_html(url)

    def get_bytes(self, url):
        if not self._started:
            self.start()
        if FORCE_BROWSER or self._prefer_browser:
            return self.browser.get_bytes(url)
        try:
            r = self._direct_get(url, referer=DOMAIN + "/")
        except Exception as e:
            if self.browser.started:
                return self.browser.get_bytes(url)
            raise FetchError(f"网络请求异常: {e}")
        if r.status_code == 404:
            raise NoRetryFetchError(f"HTTP 404 (不重试): {url}")
        if r.status_code >= 400:
            if self.browser.started:
                return self.browser.get_bytes(url)
            raise FetchError(f"HTTP {r.status_code}: {url}")
        return r.content


_fetcher = Fetcher()
atexit.register(_fetcher.close)


def fetch(url, is_binary=False):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _fetcher.get_bytes(url) if is_binary else _fetcher.get_html(url)
        except NoRetryFetchError:
            raise
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                if "验证" in str(e) or "Cloudflare" in str(e) or "429" in str(e):
                    wait = max(wait, 15)
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)
    raise last_err if last_err else FetchError(f"请求失败: {url}")

def polite_sleep():
    time.sleep(SLEEP_BETWEEN * random.uniform(0.8, 1.5))


# ============== 通用工具函数 ==============
def _re_class(base):
    return re.compile(r"^" + base.replace("_", "_+") + r"$")

def clean_url(u):
    if not u:
        return ""
    return re.sub(r"\s+", "", str(u)).strip("'\"")

def has_tc_keyword(text: str) -> bool:
    if not text:
        return False
    upper = str(text).upper()
    return any(kw.upper() in upper for kw in QIANGXIAN_KEYWORDS)

def is_in_tc_lock_list(name: str) -> bool:
    if not name or not TC_LOCK_NAMES:
        return False
    clean = re.sub(r"\s+", "", str(name)).lower()
    return any(re.sub(r"\s+", "", str(x)).lower() == clean for x in TC_LOCK_NAMES)

def _norm_space(s):
    return re.sub(r"\s+", "", s or "")

def is_blacklisted_name(name):
    if not name:
        return False
    n = _normalize_name(name)
    return any(_normalize_name(b) == n for b in BLACKLIST_NAMES)

def is_whitelisted_name(name):
    if not name:
        return False
    n = _normalize_name(name)
    return any(_normalize_name(w) == n for w in WHITELIST_NAMES)

def is_garbled(value):
    if not value:
        return False
    v = str(value)
    if "\ufffd" in v:
        return True
    stripped = re.sub(r"[\s/·,，、|\-]", "", v)
    if not stripped:
        return False
    return bool(re.fullmatch(r"[?？]+", stripped))

def normalize_text(s):
    if not s:
        return ""
    entity_map = {
        "&middot": "·", "&mdash": "—", "&ndash": "–",
        "&ldquo": "\u201c", "&rdquo": "\u201d", "&lsquo": "\u2018", "&rsquo": "\u2019",
        "&iacute": "í", "&nbsp": " ", "&lrm": "", "&rlm": "",
    }
    for ent, ch in entity_map.items():
        s = s.replace(ent + ";", ch).replace(ent + "；", ch)
    s = s.replace("\u200e", "").replace("\u200f", "")
    s = s.replace("・", "·").replace("‧", "·")
    s = s.replace("\xa0", " ").replace("\u3000", " ")
    s = re.sub(r"[，；;]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·•")
    return s

def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES or is_garbled(v):
        return ""
    return v

def num_to_chinese(num_str):
    try:
        num = int(num_str)
    except ValueError:
        return num_str
    d = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    if num < 10:
        return d[num]
    if num == 10:
        return "十"
    if num < 20:
        return f"十{d[num % 10]}"
    if num < 100:
        return f"{d[num // 10]}十" + (d[num % 10] if num % 10 else "")
    return num_str

def split_name_info(raw_title):
    raw_title = (raw_title or "").strip()
    base_name, base_info = raw_title, ""
    m = re.search(r"^(.*?)[\[［](.*?)[\]］]$", raw_title)
    if m:
        base_name, base_info = m.group(1).strip(), m.group(2).strip()
    else:
        m = re.search(r"^(.*?)\s+((?:第[0-9一二三四五六七八九十百\-]+季)(?:全)?)$", raw_title)
        if m:
            base_name, base_info = m.group(1).strip(), m.group(2).strip()

    def rep(mm):
        return f"{mm.group(1)}{num_to_chinese(mm.group(2))}{mm.group(3)}"
    base_name = re.sub(r"(第)(\d+)(季)", rep, base_name)
    base_info = re.sub(r"(第)(\d+)(季)", rep, base_info)

    if not base_info:
        return base_name, ""
    if base_info == "全集":
        return base_name, "全集"
    if base_info.endswith("季全"):
        if re.search(r"[\-\d~至]", base_info):
            return base_name, base_info
        return f"{base_name} {base_info[:-1]}", base_info
    if base_info.endswith("季"):
        return f"{base_name} {base_info}", ""
    return base_name, base_info

def get_episode_unit(group="", episodes=None, info_text=""):
    if episodes:
        names_str = " ".join(str(k) for k in episodes.keys())
        if "期" in names_str:
            return "期"
        if "话" in names_str or "話" in names_str:
            return "话"
        if "集" in names_str:
            return "集"
    if info_text:
        if "期" in info_text:
            return "期"
        if "话" in info_text or "話" in info_text:
            return "话"
        if "集" in info_text:
            return "集"
    return "期" if group == "Show" else "集"

def make_episode_info(num, unit="集"):
    return f"更新至第{num}{unit}"

def get_max_episode_number(episodes):
    if not episodes:
        return 0
    se = []
    for n in episodes.keys():
        m = re.search(r'S(\d+)E(\d+)', str(n), re.IGNORECASE)
        if m:
            se.append((int(m.group(1)), int(m.group(2))))
    if se:
        ms = max(s for s, _ in se)
        return max(e for s, e in se if s == ms)
    sp = []
    for n in episodes.keys():
        m = re.search(r'第\s*(\d+)\s*季.*?第\s*(\d+)\s*[集期话話]', str(n))
        if m:
            sp.append((int(m.group(1)), int(m.group(2))))
    if sp:
        ms = max(s for s, _ in sp)
        return max(e for s, e in sp if s == ms)
    mx = 0
    for n in episodes.keys():
        m = (re.search(r'(\d+)\s*[集期话話]', str(n)) or re.search(r'第\s*(\d+)', str(n))
             or re.search(r'(\d+)', str(n)))
        if m:
            mx = max(mx, int(m.group(1)))
    return mx

def get_effective_episode_count(episodes, group=""):
    if not episodes:
        return 0
    if group == "Movie":
        return len(episodes)
    num = get_max_episode_number(episodes)
    if num > 500:
        has_real = any(re.search(r'(\d+)\s*[集期话話]|S\d+E\d+|第\s*(\d+)', str(n)) for n in episodes.keys())
        if not has_real:
            return len(episodes)
    return num if num > 0 else len(episodes)

def is_valid_episode_name(name):
    if not name or name in INVALID_EPISODE_NAMES:
        return False
    return not re.match(r"^更新[至到]", name)

def filter_episodes(eps):
    return {k: v for k, v in eps.items() if is_valid_episode_name(k)}

def extract_year(*candidates):
    for c in candidates:
        if not c:
            continue
        m = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(c))
        if m:
            return m.group(0)
    return ""

def normalize_url(u):
    if not u:
        return ""
    u = str(u).strip()
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    u = re.sub(r"^www\.", "", u, flags=re.IGNORECASE)
    return u.rstrip("/")

def _is_site_url(u):
    try:
        host = urlparse(str(u)).netloc.lower().split(":")[0]
    except Exception:
        return False
    return host == SITE_HOST or host.endswith("." + SITE_HOST)


# ============== 本站线路（多 playlist）块操作 ==============
def is_site_playlist(pl):
    eps = pl.get("episodes") or {}
    return any(_is_site_url(v) for v in eps.values())

def site_playlist_indices(playlist):
    return [i for i, pl in enumerate(playlist) if is_site_playlist(pl)]

def remove_indices(playlist, indices):
    for i in sorted(indices, reverse=True):
        playlist.pop(i)

def playlist_signature(pls):
    """与线路顺序无关的签名：按线路名排序，集数也按名称排序后比较"""
    return sorted(
        (pl.get("name") or "",
         tuple(sorted((pl.get("episodes") or {}).items())))
        for pl in pls
    )

def total_episode_count(pls):
    return sum(len(pl.get("episodes") or {}) for pl in pls)

def _url_keys_sorted(existing):
    return sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

def has_site_url_key(existing, sub_url):
    for k in _url_keys_sorted(existing):
        v = existing.get(k, "") or ""
        if SITE_KEY in v or normalize_url(v) == normalize_url(sub_url):
            return True
    return False

def _ensure_site_url(existing, sub_url, force_new=False):
    url_keys = _url_keys_sorted(existing)
    if not force_new:
        for k in url_keys:
            v = existing.get(k, "") or ""
            if SITE_KEY in v or normalize_url(v) == normalize_url(sub_url):
                return k
    max_num = 0
    for k in url_keys:
        m = re.match(r"^url(\d+)$", k)
        if m:
            max_num = max(max_num, int(m.group(1)))
    new_key = f"url{max_num + 1}"
    last = url_keys[-1] if url_keys else None
    ordered, inserted = {}, False
    for k, v in existing.items():
        ordered[k] = v
        if k == last:
            ordered[new_key] = sub_url
            inserted = True
    if not inserted:
        ordered[new_key] = sub_url
    existing.clear()
    existing.update(ordered)
    return new_key

def resolve_insert_position_with_shangxidq(playlist, new_episodes, default_insert_pos=None, group="", log=print):
    """本站 ≥ shangxidq 集数(选集数) 时，必须排在 shangxidq 之前（同 shangxidq 规则）"""
    target = len(playlist) if default_insert_pos is None else max(0, min(default_insert_pos, len(playlist)))
    g_idx = next((i for i, pl in enumerate(playlist)
                  if pl.get("name", "").strip().lower() == TARGET_COMPARE_CHANNEL.lower()), None)
    if g_idx is None:
        return target
    cnt_g = get_effective_episode_count(playlist[g_idx].get("episodes", {}), group=group)
    cnt_s = get_effective_episode_count(new_episodes, group=group)
    if cnt_s >= cnt_g:
        if target > g_idx:
            log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) >= {TARGET_COMPARE_CHANNEL}({cnt_g})，"
                f"插入位置由第 {target + 1} 位提前至第 {g_idx + 1} 位")
            target = g_idx
        else:
            log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) >= {TARGET_COMPARE_CHANNEL}({cnt_g})，"
                f"目标位置第 {target + 1} 位已在其之前，符合规则")
    else:
        log(f"      🛡️ [渠道优先级仲裁] {SITE_KEY}({cnt_s}) < {TARGET_COMPARE_CHANNEL}({cnt_g})，保持第 {target + 1} 位")
    return target

def merge_missing_fields(existing, rec, log=print):
    changed = False
    for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]:
        old_val = existing.get(field)
        new_val = rec.get(field)
        if isinstance(new_val, str) and is_garbled(new_val):
            continue
        if isinstance(new_val, list):
            new_val = [x for x in new_val if not is_garbled(x)]
        if (not old_val) and new_val:
            existing[field] = new_val
            changed = True
            log(f"      [字段更新] 补充缺失字段「{field}」: {new_val}")
    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if new_date and (not old_date or len(str(new_date)) > len(str(old_date))):
        existing["date"] = new_date
        changed = True
        log(f"      [字段更新] 更新「date」字段: 「{old_date}」 -> 「{new_date}」")
    existing.setdefault("评分", {"豆瓣": "", "IMDB": ""})
    return changed

def region_blocked(region, filter_regions):
    region = (region or "").strip()
    if not region:
        return False
    if region in filter_regions:
        return True
    tokens = [t for t in re.split(r"[,，/、|\s]+", region) if t]
    return bool(tokens) and all(t in filter_regions for t in tokens)


# ============== 图片下载 ==============
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".heic"}

def safe_filename(url):
    """【修复】通用/过短/非法文件名（如 cover.jpg、1.jpg）改用 站点+URL哈希，避免不同影片封面互相覆盖"""
    base = os.path.basename(unquote(url.split("?")[0].split("#")[0]))
    stem, ext = os.path.splitext(base)
    ext_l = ext.lower()
    if base and len(stem) >= 8 and ext_l in _IMG_EXTS and not re.search(r'[\\:*?"<>|\s]', base):
        return base
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    return f"{SITE_KEY}_{digest}{ext_l if ext_l in _IMG_EXTS else '.jpg'}"

def _looks_like_image(b: bytes) -> bool:
    if not b or len(b) < 512:
        return False
    return (b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n"
            or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")
            or b[:6] in (b"GIF87a", b"GIF89a")
            or b[4:12] in (b"ftypavif", b"ftypheic", b"ftypmif1"))

def download_and_localize_image(img_url):
    img_url = clean_url(img_url)
    if not img_url:
        return ""
    fn = safe_filename(img_url)
    if not fn:
        return ""
    local_path = os.path.join(IMG_DIR, fn)
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return fn
    try:
        content = fetch(img_url, is_binary=True)
        if not _looks_like_image(content):
            print(f"  [图片下载失败] 返回内容不是有效图片（可能被拦截）: {img_url}")
            return ""
        os.makedirs(IMG_DIR, exist_ok=True)
        tmp = local_path + ".part"
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, local_path)
        print(f"  [图片] 已下载 -> {fn}")
        return fn
    except Exception as e:
        print(f"  [图片下载失败] {img_url}: {e}")
        return ""


# ============== 列表页解析 ==============
def parse_list_items(soup, base_url):
    out = []
    for li in soup.select("ul[class*='myui-vodlist'] > li"):
        thumb = li.find("a", class_=_re_class("myui-vodlist_thumb"))
        title_a = li.select_one("h4.title a[href]") or li.select_one(".title a[href]")
        a = title_a or thumb
        if not a:
            continue
        href = (a.get("href") or "").strip() or ((thumb.get("href") or "").strip() if thumb else "")
        if not href:
            continue
        full = urljoin(base_url, href)
        if DETAIL_URL_PATTERN and not DETAIL_URL_PATTERN.search(urlparse(full).path):
            continue
        title = normalize_text(a.get("title") or a.get_text(strip=True)
                               or (thumb.get("title") if thumb else "") or "")
        if not title:
            continue

        info, img = "", ""
        if thumb:
            pic = thumb.select_one("span.pic-text")
            if pic:
                info = normalize_text(pic.get_text(strip=True))
            img = thumb.get("data-original") or thumb.get("data-src") or ""
            if not img:
                m = re.search(r"url\(\s*['\"]?(.*?)['\"]?\s*\)", thumb.get("style", "") or "")
                if m:
                    img = m.group(1)
            if not img:
                it = thumb.find("img")
                if it:
                    img = it.get("data-original") or it.get("src") or ""
        img = clean_url(img)
        img = urljoin(base_url, img) if img else ""

        name, _ = split_name_info(title)
        out.append((name or title, info, full, img))
    return out

def find_next_page(soup, cur_url):
    for a in soup.select("a[href]"):
        if normalize_text(a.get_text(strip=True)) in ("下一页", "下页"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript", "#")):
                return None
            nxt = urljoin(cur_url, href)
            return None if normalize_url(nxt) == normalize_url(cur_url) else nxt
    return None

def collect_list_items(list_url):
    items, seen, visited = [], set(), set()
    url = list_url
    for page_no in range(1, max(1, MAX_LIST_PAGES) + 1):
        if url in visited:
            break
        visited.add(url)
        soup = BeautifulSoup(fetch(url), "lxml")
        page_items = parse_list_items(soup, url)
        new = 0
        for it in page_items:
            if it[2] in seen:
                continue
            seen.add(it[2])
            items.append(it)
            new += 1
        print(f"  [列表] 第 {page_no} 页解析到 {len(page_items)} 条（去重后新增 {new}）")
        if page_no >= MAX_LIST_PAGES:
            break
        nxt = find_next_page(soup, url)
        if not nxt:
            break
        url = nxt
        polite_sleep()
    return items


# ============== 详情页解析 ==============
def parse_title_and_status(soup, default_name):
    detail = soup.find(class_=_re_class("myui-content_detail"))
    h1 = (detail.find("h1") if detail else None) or soup.select_one("h1.title")
    if not h1:
        return default_name, ""
    h1 = copy.copy(h1)
    status = ""
    for tag in h1.find_all(["font", "span", "small", "em", "i"]):
        t = normalize_text(tag.get_text(strip=True))
        if t and not status:
            status = t
        tag.decompose()
    t = normalize_text(h1.get_text(" ", strip=True))
    if not t:
        return default_name, status
    name, _ = split_name_info(t)
    return (name or t), status

def _title_fallback_name(soup):
    """h1 缺失时（单页模式无列表名可用）从 <title> 兜底取片名"""
    t = soup.title.get_text(strip=True) if soup.title else ""
    t = re.split(r"\s*[-_|–—]\s*", t)[0].strip() if t else ""
    t = re.sub(r"(在线观看|免费观看|高清|完整版|全集|电影|电视剧).*$", "", t).strip()
    t = normalize_text(t)
    return split_name_info(t)[0] if t else ""

def _detect_field(text):
    if not text:
        return None
    if re.search(r"导\s*演", text):
        return "导演"
    if re.search(r"编\s*剧", text):
        return "编剧"
    if re.search(r"主\s*演|演\s*员", text):
        return "主演"
    if re.search(r"分\s*类|类\s*型|类\s*别", text):
        return "类型"
    if re.search(r"地\s*区", text):
        return "地区"
    if re.search(r"年\s*份|上\s*映|首\s*播|发\s*行", text):
        return "date"
    return None

LIST_FIELDS = ("类型", "主演", "导演", "编剧")

def parse_detail_fields(detail_div):
    result = {"类型": [], "地区": "", "date": "", "主演": [], "导演": [], "编剧": []}
    if detail_div is None:
        return result

    def assign(field, value):
        value = _clean_val(value)
        if not value:
            return
        if field in LIST_FIELDS:
            if value not in result[field]:
                result[field].append(value)
        elif not result[field]:
            result[field] = value

    p_tags = detail_div.select("p.data") or detail_div.select("p")
    for p in p_tags:
        current = None
        for node in p.children:
            if isinstance(node, Tag):
                if node.name == "span":
                    classes = node.get("class", []) or []
                    if "split-line" in classes:
                        current = None
                        continue
                    matched = _detect_field(node.get_text(strip=True))
                    if matched:
                        current = matched
                    elif "text-muted" in classes:
                        current = None
                elif node.name == "a" and current:
                    assign(current, node.get_text(strip=True))
            elif isinstance(node, NavigableString) and current:
                assign(current, str(node))
    return result

KV_MAP = {
    "date": ("发行年份", "上映年份", "年份", "上映时间", "上映日期", "首播"),
    "地区": ("首映地区", "地区", "制片国家/地区", "国家/地区"),
    "类型": ("电影类别", "剧集类别", "类别", "类型", "分类"),
    "导演": ("导演",),
    "编剧": ("编剧",),
    "主演": ("主演", "演员"),
}

def _split_people(v):
    parts = re.split(r"[,，/、|]+|\s{2,}", v or "")
    return [x for x in (_clean_val(p) for p in parts) if x]

def _clean_intro(text):
    text = normalize_text(text)
    text = re.sub(r"^(剧情简介|剧情介绍|简介|剧情)[：:]\s*", "", text)
    text = re.sub(r"\s*详情\s*$", "", text)
    return "" if is_garbled(text) else text

def parse_info_panel(soup):
    """解析「剧情介绍」面板（id=jq）：简介 + 片名/年份/地区等 key：value 兜底信息"""
    res = {"intro": "", "kv": {}}
    panel = soup.find(id="jq")
    if not panel:
        for hd in soup.find_all(class_=_re_class("myui-panel_hd")):
            if re.search(r"剧情|简介", hd.get_text()):
                panel = hd.find_parent(class_=_re_class("myui-panel-box")) or hd.parent
                break
    if not panel:
        return res

    bd = panel.find(class_=_re_class("myui-panel_bd"))
    if bd:
        direct = " ".join(str(s) for s in bd.find_all(string=True, recursive=False))
        res["intro"] = _clean_intro(direct)

    for p in panel.find_all("p"):
        t = normalize_text(p.get_text(" ", strip=True))
        m = re.match(r"^([^：:]{1,10})[：:]\s*(.+)$", t)
        if m:
            res["kv"].setdefault(m.group(1).strip(), m.group(2).strip())
        elif not res["intro"] and len(t) > 20 and not t.startswith("如何评价"):
            res["intro"] = _clean_intro(t)
    return res

def parse_desc_fallback(detail):
    if not detail:
        return ""
    desc = detail.find("p", class_="desc")
    if not desc:
        return ""
    full = desc.select_one("span.data") or desc.select_one("span.sketch")
    text = full.get_text(" ", strip=True) if full else desc.get_text(" ", strip=True)
    return _clean_intro(text)

def extract_playlists(soup, page_url):
    """按「播放地址」tab 顺序抓取所有线路，每条线路一个 playlist"""
    list_cls = _re_class("myui-content_list")
    panes = {}
    for pane in soup.find_all("div", id=True):
        if "tab-pane" in (pane.get("class") or []) and pane.find("ul", class_=list_cls):
            panes[pane["id"].strip().lower()] = pane

    ordered, used = [], set()
    for a in soup.select("ul.nav-tabs li a[href]"):
        href = (a.get("href") or "").strip()
        if not href.startswith("#"):
            continue
        pid = href[1:].strip().lower()
        if pid in panes and pid not in used:
            ordered.append((normalize_text(a.get_text(strip=True)), panes[pid]))
            used.add(pid)
    for pid, pane in panes.items():           # tab 未覆盖到的线路
        if pid not in used:
            ordered.append(("", pane))
            used.add(pid)
    if not ordered:                            # 完全没有 tab 结构时兜底
        ordered = [("", ul) for ul in soup.find_all("ul", class_=list_cls)]

    result, name_count = [], {}
    for i, (line_name, container) in enumerate(ordered, 1):
        uls = [container] if container.name == "ul" else container.find_all("ul", class_=list_cls)
        eps = {}
        for ul in uls:
            for a in ul.select("li a[href]"):
                href = (a.get("href") or "").strip()
                if not href or href.startswith(("javascript", "#")):
                    continue
                full = urljoin(page_url, href)
                if urlparse(full).scheme not in ("http", "https"):
                    continue          # 跳过 thunder:// magnet: 等下载协议
                ep = normalize_text(a.get_text(strip=True)) or normalize_text(a.get("title", ""))
                if not ep:
                    continue
                key, n = ep, 2
                while key in eps and eps[key] != full:
                    key = f"{ep}({n})"
                    n += 1
                eps[key] = full
        eps = filter_episodes(eps)
        if not eps:
            continue
        name = line_name or f"线路{i}"
        if name in name_count:
            name_count[name] += 1
            name = f"{name}{name_count[name]}"
        else:
            name_count[name] = 1
        result.append({"name": name, "episodes": eps})
    return result

def move_low_priority_lines_to_end(playlists):
    """
    若存在 LOW_PRIORITY_LINES 之外的线路（如 腾讯云、线路2、芒果），
    则把 阿里云、线路1 移到列表末尾；否则保持原顺序不变。
    各组内部保留抓取时的原始相对顺序。
    """
    low_names = {_norm_space(x) for x in LOW_PRIORITY_LINES}

    def is_low(pl):
        return _norm_space(pl.get("name", "")) in low_names

    normal = [pl for pl in playlists if not is_low(pl)]
    low = [pl for pl in playlists if is_low(pl)]

    if not normal or not low:      # 只有其中一类时不需要调整
        return playlists
    return normal + low

# ============== 芒果线路置顶 ==============
MANGO_KEYWORD = "芒果"   # 线路名包含该关键字即视为芒果渠道

def move_mango_within_site(playlist):
    """
    只在本站线路内部把「芒果」线路置顶。
    - 本站线路占据的下标位置保持不变，只调整它们之间的先后顺序
    - 其他渠道（如 shangxidq 等）的位置完全不动
    - 同为芒果的多条线路保持原相对顺序
    原地修改 playlist，返回是否发生了变化。
    """
    site_idx = [i for i, pl in enumerate(playlist) if is_site_playlist(pl)]
    if not site_idx:
        return False

    site = [playlist[i] for i in site_idx]
    mango = [pl for pl in site if MANGO_KEYWORD in (pl.get("name") or "")]
    if not mango:
        return False

    rest = [pl for pl in site if MANGO_KEYWORD not in (pl.get("name") or "")]
    new_site = mango + rest
    if all(a is b for a, b in zip(new_site, site)):
        return False

    # 按原来的下标位置回填，保证其他渠道的位置不变
    for i, pl in zip(site_idx, new_site):
        playlist[i] = pl
    return True

def parse_subpage(sub_url, default_name, default_info, list_img=""):
    """返回 (rec, meta)；meta 中含 year，不写入 JSON"""
    soup = BeautifulSoup(fetch(sub_url), "lxml")
    detail = soup.find(class_=_re_class("myui-content_detail"))

    real_name, status = parse_title_and_status(soup, default_name)
    if not real_name:
        real_name = _title_fallback_name(soup)
    fields = parse_detail_fields(detail)
    panel = parse_info_panel(soup)
    kv = panel["kv"]

    def kv_get(field):
        for k in KV_MAP[field]:
            if kv.get(k):
                return kv[k]
        return ""

    if not fields["date"]:
        fields["date"] = _clean_val(kv_get("date"))
    if not fields["地区"]:
        fields["地区"] = _clean_val(kv_get("地区"))
    for f in LIST_FIELDS:
        if not fields[f]:
            fields[f] = _split_people(kv_get(f))

    year = extract_year(fields["date"], kv_get("date"))
    date_val = fields["date"].strip() if fields["date"] else year
    if re.fullmatch(r"(19|20)\d{2}\D*", date_val or ""):
        date_val = year

    intro = panel["intro"] or parse_desc_fallback(detail)

    img_url = list_img
    if not img_url:
        thumb = soup.find(class_=_re_class("myui-content_thumb"))
        it = thumb.find("img") if thumb else None
        if it:
            img_url = it.get("data-original") or it.get("data-src") or it.get("src") or ""
    img_url = clean_url(img_url)
    if img_url:
        img_url = urljoin(sub_url, img_url)

    rec = {
        "name":   real_name,
        "url":    sub_url,
        "info":   default_info or status,
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   " / ".join(fields["导演"]) if fields["导演"] else "",
        "编剧":   fields["编剧"],
        "主演":   fields["主演"],
        "类型":   fields["类型"],
        "地区":   fields["地区"],
        "date":   date_val,
        "date_re": date_val,
        "alias":  "",
        "intro":  intro or "",
        "评分":   {"豆瓣": "", "IMDB": ""},
        "playlist": move_low_priority_lines_to_end(extract_playlists(soup, sub_url)),
    }
    return rec, {"year": year, "fields": fields}


# ============== 去重查找 ==============
def _normalize_name(s):
    if not s:
        return ""
    s = s.translate(str.maketrans("：！？，（）【】", ":!?,()[]"))
    return re.sub(r"\s+", "", s).strip().lower()

def clean_season_one(s):
    return re.sub(r"(?:第[一1]季)$", "", s or "").strip()

def _year_conflict(item, year, group):
    if not year or group not in YEAR_CONFLICT_GROUPS:
        return False
    old_year = extract_year(item.get("date", ""), item.get("date_re", ""))
    return bool(old_year) and abs(int(old_year) - int(year)) > 1

def find_existing_global(data, name, sub_url, prefer_group=None, year="", log=print):
    groups_all = list(ALL_GROUPS)
    norm_sub = normalize_url(sub_url)

    # 1. URL 精确匹配（最可靠）
    if norm_sub:
        for g in groups_all:
            for item in data.get(g, []):
                for k in item.keys():
                    if (k == "url" or re.match(r"^url\d+$", k)) and normalize_url(item.get(k, "")) == norm_sub:
                        if item.get("name", "") != name:
                            log(f"      [URL匹配去重] 已有:「{item.get('name')}」, 抓取:「{name}」")
                        return g, item

    # 2. 名称匹配：先同分类，再其他分类；电影校验年份防止翻拍片误合并
    norm = _normalize_name(name)
    if not norm:
        return None, None
    base = clean_season_one(norm)
    order = ([prefer_group] if prefer_group in groups_all else []) + [g for g in groups_all if g != prefer_group]
    for g in order:
        for item in data.get(g, []):
            en = _normalize_name(item.get("name", ""))
            if not en:
                continue
            eb = clean_season_one(en)
            hit = (en == norm) or (base and eb and base == eb)
            if not hit:
                continue
            if _year_conflict(item, year, g) or _year_conflict(item, year, prefer_group):
                log(f"      [年份冲突] 同名「{item.get('name')}」年份 {item.get('date')} ≠ {year}，视为不同作品")
                continue
            log(f"      [名称去重] 匹配成功：已有「{item.get('name')}」({g}) ↔ 抓取「{name}」")
            return g, item
    return None, None


# ============== 合并到已有记录 ==============
# ============== 枪版 → 高清 升级检测 ==============
QUALITY_RE = re.compile(r"^(HD|FHD|UHD|4K|1080P?|720P?|BD|蓝光|高清|超清)$", re.IGNORECASE)

def extract_quality_label(playlists):
    """从线路的集数名中找出画质标签，如 'HD'；找不到返回空串"""
    for pl in playlists or []:
        for ep in (pl.get("episodes") or {}):
            ep_s = str(ep).strip()
            if QUALITY_RE.match(ep_s):
                return ep_s.upper()
    return ""

def refresh_date_to_today(old_date):
    """
    把 date 的日期部分换成今天，保留后缀（如地区）：
      '2026-09-26(美国)' -> '2026-10-27(美国)'
      '2026'             -> '2026-10-27'
      ''                 -> '2026-10-27'
    """
    today = datetime.now().strftime("%Y-%m-%d")
    old_date = old_date or ""
    suffix = re.sub(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?", "", old_date)
    return today + suffix

def merge_into_existing(existing, rec, sub_url, group, log=print, force_add=False):
    """返回 (status, changed)；force_add=True 时忽略「该分类不允许追加渠道」限制（白名单/用户强制）"""
    new_pls = rec.get("playlist", [])
    serial = group in SERIAL_GROUPS
    playlist = existing.setdefault("playlist", [])
    site_idx = site_playlist_indices(playlist)
    site_set = set(site_idx)
    old_site = [playlist[i] for i in site_idx]
    # 【新增】合并前 jjztq 线路是否含枪版关键字
    old_site_has_tc = any(has_tc_keyword(ep) for pl in old_site for ep in (pl.get("episodes") or {}))
    others = [(i, pl) for i, pl in enumerate(playlist) if i not in site_set]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # —— TC 锁定（显式保护名单，白名单不覆盖） ——
    if old_site and (is_in_tc_lock_list(existing.get("name", "")) or is_in_tc_lock_list(rec["name"])):
        old_tc = any(has_tc_keyword(ep) for pl in old_site for ep in (pl.get("episodes") or {}))
        new_tc = any(has_tc_keyword(ep) for pl in new_pls for ep in pl["episodes"])
        if old_tc and not new_tc:
            return "tc_locked", False

    old_max_all = max([get_max_episode_number(pl.get("episodes", {})) for pl in playlist] or [0])
    other_max = max([get_max_episode_number(pl.get("episodes", {})) for _, pl in others] or [0])
    new_max = max([get_max_episode_number(pl["episodes"]) for pl in new_pls] or [0])
    best_new_eps = max(new_pls, key=lambda pl: get_effective_episode_count(pl["episodes"], group))["episodes"]

    status = "no_change"
    playlist_changed = False
    url_added = not has_site_url_key(existing, sub_url)

    if old_site:
        if playlist_signature(old_site) == playlist_signature(new_pls):
            pass
        elif total_episode_count(new_pls) < total_episode_count(old_site):
            log(f"      [忽略线路] 本次 {total_episode_count(new_pls)} 项 < 已有 {total_episode_count(old_site)} 项，保留原线路")
            status = "decreased"
        else:
            first = site_idx[0]
            remove_indices(playlist, site_idx)
            playlist[first:first] = copy.deepcopy(new_pls)
            playlist_changed = True
            log(f"      [线路更新] {[p['name'] for p in old_site]} -> {[p['name'] for p in new_pls]}")

        if serial and status != "decreased":
            cur = site_playlist_indices(playlist)
            if cur and cur[0] != 0 and new_max > other_max:
                block = [playlist[i] for i in cur]
                remove_indices(playlist, cur)
                playlist[0:0] = block
                playlist_changed = True
                log(f"      [排序调整] {SITE_KEY} 最大集数({new_max}) > 其他渠道({other_max})，已移动至最前")
        _ensure_site_url(existing, sub_url)
    else:
        if group not in ADD_CHANNEL_GROUPS and not force_add:
            return "skip_add", False
        if serial:
            if new_max > other_max:
                pos = 0
            else:
                best_i, best_v = -1, -1
                for i, pl in others:
                    v = get_max_episode_number(pl.get("episodes", {}))
                    if v > best_v:
                        best_i, best_v = i, v
                pos = best_i + 1 if best_i >= 0 else len(playlist)
        else:
            pos = len(playlist)
        if ENABLE_shangxidq_RULE:
            pos = resolve_insert_position_with_shangxidq(playlist, best_new_eps, pos, group, log)
        playlist[pos:pos] = copy.deepcopy(new_pls)
        # 【修复】已存在本站 url 键时复用，避免重复写出指向同一地址的 urlN
        key = _ensure_site_url(existing, sub_url)
        playlist_changed = True
        status = "channel_added"
        log(f"      [新增渠道] {SITE_KEY} 写入 {key}，{len(new_pls)} 条线路插入至第 {pos + 1} 位")

    # —— info ——
    info_changed = False
    old_info = existing.get("info", "")
    if serial and new_max > 0 and (new_max > old_max_all or not old_info):
        cand = make_episode_info(max(new_max, old_max_all), get_episode_unit(group, best_new_eps, old_info))
        if old_info != cand:
            existing["info"] = cand
            info_changed = True
            log(f"      [info更新] 「{old_info}」 -> 「{cand}」")
    elif not serial and not old_info and rec.get("info"):
        existing["info"] = rec["info"]
        info_changed = True
        log(f"      [info补充] 「{rec['info']}」")

    fields_changed = merge_missing_fields(existing, rec, log)
    if not existing.get("image") and rec.get("image"):
        local = download_and_localize_image(rec["image"])
        if local:
            existing["image"] = local
            fields_changed = True
            log(f"      [字段更新] 补充封面: {local}")

    # —— 【新增】枪版 → 高清：本站线路不再含 TC/TS/HC 等关键字时，更新 info 和 date ——
    cur_site = [playlist[i] for i in site_playlist_indices(playlist)]
    cur_site_has_tc = any(has_tc_keyword(ep) for pl in cur_site for ep in (pl.get("episodes") or {}))
    if old_site_has_tc and cur_site and not cur_site_has_tc:
        label = extract_quality_label(cur_site) or extract_quality_label(new_pls)
        if label:
            new_info = f"更新至{label}"
            if existing.get("info") != new_info:
                log(f"      [枪版→高清] info「{existing.get('info', '')}」 -> 「{new_info}」")
                existing["info"] = new_info
                info_changed = True

        old_date = existing.get("date", "")
        new_date = refresh_date_to_today(old_date)
        if new_date != old_date:
            log(f"      [枪版→高清] date「{old_date}」 -> 「{new_date}」")
            existing["date"] = new_date
            fields_changed = True

    # —— 本站线路内部芒果置顶（放在所有排序逻辑之后）——
    if move_mango_within_site(playlist):
        playlist_changed = True
        log(f"      [排序调整] {SITE_KEY} 内「{MANGO_KEYWORD}」线路已置顶")

    changed = playlist_changed or info_changed or fields_changed or url_added
    if status == "decreased":
        return "decreased", changed

    if serial:
        if new_max > old_max_all:
            existing["update"] = now
    elif playlist_changed:
        existing["update"] = now

    if status == "no_change" and changed:
        status = "updated"
    return status, changed


# ============== 处理单个详情页（列表模式 & 单页模式共用） ==============
RESULT_LABELS = {
    "added": "新增", "updated": "更新", "no_change": "无变更",
    "skipped": "规则跳过", "skip_year": "年份跳过", "failed": "失败",
}

def process_detail(data, url, group, list_name="", list_info="", list_img="",
                   header=None, on_block=None):
    """
    抓取并处理一个详情页。
    on_block(reason) -> bool：命中过滤规则时回调，返回 True 表示强制放行（单页交互模式使用）。
    白名单影片：自动放行所有过滤规则（年份/黑名单/集数上限/地区/国产推断/分类不允许追加渠道）。
    返回：added / updated / no_change / skipped / skip_year / failed
    """
    print(header or f"  {list_name or url}  [{list_info}]")
    try:
        rec, meta = parse_subpage(url, list_name, list_info, list_img=list_img)
        real_name = rec.get("name") or list_name
        if not real_name:
            print("    ✗ 无法解析片名，跳过")
            return "failed"
        rec["name"] = real_name
        year = meta["year"]
        filter_regions = FILTER_REGIONS_BY_GROUP.get(group, FILTER_REGIONS)

        whitelisted = is_whitelisted_name(real_name) or is_whitelisted_name(list_name)
        if whitelisted:
            print(f"    ⭐ 白名单命中：「{real_name}」，跳过全部过滤规则")

        def blocked(reason):
            """True=应跳过；白名单或用户强制时返回 False"""
            if whitelisted:
                print(f"    ⭐ 白名单放行（忽略规则：{reason}）")
                return False
            if on_block is not None:
                try:
                    force = bool(on_block(reason))
                except Exception:
                    force = False
                if force:
                    print(f"    ⚠️ 已强制放行（忽略规则：{reason}）")
                    return False
            print(f"    - 跳过：{reason}")
            return True

        # —— 1. 年份 ——
        if (not year and SKIP_IF_YEAR_UNKNOWN) or (year and year not in ALLOWED_YEARS):
            if blocked(f"年份「{year or '未知'}」不在 {sorted(ALLOWED_YEARS)} 内"):
                return "skip_year"

        # —— 2. 黑名单 ——
        bl = next((n for n in (real_name, list_name) if n and is_blacklisted_name(n)), None)
        if bl and blocked(f"名称「{bl}」在黑名单中"):
            return "skipped"
        if any(b in url for b in BLACKLIST_URLS if b) and blocked("URL 在黑名单中"):
            return "skipped"

        # —— 3. 播放源（无法放行：没有可写入的内容） ——
        new_pls = rec["playlist"]
        if not new_pls:
            print("    ✗ 无播放源，跳过")
            return "failed"
        lines_desc = ", ".join("{}({})".format(p["name"], len(p["episodes"])) for p in new_pls)
        print(f"    [线路] {lines_desc}  年份:{year or '未知'}  地区:{rec.get('地区') or '未知'}")

        # —— 4. 集数上限 ——
        max_line = max(len(p["episodes"]) for p in new_pls)
        if group in ("Drama", "Anime") and max_line > MAX_EPISODES:
            if blocked(f"「{real_name}」集数 {max_line} 超过 {MAX_EPISODES} 上限"):
                return "skipped"

        # —— 5. 去重 ——
        matched_group, existing = find_existing_global(
            data, real_name, url, prefer_group=group, year=year, log=print)
        eff_group = matched_group or group
        if existing and matched_group != group:
            print(f"    * 该资源已存在于「{matched_group}」分类，将按「{matched_group}」规则处理")

        # —— 6. 地区 ——
        if existing and eff_group in ("Anime", "Drama", "Movie"):
            print(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
        else:
            region = (rec.get("地区") or "").strip()
            if region_blocked(region, filter_regions):
                if blocked(f"地区为「{region}」，在过滤列表中"):
                    return "skipped"
            elif region in ("", "未知"):
                type_text = " ".join(rec.get("类型", []) or [])
                kw = next((k for k in ["国产", "中国", "大陆", "内地"] if k in type_text), None)
                if kw and blocked(f"地区未知，但类型「{type_text}」含「{kw}」，判定为国产内容"):
                    return "skipped"

        # —— 7. 合并 / 新增 ——
        if existing:
            force_add = False
            if not site_playlist_indices(existing.get("playlist") or []) and eff_group not in ADD_CHANNEL_GROUPS:
                if blocked(f"项目已存在于「{eff_group}」但无 {SITE_KEY} 渠道，且该分类不允许追加渠道"):
                    return "skipped"
                force_add = True
            status, changed = merge_into_existing(existing, rec, url, eff_group, log=print, force_add=force_add)
            saved = save_json(data) if changed else True
            msg = {
                "channel_added": f"    ✅ 更新({eff_group})：已把 {SITE_KEY} 作为新渠道写入",
                "updated":       f"    ✅ 更新({eff_group})：{SITE_KEY} 线路/信息已更新",
                "no_change":     f"    - 无变更({eff_group})",
                "decreased":     f"    - 忽略({eff_group})：抓取集数少于已有集数" + ("（字段已补全）" if changed else ""),
                "tc_locked":     f"    🛡️ [TC锁定跳过] 「{real_name}」原有 {SITE_KEY} 线路含 TC，新抓为非 TC，锁定不更新",
                "skip_add":      f"    - 跳过({eff_group})：项目已存在但无 {SITE_KEY} 渠道，且该分类不允许追加渠道",
            }.get(status, f"    ? 未知状态 {status}")
            print(msg)
            if changed and not saved:
                print("    ⚠️ 本条变更未能写盘（见上方提示）")
            if status in ("channel_added", "updated"):
                return "updated"
            if status == "decreased":
                return "updated" if changed else "no_change"
            if status in ("tc_locked", "skip_add"):
                return "skipped"
            return "no_change"

        rec["image"] = download_and_localize_image(rec.get("image", ""))
        if group in SERIAL_GROUPS:
            ep_cnt = max(get_max_episode_number(p["episodes"]) for p in new_pls)
            if ep_cnt > 0:
                best = max(new_pls, key=lambda p: len(p["episodes"]))["episodes"]
                rec["info"] = make_episode_info(ep_cnt, get_episode_unit(group, best, rec.get("info", "")))
        move_mango_within_site(rec["playlist"])
        data.setdefault(group, []).append(rec)
        if not save_json(data):
            print("    ⚠️ 本条未能写盘（见上方提示）")
        print(f"    ✅ 新增 -> {group} (线路 {len(new_pls)} 条) [真实名称: {real_name}] [URL: {url}]")
        return "added"

    except ConcurrentWriteError:
        raise
    except Exception as e:
        print(f"    ✗ 抓取失败: {e}")
        return "failed"


# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name, seen_urls):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    stats = Counter()
    try:
        items = collect_list_items(list_url)
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        stats["failed"] += 1
        return stats
    print(f"  共发现 {len(items)} 条")

    for idx, (name, info, url, img) in enumerate(items, 1):
        tag = f"  ({idx}/{len(items)}) {name}"
        if url in seen_urls:
            print(f"{tag} [本次运行已处理过，跳过]")
            continue
        seen_urls.add(url)
        if not is_whitelisted_name(name):          # 白名单优先于黑名单
            if is_blacklisted_name(name):
                print(f"{tag} [在名称黑名单中，跳过]")
                continue
            if any(b in url for b in BLACKLIST_URLS if b):
                print(f"{tag} [URL 在黑名单中，跳过: {url}]")
                continue

        result = process_detail(data, url, group, list_name=name, list_info=info,
                                list_img=img, header=f"{tag}  [{info}]")
        stats[result] += 1
        polite_sleep()
    return stats


# ============== 补全模式 ==============
def fill_empty_fields(item, rec):
    changed = False
    for f in ["导演", "编剧", "主演", "类型", "地区", "date", "intro"]:
        if not item.get(f) and rec.get(f):
            item[f] = rec[f]
            changed = True
    if rec.get("image") and not item.get("image"):
        local = download_and_localize_image(rec["image"])
        if local:
            item["image"] = local
            changed = True
    return changed

def backfill_existing(data):
    print(f"\n[补全模式] 扫描已有 {SITE_KEY} 记录中字段缺失的资源 ...")
    total = updated = 0
    for group in ALL_GROUPS:
        for item in data.get(group, []):
            target = next((item.get(k) for k in _url_keys_sorted(item)
                           if item.get(k) and SITE_KEY in item.get(k)), None)
            if not target:
                continue
            if any(item.get(f) for f in ["导演", "主演", "类型", "地区", "intro"]):
                continue
            total += 1
            print(f"  [{group}] 补全: {item.get('name')}  <- {target}")
            try:
                rec, _ = parse_subpage(target, item.get("name", ""), "")
                if fill_empty_fields(item, rec):
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    save_json(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} 地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except ConcurrentWriteError:
                raise
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            polite_sleep()
    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")


# ============== 命令行解析 ==============
def parse_cli():
    global USE_CDP, HEADLESS, FORCE_BROWSER, BROWSER_FALLBACK, AUTO_CLICK_TURNSTILE, MAX_LIST_PAGES
    args = [a.lower().lstrip("-") for a in sys.argv[1:]]
    if "open" in args or "launch" in args:
        launch_chrome_for_cdp()
        sys.exit(0)
    if "cdp" in args:
        USE_CDP = True
        AUTO_CLICK_TURNSTILE = False
        print(">>> [模式] CDP：附着到你手动启动的 Chrome（不会关闭它）")
    if "browser" in args:
        FORCE_BROWSER = True
        print(">>> [模式] 强制浏览器通道")
    if "headless" in args:
        HEADLESS = True
        print(">>> [模式] 无头浏览器")
    if "nobrowser" in args:
        BROWSER_FALLBACK = False
        print(">>> [模式] 禁用浏览器兜底（纯直连）")
    if "click" in args:
        AUTO_CLICK_TURNSTILE = True
    for a in args:
        m = re.match(r"^pages=(\d+)$", a)
        if m:
            MAX_LIST_PAGES = max(1, int(m.group(1)))
            print(f">>> [模式] 每个分类最多翻 {MAX_LIST_PAGES} 页")
    return "backfill" in args


# ============== 主流程 ==============
def main():
    setup_logging()
    is_backfill = parse_cli()
    start_caffeinate()
    acquire_run_lock()
    os.makedirs(IMG_DIR, exist_ok=True)

    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    data = load_existing(JSON_PATH)
    snapshot_backup(JSON_PATH)
    if os.path.exists(JSON_PATH + ".tmp"):
        print(f">>> [提示] 发现残留临时文件 {JSON_PATH}.tmp，可自行检查后删除")

    try:
        _fetcher.start()
        if is_backfill:
            backfill_existing(data)
            print(f"\n补全任务完成! 数据已保存在 {JSON_PATH}")
            return

        seen_urls = set()
        total = Counter()
        for list_url, group, page_name in LIST_PAGES:
            total.update(process_list_page(data, list_url, group, page_name, seen_urls))
        print("\n====================================")
        summary = "，".join(f"{RESULT_LABELS[k]} {total.get(k, 0)} 条" for k in RESULT_LABELS)
        print(f"所有抓取任务完成! {summary}。数据已实时保存在 {JSON_PATH}")
    except ConcurrentWriteError as e:
        print(f"\n⛔ {e}")
    except KeyboardInterrupt:
        print("\n>>> 用户中断（已处理的条目均已实时保存）")
    finally:
        _fetcher.close()
        release_run_lock()

if __name__ == "__main__":
    main()