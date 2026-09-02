# -*- coding: utf-8 -*-
"""
xb6v.com 最新剧集、最新电影、小编推荐、首页 爬取脚本
（升级版 + 防休眠 + 国产/泰国地区过滤(仅分集剧集) + 新格式兼容 + 补全模式 + 6vdy首页抓取 + 评分过滤）
"""

import os
import re
import ssl
import sys
import json
import time
import glob
import shutil
import random
import requests
import platform
import subprocess
import atexit
from urllib.parse import urljoin, urlparse, urlunparse
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:
    from urllib3.util.retry import Retry

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from bs4 import BeautifulSoup
from datetime import datetime

# ================= 防止系统休眠控制 =================
_caffeinate_proc = None

def start_caffeinate():
    """启动 caffeinate 以防止系统休眠 (仅限 macOS)"""
    global _caffeinate_proc
    if platform.system() == 'Darwin':
        try:
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-idmu"])
            print(">>> [系统] 已开启防休眠模式 (caffeinate)")
        except Exception as e:
            print(f">>> [系统] 无法启动 caffeinate: {e}")

def stop_caffeinate():
    """停止 caffeinate"""
    global _caffeinate_proc
    if _caffeinate_proc:
        try:
            _caffeinate_proc.terminate()
            print(">>> [系统] 已关闭防休眠模式")
        except Exception as e:
            print(f">>> [系统] 关闭 caffeinate 时出错: {e}")

atexit.register(stop_caffeinate)

# ============== 配置 ==============
BASE_URL    = "https://www.xb6v.com/qian50m.html"
HOME_URL_6VDY = "https://www.xb6v.com/"
JSON_PATH   = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
BLACKLIST_URL_PATH = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json"
PLAYLIST_NAME = "xb6v"
REQUEST_TIMEOUT = (10, 25)
SLEEP_BETWEEN  = 1.0

# ============ 数据安全相关配置 ============
BACKUP_DIR = os.path.join(os.path.dirname(JSON_PATH), "backup")
BAK_FILE = JSON_PATH + ".bak"
REJECTED_FILE = JSON_PATH + ".rejected.json"
MAX_BACKUPS = 20                 # backup/ 目录里最多保留多少份启动快照
ALLOW_SHRINK_RATIO = 0.90        # 新数据条目数不得低于基线的 90%，否则拒绝写盘
SHRINK_GUARD_MIN_ITEMS = 20      # 基线条目少于这个数时不启用缩水保护
ALLOW_FRESH_START = False        # 只有确实想从零开始建库时才改 True

_BASELINE_TOTAL = 0              # 启动时加载到的条目总数（缩水保护基线）
_LOAD_OK = False                 # 是否成功加载了初始数据（未成功则禁止任何写盘）

BLACKLIST_NAMES = ["乘风2026", "吞噬星空", "遮天 动画版"]
WHITELIST_NAMES = [
    "镖人 第二季"
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "China"]

MIN_RATING = 6.0
MIN_RATING_7 = 7.0

# ============== 镜像站识别 ==============
MIRROR_DOMAINS = ("xb6v", "6vdy", "66ss", "6v520", "66s.cc")
MIRROR_HOSTS = [
    "www.xb6v.com",
    "www.6vdy.org",
    "www.66ss.org",
    "www.6v520.tv",
]

PROXIES = None
MAX_ATTEMPTS_PER_URL = 3
BACKOFF_BASE = 1.8
VERIFY_SSL_STRICT_FIRST = True

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Referer": BASE_URL,
}

# ============== TLS / Session 构建 ==============
class TLSAdapter(HTTPAdapter):
    def __init__(self, ssl_context=None, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        if self._ssl_context is not None:
            kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        if self._ssl_context is not None:
            kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(*args, **kwargs)

def _build_ssl_context(loose=False):
    ctx = ssl.create_default_context()
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except Exception:
        pass

    if loose:
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            try:
                ctx.set_ciphers("ALL:@SECLEVEL=1")
            except ssl.SSLError:
                pass
        legacy_flag = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        try:
            ctx.options |= legacy_flag
        except Exception:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        except Exception:
            pass
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx

def count_items(data: dict) -> int:
    if not isinstance(data, dict):
        return 0
    return sum(len(v) for v in data.values() if isinstance(v, list))

def _read_json_strict(path: str) -> dict:
    """严格读取：空文件 / 非 dict / 解析失败 都抛异常"""
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    if not txt.strip():
        raise ValueError("文件内容为空（0 字节或全空白）")
    data = json.loads(txt)
    if not isinstance(data, dict):
        raise ValueError(f"顶层结构不是 dict，而是 {type(data).__name__}")
    return data

def _backup_candidates() -> list[str]:
    cands = [BAK_FILE]
    try:
        snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")), reverse=True)
        cands.extend(snaps)
    except Exception:
        pass
    return cands

def snapshot_backup(path: str):
    """每次启动把当前有效文件另存一份时间戳快照，先清理非今日的旧备份，只保留今日备份"""
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        # 获取今日日期 YYYYMMDD
        today_ts = time.strftime("%Y%m%d")
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"OVideos_{ts}.json")

        # --------新增逻辑：删除所有不是今天日期的备份文件--------
        snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")))
        for fpath in snaps:
            fname = os.path.basename(fpath)
            # 匹配 OVideos_20260827_101451.json
            m = re.match(r"OVideos_(\d{8})_\d{6}\.json", fname)
            if m:
                file_date = m.group(1)
                if file_date != today_ts:
                    try:
                        os.remove(fpath)
                        print(f">>> [备份清理] 删除过期备份: {fname}")
                    except Exception as e:
                        print(f">>> [备份清理] 删除失败 {fname}: {e}")

        shutil.copy2(path, dst)
        print(f">>> [备份] 启动快照已保存: {dst}")

        # 原来的 MAX_BACKUPS 数量轮转逻辑不再需要，直接注释掉
        # snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "OVideos_*.json")))
        # if len(snaps) > MAX_BACKUPS:
        #     for old in snaps[:len(snaps) - MAX_BACKUPS]:
        #         try:
        #             os.remove(old)
        #         except Exception:
        #             pass
    except Exception as e:
        print(f">>> [备份] 创建启动快照失败: {e}")


def _build_session(loose_tls=False):
    s = requests.Session()
    s.headers.update(HEADERS)
    if PROXIES:
        s.proxies.update(PROXIES)

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504, 520, 521, 522, 524),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adapter = TLSAdapter(
        ssl_context=_build_ssl_context(loose=loose_tls),
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=20,
    )
    s.mount("https://", adapter)
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

SESSION_STRICT = _build_session(loose_tls=False)
SESSION_LOOSE  = _build_session(loose_tls=True)

_WORKING_HOST = None
_DEAD_HOSTS = set()

# ============== 工具函数 ==============
def load_blacklist_urls():
    if not os.path.exists(BLACKLIST_URL_PATH):
        return set()
    try:
        with open(BLACKLIST_URL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.keys())
    except Exception as e:
        print(f">>> [黑名单URL] 读取失败: {e}")
        return set()

BLACKLIST_URLS = load_blacklist_urls()

def _swap_host(url, new_host, scheme=None):
    p = urlparse(url)
    return urlunparse((
        scheme or p.scheme or "https",
        new_host,
        p.path or "/",
        p.params,
        p.query,
        p.fragment,
    ))

def _host_of(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def _candidate_urls(url):
    p = urlparse(url)
    origin_host = p.netloc.lower()
    ordered_hosts = []

    if _WORKING_HOST and _WORKING_HOST not in ordered_hosts:
        ordered_hosts.append(_WORKING_HOST)
    if origin_host and origin_host not in ordered_hosts:
        ordered_hosts.append(origin_host)
    for h in MIRROR_HOSTS:
        if h not in ordered_hosts:
            ordered_hosts.append(h)

    cands = []
    for h in ordered_hosts:
        if h not in _DEAD_HOSTS:
            cands.append(_swap_host(url, h, scheme="https"))
    for h in ordered_hosts:
        if h not in _DEAD_HOSTS:
            cands.append(_swap_host(url, h, scheme="http"))

    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

def _do_request(session, url, verify, is_binary):
    resp = session.get(url, timeout=REQUEST_TIMEOUT, verify=verify, allow_redirects=True)
    resp.raise_for_status()
    if is_binary:
        return resp.content
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text

def fetch_ex(url, is_binary=False, allow_mirror=True):
    global _WORKING_HOST

    candidates = _candidate_urls(url) if allow_mirror else [url]
    last_err = None

    for cand in candidates:
        host = _host_of(cand)
        plans = []
        if VERIFY_SSL_STRICT_FIRST:
            plans.append((SESSION_STRICT, True))
        plans.append((SESSION_STRICT, False))
        plans.append((SESSION_LOOSE, False))

        for sess, verify in plans:
            for attempt in range(1, MAX_ATTEMPTS_PER_URL + 1):
                try:
                    content = _do_request(sess, cand, verify, is_binary)
                    if host and host != _WORKING_HOST:
                        _WORKING_HOST = host
                        if cand != url:
                            print(f"    [网络] 已切换到可用地址: {cand}")
                    return content, cand
                except requests.exceptions.SSLError as e:
                    last_err = e
                    break
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.ChunkedEncodingError) as e:
                    last_err = e
                    if attempt < MAX_ATTEMPTS_PER_URL:
                        wait = (BACKOFF_BASE ** attempt) + random.uniform(0, 0.8)
                        print(f"    [网络] 连接异常({attempt}/{MAX_ATTEMPTS_PER_URL})，{wait:.1f}s 后重试 -> {cand}")
                        time.sleep(wait)
                    else:
                        print(f"    [网络] 连接失败，放弃该方案 -> {cand}")
                except requests.exceptions.HTTPError as e:
                    last_err = e
                    code = getattr(e.response, "status_code", None)
                    if code in (403, 404, 410):
                        break
                    if attempt < MAX_ATTEMPTS_PER_URL:
                        time.sleep((BACKOFF_BASE ** attempt))
                except Exception as e:
                    last_err = e
                    break

        if host and host not in _DEAD_HOSTS and host != _WORKING_HOST:
            _DEAD_HOSTS.add(host)

    raise RuntimeError(f"所有候选地址均请求失败: {url} | 最后错误: {last_err}")

def fetch(url, is_binary=False):
    content, _ = fetch_ex(url, is_binary=is_binary)
    return content

def normalize_link_host(link, target_host):
    if not link or not target_host:
        return link
    h = _host_of(link)
    if not h or h == target_host:
        return link
    if any(d in h for d in MIRROR_DOMAINS):
        return _swap_host(link, target_host, scheme="https")
    return link

def get_max_rating(rating_dict):
    if not isinstance(rating_dict, dict):
        return None
    vals = []
    for key in ("豆瓣", "IMDB"):
        v = rating_dict.get(key, "")
        if v in ("", None):
            continue
        try:
            f = float(v)
        except (ValueError, TypeError):
            continue
        if f > 0:
            vals.append(f)
    return max(vals) if vals else None

def update_movie_quality_info_if_needed(existing, new_6vdy_episodes):
    return False

def normalize_text(s):
    if not s:
        return ""
    entity_map = {
        "&middot": "·", "&mdash": "—", "&ndash": "–",
        "&ldquo": "“", "&rdquo": "”", "&lsquo": "‘", "&rsquo": "’",
        "&iacute": "í", "&nbsp": " ", "&lrm": "", "&rlm": "",
    }
    for ent, ch in entity_map.items():
        s = s.replace(ent + ";", ch).replace(ent + "；", ch)
    s = s.replace("\u200e", "").replace("\u200f", "")
    s = s.replace("・", "·").replace("‧", "·").replace("·", "·")
    s = s.replace("\xa0", " ")
    s = re.sub(r"[，；;]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·•")
    return s

def num_to_chinese(num_str):
    try:
        num = int(num_str)
    except ValueError:
        return num_str

    chinese_digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    if num < 10:
        return chinese_digits[num]
    elif num == 10:
        return "十"
    elif num < 20:
        return f"十{chinese_digits[num % 10]}"
    elif num < 100:
        tens = num // 10
        ones = num % 10
        return f"{chinese_digits[tens]}十" + (chinese_digits[ones] if ones != 0 else "")
    return num_str

def split_name_info(raw_title):
    raw_title = raw_title.strip()
    base_name = raw_title
    base_info = ""

    bracket_match = re.search(r"^(.*?)[\[［](.*?)[\]］]$", raw_title)
    if bracket_match:
        base_name = bracket_match.group(1).strip()
        base_info = bracket_match.group(2).strip()
    else:
        season_match = re.search(r"^(.*?)\s+((?:第[0-9一二三四五六七八九十百\-]+季)(?:全)?)$", raw_title)
        if season_match:
            base_name = season_match.group(1).strip()
            base_info = season_match.group(2).strip()

    def replace_season(match):
        prefix = match.group(1)
        num = match.group(2)
        suffix = match.group(3)
        return f"{prefix}{num_to_chinese(num)}{suffix}"

    base_name = re.sub(r"(第)(\d+)(季)", replace_season, base_name)
    base_info = re.sub(r"(第)(\d+)(季)", replace_season, base_info)

    if not base_info:
        return base_name, ""

    if base_info == "全集":
        return base_name, "全集"
    elif base_info.endswith("季全"):
        if re.search(r"[\-\d~至]", base_info):
            return base_name, base_info
        else:
            season_clean = base_info[:-1]
            name = f"{base_name} {season_clean}"
            return name, base_info
    elif base_info.endswith("季"):
        name = f"{base_name} {base_info}"
        info = ""
        return name, info

    return base_name, base_info

def safe_filename(url):
    return os.path.basename(url.split("?")[0])

def should_update_date(old_date, new_date):
    """
    判断是否应该用 new_date 替换 old_date：
    1. 原 date 为空，直接更新。
    2. 新年份 < 旧年份（抓到了旧季年份），拒绝替换。
    3. 新年份 > 旧年份（资源年份升级），允许替换。
    4. 年份相同时，如果新日期更详细（长度更长），允许替换。
    """
    if not new_date:
        return False
    if not old_date:
        return True

    old_str = str(old_date).strip()
    new_str = str(new_date).strip()

    # 正则提取 4 位年份 (19xx / 20xx)
    old_m = re.search(r'(19\d{2}|20\d{2})', old_str)
    new_m = re.search(r'(19\d{2}|20\d{2})', new_str)

    if old_m and new_m:
        old_year = int(old_m.group(1))
        new_year = int(new_m.group(1))
        if new_year < old_year:
            return False
        if new_year > old_year:
            return True
        return len(new_str) > len(old_str)

    # 无法提取年份时的兜底逻辑
    return len(new_str) > len(old_str)

# ============== 播放列表提取 ==============
def extract_episodes(soup, base_url=BASE_URL, host_normalize_to=None):
    for widget in soup.select("div.widget.box.row"):
        h3 = widget.find("h3")
        if h3 and "播放地址（无需安装插件" in h3.get_text():
            eps = {}
            for a in widget.select("a.lBtn[href]"):
                href = a["href"]
                if "DownSys/play" in href:
                    ep_name = a.get_text(strip=True) or a.get("title", "").strip()
                    if ep_name:
                        full = urljoin(base_url, href)
                        if host_normalize_to:
                            full = normalize_link_host(full, host_normalize_to)
                        eps[ep_name] = full
            return eps
    return {}

# ============== 旧格式字段解析正则 ==============
FIELD_PATTERNS = {
    "译名":     r"[◎®@]\s*译\s*名\s*[:：]?\s*(.+)",
    "片名":     r"[◎®@]\s*片\s*名\s*[:：]?\s*(.+)",
    "年代":     r"[◎®@]\s*年\s*代\s*[:：]?\s*(.+)",
    "产地":     r"[◎®@]\s*产\s*地\s*[:：]?\s*(.+)",
    "类别":     r"[◎®@]\s*类\s*别\s*[:：]?\s*(.+)",
    "上映":     r"[◎®@]\s*上映日期\s*[:：]?\s*(.+)",
    "IMDb评分": r"[◎®@]\s*IMDb评分\s*[:：]?\s*(.+)",
    "豆瓣评分": r"[◎®@]\s*豆瓣评分\s*[:：]?\s*(.+)",
    "导演":     r"[◎®@]\s*导\s*演\s*[:：]?\s*(.+)",
    "编剧":     r"[◎®@]\s*编\s*剧\s*[:：]?\s*(.+)",
    "主演":     r"[◎®@]\s*(?:主\s*演|演\s*员)\s*[:：]?\s*(.+)",
    "简介":     r"[◎®@]\s*简\s*介\s*[:：]?\s*(.*)",
}

def parse_post_lines(post_div):
    for br in post_div.find_all("br"):
        br.replace_with("\n")
    raw = post_div.get_text("\n")
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip().strip('"').strip("'").strip()
        if ln:
            lines.append(ln)
    return lines

def match_field(lines, pattern):
    field_starter = re.compile(r"^[◎®@]")
    for i, ln in enumerate(lines):
        m = re.search(pattern, ln)
        if m:
            value = m.group(1).strip()
            j = i + 1
            while (not value) and j < len(lines) and not field_starter.match(lines[j]):
                value = lines[j].strip()
                j += 1
            return value, i, j
    return "", -1, -1

def collect_multi(lines, start_idx):
    field_starter = re.compile(r"^[◎®@]")
    out = []
    for k in range(start_idx + 1, len(lines)):
        if field_starter.match(lines[k]):
            break
        out.append(lines[k].strip())
    return out

def extract_intro(post):
    for p in post.find_all("p"):
        for br in p.find_all("br"):
            br.replace_with("\n")
        raw = p.get_text("\n")
        if not re.search(r"[◎®@]\s*简\s*介", raw):
            continue
        lines = [ln.strip().strip('"').strip("'").strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln and not re.match(r"^[◎®@]\s*简\s*介", ln)]
        if lines:
            return " ".join(lines)
        nxt = p.find_next_sibling()
        while nxt:
            if nxt.name == "p":
                t = re.sub(r"\s+", " ", nxt.get_text(" ", strip=True)).strip()
                if t and t not in (".", "•"):
                    return t
            nxt = nxt.find_next_sibling()
        break
    return ""

def parse_score(s):
    if not s:
        return ""
    m = re.match(r"\s*([\d.]+)\s*/\s*10", s)
    if not m:
        return ""
    val = m.group(1)
    try:
        if float(val) == 0:
            return ""
    except ValueError:
        return ""
    return val

def download_and_localize_image(img_url):
    if not img_url:
        return ""
    fn = safe_filename(img_url)
    local_path = os.path.join(IMG_DIR, fn)
    if not os.path.exists(local_path):
        try:
            content = fetch(img_url, is_binary=True)
            os.makedirs(IMG_DIR, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            print(f"  [图片] 已下载 -> {fn}")
        except Exception as e:
            print(f"  [图片下载失败] {img_url}: {e}")
            return ""
    return fn

# ============== 新格式解析 ==============
JUNK_LINE_RE = re.compile(r"^[\s•·.。…\-—=\$~@®◎\u3000]*$")
INTRO_STOP_RE = re.compile(
    r"(磁\s*力|下载地址|【下载|下载|https?://|ftp://|magnet|ed2k|迅雷|thunder|\.mp4|\.mkv|BT类|本站推荐|播放地址)",
    re.I,
)

def parse_people_line(value):
    parts = re.split(r"[/、]", value)
    out, seen = [], set()
    for p in parts:
        p = normalize_text(p)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out

def parse_new_format(lines, h1_name):
    result = {
        "info": "", "alias": "", "导演": "", "编剧": [], "主演": [],
        "类型": [], "地区": "", "date": "", "intro": "", "评分": {"豆瓣": ""},
    }
    youming = ""
    title_alias = ""
    title_found = False
    intro_started = False
    intro_parts = []

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue

        if intro_started:
            if INTRO_STOP_RE.search(ln):
                break
            if JUNK_LINE_RE.match(ln):
                continue
            intro_parts.append(ln)
            continue

        if re.search(r"剧情简介\s*$", ln):
            intro_started = True
            continue

        if JUNK_LINE_RE.match(ln):
            continue

        m = re.match(r"^又\s*名\s*[:：]\s*(.+)$", ln)
        if m:
            youming = normalize_text(m.group(1))
            continue
        m = re.match(r"^译\s*名\s*[:：]\s*(.+)$", ln)
        if m:
            if not youming:
                youming = normalize_text(m.group(1))
            continue
        m = re.match(r"^导\s*演\s*[:：]\s*(.+)$", ln)
        if m:
            ppl = parse_people_line(m.group(1))
            result["导演"] = ppl[0] if ppl else ""
            continue
        m = re.match(r"^编\s*剧\s*[:：]\s*(.+)$", ln)
        if m:
            result["编剧"] = parse_people_line(m.group(1))
            continue
        m = re.match(r"^(?:主\s*演|演\s*员)\s*[:：]\s*(.+)$", ln)
        if m:
            result["主演"] = parse_people_line(m.group(1))
            continue
        m = re.match(r"^类\s*型\s*[:：]\s*(.+)$", ln)
        if m:
            result["类型"] = [t for t in re.split(r"[\s/、,，]+", normalize_text(m.group(1))) if t]
            continue
        m = re.match(r"^(?:制片国家/地区|制片国家|国家/地区|产\s*地|地\s*区|国\s*家)\s*[:：]\s*(.+)$", ln)
        if m:
            result["地区"] = normalize_text(m.group(1))
            continue
        m = re.match(r"^上映日期\s*[:：]\s*(.+)$", ln)
        if m:
            result["date"] = normalize_text(m.group(1))
            continue
        m = re.match(r"^豆瓣评分\s*[:：]\s*(.+)$", ln)
        if m:
            result["评分"]["豆瓣"] = parse_score(m.group(1))
            continue
        m = re.match(r"^IMDb评分\s*[:：]\s*(.+)$", ln)
        if m:
            sc = parse_score(m.group(1))
            if sc:
                result["评分"]["IMDB"] = sc
            continue

        if re.match(r"^(?:语\s*言|片\s*长|单集片长|IMDb|集\s*数|首\s*播|季\s*数|官方网站|资\s*源|状\s*态)\s*[:：]", ln):
            continue

        if not title_found:
            work = ln
            ym = re.search(r"[（(](\d{4})[）)]", ln)
            if ym:
                result["info"] = ym.group(1)
                work = ln[:ym.start()].strip()
                after_year = ln[ym.end():]
                m2 = re.search(r"又\s*名\s*[:：]\s*(.+)$", after_year)
                if m2 and not youming:
                    youming = normalize_text(m2.group(1))
            else:
                m2 = re.search(r"^(.*?)\s*又\s*名\s*[:：]\s*(.+)$", ln)
                if m2:
                    work = m2.group(1).strip()
                    if not youming:
                        youming = normalize_text(m2.group(2))
            ali = work
            if h1_name:
                ali = work.replace(h1_name, "", 1).strip()
            title_alias = ali.strip(" /:：·").strip()
            title_found = True
            continue

    if youming:
        result["alias"] = youming
    elif title_alias:
        result["alias"] = title_alias

    intro_text = " ".join(intro_parts).strip()
    intro_text = re.sub(r"^[\s！!·•．.　]+", "", intro_text)
    intro_text = normalize_text(intro_text)
    result["intro"] = intro_text

    return result

# ============== 子页面解析 ==============
def parse_subpage(sub_url, default_name, default_info):
    html, eff_url = fetch_ex(sub_url)
    soup = BeautifulSoup(html, "lxml")

    origin_host = _host_of(sub_url) or MIRROR_HOSTS[0]

    h1 = soup.select_one(".article_container h1")
    raw_title = h1.get_text(strip=True) if h1 else default_name
    name, info = split_name_info(raw_title)
    if not name:
        name = default_name
    if not info:
        info = default_info

    post = soup.select_one("#post_content")
    if not post:
        raise RuntimeError(f"子页面没有 #post_content: {eff_url}")

    intro_text = extract_intro(post)

    img_url = ""
    img_tag = post.find("img")
    if img_tag and img_tag.get("src"):
        img_url = urljoin(eff_url, img_tag["src"])

    lines = parse_post_lines(post)

    def gv(key):
        v, _, _ = match_field(lines, FIELD_PATTERNS[key])
        return normalize_text(v)

    yi_ming   = gv("译名")
    pian_ming = gv("片名")
    chan_di   = gv("产地")
    lei_bie   = gv("类别")
    shang_ying = gv("上映")
    imdb_raw  = gv("IMDb评分")
    douban_raw = gv("豆瓣评分")

    def collect_people(field_key):
        v, i, _ = match_field(lines, FIELD_PATTERNS[field_key])
        people = []
        if v:
            people.append(normalize_text(v))
        if i >= 0:
            for ex in collect_multi(lines, i):
                ex = normalize_text(ex)
                if ex:
                    people.append(ex)
        seen, out = set(), []
        for p in people:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    director_list = collect_people("导演")
    writer_list   = collect_people("编剧")
    actor_list    = collect_people("主演")
    director = director_list[0] if director_list else ""

    imdb_score   = parse_score(imdb_raw)
    douban_score = parse_score(douban_raw)

    alias_parts = []
    if pian_ming:
        alias_parts.append(pian_ming)
    if yi_ming:
        alias_parts.append(yi_ming)
    alias_str = " / ".join(alias_parts) if alias_parts else ""

    types = []
    if lei_bie:
        types = [t for t in re.split(r"[\s/、,，]+", lei_bie) if t]

    rating = {"豆瓣": douban_score if douban_score else ""}
    if imdb_score:
        rating["IMDB"] = imdb_score

    old_is_empty = (not director and not writer_list and not actor_list
                    and not types and not chan_di)
    if old_is_empty:
        nf = parse_new_format(lines, name)
        print("      [新格式解析] 检测到旧版字段为空，已启用新版页面解析逻辑")
        if nf["导演"]:
            director = nf["导演"]
        if nf["编剧"]:
            writer_list = nf["编剧"]
        if nf["主演"]:
            actor_list = nf["主演"]
        if nf["类型"]:
            types = nf["类型"]
        if nf["地区"]:
            chan_di = nf["地区"]
        if nf["date"]:
            shang_ying = nf["date"]
        if not alias_str and nf["alias"]:
            alias_str = nf["alias"]
        if not intro_text and nf["intro"]:
            intro_text = nf["intro"]
        if nf["info"]:
            info = nf["info"]
        if not rating.get("豆瓣") and nf["评分"].get("豆瓣"):
            rating["豆瓣"] = nf["评分"]["豆瓣"]
        if not rating.get("IMDB") and nf["评分"].get("IMDB"):
            rating["IMDB"] = nf["评分"]["IMDB"]

    episodes = extract_episodes(soup, base_url=eff_url, host_normalize_to=origin_host)
    playlist = []
    if episodes:
        playlist.append({"name": PLAYLIST_NAME, "episodes": episodes})

    return {
        "name":   name,
        "url":    sub_url,
        "info":   info,
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   director,
        "编剧":   writer_list,
        "主演":   actor_list,
        "类型":   types,
        "地区":   chan_di,
        "date":   shang_ying,
        "alias":  alias_str,
        "intro":  intro_text or "",
        "评分":   rating,
        "playlist": playlist,
    }

# ============== JSON 读写与核心逻辑 ==============
def load_existing(path: str) -> dict:
    global _BASELINE_TOTAL, _LOAD_OK
    main_exists = os.path.exists(path)
    main_size = os.path.getsize(path) if main_exists else -1

    if main_exists and main_size > 0:
        try:
            data = _read_json_strict(path)
            _BASELINE_TOTAL = count_items(data)
            _LOAD_OK = True
            print(f">>> [读取] 主文件正常: {path} ({main_size/1024:.1f} KB, {_BASELINE_TOTAL} 条)")
            return data
        except Exception as e:
            print(f"\n❌ [严重] 主数据文件损坏，无法解析: {e}")
    elif main_exists:
        print(f"\n❌ [严重] 主数据文件为 0 字节: {path}")

    # 尝试从备份恢复
    if main_exists:
        for cand in _backup_candidates():
            if not os.path.exists(cand) or os.path.getsize(cand) == 0:
                continue
            try:
                data = _read_json_strict(cand)
            except Exception as e:
                continue
            n = count_items(data)
            _BASELINE_TOTAL = n
            _LOAD_OK = True
            print(f"✅ [恢复] 已从备份恢复数据: {cand} ({n} 条)")
            save_json(data, force=True, quiet=False)
            return data

        if not ALLOW_FRESH_START:
            print("\n" + "!" * 70)
            print("脚本已终止：为防止用空数据覆盖你的历史库，本次不会写入任何内容。")
            print("请从备份恢复可用的 JSON 后再重试。")
            print("!" * 70 + "\n")
            sys.exit(1)
        _BASELINE_TOTAL = 0
        _LOAD_OK = True
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

    _BASELINE_TOTAL = 0
    _LOAD_OK = True
    return {"Movie": [], "Drama": [], "Show": [], "Anime": []}

def save_json(data: dict, force: bool = False, quiet: bool = True) -> bool:
    global _BASELINE_TOTAL
    if not _LOAD_OK:
        print("  [拒绝保存] 初始数据未成功加载，禁止写盘")
        return False
    if not isinstance(data, dict):
        return False

    total = count_items(data)
    if (not force) and _BASELINE_TOTAL >= SHRINK_GUARD_MIN_ITEMS and total < _BASELINE_TOTAL * ALLOW_SHRINK_RATIO:
        print(f"\n  ⛔ [拒绝保存] 条目数异常缩水：{_BASELINE_TOTAL} -> {total} (低于 {ALLOW_SHRINK_RATIO:.0%} 阈值)")
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

def _url_path(url):
    if not url:
        return ""
    try:
        p = urlparse(url).path
    except Exception:
        return ""
    return p.rstrip("/").lower()

def _is_mirror(url):
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(d in host for d in MIRROR_DOMAINS)

def find_existing_global(data, name, sub_url):
    if sub_url:
        sub_path = _url_path(sub_url)
        sub_is_mirror = _is_mirror(sub_url)

        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                existing_urls = {
                    item.get(k) for k in item.keys()
                    if k == "url" or re.match(r"^url\d+$", k)
                }
                if sub_url in existing_urls:
                    return group, item

        if sub_is_mirror and sub_path:
            for group in ["Movie", "Drama", "Show", "Anime"]:
                for item in data.get(group, []):
                    for k in item.keys():
                        if k == "url" or re.match(r"^url\d+$", k):
                            u = item.get(k, "")
                            if _is_mirror(u) and _url_path(u) == sub_path:
                                return group, item

    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            if item.get("name") == name:
                return group, item

    return None, None

def extract_max_episodes_from_info(info_str):
    if not info_str:
        return 0
    match = re.findall(r'(\d+)', info_str)
    return int(match[-1]) if match else 0

def get_real_episode_count(episodes):
    """
    计算真实集数：
    - 优先解析 SxxExx 格式，取最新季（最大S）的最大集号
    - 优先解析 第X季第Y集 格式
    - 常规集名提取最大集编号，无数字退回 len()
    """
    if not episodes:
        return 0

    # 1. 匹配 SxxExx
    se_pairs = []
    for k in episodes.keys():
        m = re.search(r'S(\d+)E(\d+)', str(k), re.IGNORECASE)
        if m:
            se_pairs.append((int(m.group(1)), int(m.group(2))))
    if se_pairs:
        max_season = max(s for s, e in se_pairs)
        max_ep = max(e for s, e in se_pairs if s == max_season)
        return max_ep

    # 2. 匹配 第X季第Y集
    season_ep_pairs = []
    for k in episodes.keys():
        m = re.search(r'第\s*(\d+)\s*季.*?第\s*(\d+)\s*[集期话話]', str(k))
        if m:
            season_ep_pairs.append((int(m.group(1)), int(m.group(2))))
    if season_ep_pairs:
        max_season = max(s for s, e in season_ep_pairs)
        max_ep = max(e for s, e in season_ep_pairs if s == max_season)
        return max_ep

    # 3. 常规提取
    max_num = 0
    for k in episodes.keys():
        m = re.search(r'(\d+)\s*[集期话話]', str(k))
        if not m:
            m = re.search(r'第\s*(\d+)', str(k))
        if not m:
            m = re.search(r'(\d+)', str(k))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num if max_num > 0 else len(episodes)

def has_episode_concept(episodes):
    if not episodes:
        return False
    if len(episodes) >= 3:
        return True
    for key in episodes.keys():
        key_str = str(key)
        if "集" in key_str or "期" in key_str or "话" in key_str or "話" in key_str:
            return True
        if re.search(r"S\d+E\d+", key_str, re.IGNORECASE):
            return True
    return False

def only_6vdy_hits_blacklist_url(existing, blacklist_urls, new_pl=None):
    if not blacklist_urls:
        return False

    for k, v in existing.items():
        if (k == "url" or re.match(r"^url\d+$", k)) and v:
            if "xb6v" in v and v in blacklist_urls:
                print(f"      [黑名单命中] 6vdy 字段「{k}」的 URL 在黑名单中：{v}")
                return True

    for pl in existing.get("playlist", []):
        if pl.get("name") != PLAYLIST_NAME:
            continue
        eps = pl.get("episodes", {})
        if isinstance(eps, dict):
            for ep_name, ep_url in eps.items():
                if ep_url in blacklist_urls:
                    print(f"      [黑名单命中] 6vdy 渠道的集「{ep_name}」URL 在黑名单中：{ep_url}")
                    return True

    if new_pl and new_pl.get("name") == PLAYLIST_NAME:
        eps = new_pl.get("episodes", {})
        if isinstance(eps, dict):
            for ep_name, ep_url in eps.items():
                if ep_url in blacklist_urls:
                    print(f"      [黑名单命中] 6vdy 新抓取的集「{ep_name}」URL 在黑名单中：{ep_url}")
                    return True

    return False

def update_info_field_if_needed(existing, new_playlist, old_vdy_cnt):
    if not new_playlist:
        return False

    if only_6vdy_hits_blacklist_url(existing, BLACKLIST_URLS):
        print(f"      [info字段跳过] 6vdy 渠道命中黑名单 URL")
        return False

    vdy_pl = next((pl for pl in new_playlist if pl.get("name") == PLAYLIST_NAME), None)
    if vdy_pl is None:
        return False

    eps = vdy_pl.get("episodes", {})
    if not has_episode_concept(eps):
        return False

    Y = get_real_episode_count(eps)
    old_info = existing.get("info", "")
    X = extract_max_episodes_from_info(old_info)

    # 统计其他渠道最大集数
    max_other = 0
    max_other_name = ""
    for pl in new_playlist:
        if pl.get("name") == PLAYLIST_NAME:
            continue
        eps_other = pl.get("episodes", {})
        cnt = get_real_episode_count(eps_other) if isinstance(eps_other, dict) else 0
        if cnt > max_other:
            max_other = cnt
            max_other_name = pl.get("name", "")

    # 单渠道场景
    if len(new_playlist) == 1:
        if Y > 0:
            new_info = f"更新至第{Y}集"
            if existing.get("info") != new_info:
                existing["info"] = new_info
                print(f"      ✅[info字段更新] 唯一渠道 6vdy，集数 {Y}，info: 「{old_info}」 -> 「{new_info}」")
                return True
        return False

    # 多渠道场景：抓到的最大集数严格大于其他所有渠道的最大集数
    if Y > max_other and Y > 0:
        new_info = f"更新至第{Y}集"
        if existing.get("info") != new_info:
            existing["info"] = new_info
            print(f"      ✅[info字段更新] 6vdy 新集数 {Y} > 其他渠道最大集数 {max_other}（渠道「{max_other_name}」），info: 「{old_info}」 -> 「{new_info}」")
            return True
    else:
        print(f"      [info字段跳过] 6vdy 新集数 {Y} 未大于其他渠道最大集数 {max_other}，保持原 info「{old_info}」")
        return False

def get_max_other_playlist_ep_count(playlist):
    max_cnt = 0
    for pl in playlist:
        if pl.get("name") == PLAYLIST_NAME:
            continue
        eps = pl.get("episodes", {})
        cnt = get_real_episode_count(eps)
        if cnt > max_cnt:
            max_cnt = cnt
    return max_cnt

def insert_6vdy_playlist(playlist, new_pl, existing):
    vdy_eps = new_pl.get("episodes", {})
    vdy_cnt = get_real_episode_count(vdy_eps)
    max_other = get_max_other_playlist_ep_count(playlist)

    hit_black = only_6vdy_hits_blacklist_url(existing, BLACKLIST_URLS, new_pl)
    if hit_black:
        print(f"      [排序规则] 6vdy 命中黑名单 URL，禁用置顶")
    elif vdy_cnt > max_other:
        playlist.insert(0, new_pl)
        print(f"      [排序规则] 6vdy 集数 {vdy_cnt} > 其他渠道最大集数 {max_other}，置顶第一位")
        return

    target_names = {"shangxidq", "gdefud", "huxitech"}
    target_indexes = [idx for idx, item in enumerate(playlist) if item.get("name", "") in target_names]

    if target_indexes:
        insert_pos = max(target_indexes) + 1
        playlist.insert(insert_pos, new_pl)
        found_names = [playlist[i].get("name") for i in target_indexes]
        print(f"      [排序规则] 检测到渠道 {found_names}，6vdy 插入至位置 {insert_pos}")
    else:
        playlist.append(new_pl)
        print(f"      [排序规则] 6vdy 添加到 playlist 末尾")

def should_touch_update_on_episode_change(playlist, new_6vdy_count):
    max_other_count = 0
    for pl in playlist:
        if pl.get("name") == PLAYLIST_NAME:
            continue
        eps_other = pl.get("episodes", {})
        cnt = get_real_episode_count(eps_other) if isinstance(eps_other, dict) else 0
        if cnt > max_other_count:
            max_other_count = cnt
    return new_6vdy_count > max_other_count

def _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                             info_updated, movie_info_updated, matched_group, old_max_episodes):
    new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
    if only_6vdy_hits_blacklist_url(existing, BLACKLIST_URLS, new_pl):
        print("      [时间戳跳过] 6vdy 渠道命中黑名单 URL，禁止刷新 update 时间戳")
        return False

    touch = False
    new_6vdy_count = get_real_episode_count(new_6vdy_episodes)

    if matched_group in ["Drama", "Anime"]:
        if new_6vdy_count > old_max_episodes or info_updated:
            touch = True
            print(f"      ✅[时间戳] {matched_group} 集数更新/info更新 → 刷新 update")
        else:
            print(f"      [时间戳] {matched_group} 新集数({new_6vdy_count}) 未超过旧最大集数({old_max_episodes}) → 保持 update 不变")
    else:
        if movie_info_updated:
            touch = True
        elif info_updated:
            if should_touch_update_on_episode_change(playlist, new_6vdy_count):
                touch = True
                print("      ✅[时间戳] 集数更新且 6vdy 集数大于其他所有渠道最大值 → 刷新 update")
            
    if touch:
        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("      ✅[字段更新] 已同步更新「update」时间戳")
    return touch

def process_existing_record(existing, new_6vdy_episodes, sub_url, rec, matched_group):
    fields_updated = False

    normal_fields = ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]
    for field in normal_fields:
        old_val = existing.get(field)
        new_val = rec.get(field)
        if (not old_val) and new_val:
            existing[field] = new_val
            fields_updated = True
            print(f"      ✅[字段更新] 补充缺失字段「{field}」: {new_val}")

    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if should_update_date(old_date, new_date):
        existing["date"] = new_date
        fields_updated = True
        print(f"      ✅[字段更新] 更新「date」字段: 「{old_date}」 -> 「{new_date}」")

    old_rating = existing.setdefault("评分", {})
    new_rating = rec.get("评分", {})
    if isinstance(new_rating, dict):
        for rate_key in ["豆瓣", "IMDB"]:
            old_rate_val = old_rating.get(rate_key, "")
            new_rate_val = new_rating.get(rate_key, "")
            if not old_rate_val and new_rate_val:
                old_rating[rate_key] = new_rate_val
                fields_updated = True
                print(f"      ✅[字段更新] 补充评分「{rate_key}」: {new_rate_val}")

    if not new_6vdy_episodes:
        return "updated" if fields_updated else "no_new"

    url_keys = sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

    has_6vdy_url = any("xb6v" in existing.get(k, "") or existing.get(k, "") == sub_url for k in url_keys)
    playlist = existing.setdefault("playlist", [])
    
    old_max_episodes = 0
    for pl in playlist:
        eps = pl.get("episodes", {})
        cnt = get_real_episode_count(eps)
        if cnt > old_max_episodes:
            old_max_episodes = cnt

    if has_6vdy_url:
        old_6vdy_eps = {}
        old_6vdy_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_6vdy_eps = pl.get("episodes", {})
                old_6vdy_idx = idx
                break
        
        old_vdy_cnt = get_real_episode_count(old_6vdy_eps)

        if new_6vdy_episodes == old_6vdy_eps:
            info_updated = update_info_field_if_needed(existing, playlist, old_vdy_cnt)
            if info_updated:
                _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                                        True, False, matched_group, old_max_episodes)
                return "updated"
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)
            if movie_info_updated:
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return "quality_updated"
            return "meta_updated" if fields_updated else "no_change"

        if len(new_6vdy_episodes) < len(old_6vdy_eps):
            return "updated" if fields_updated else "decreased"

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
        if old_6vdy_idx != -1:
            del playlist[old_6vdy_idx]
            insert_6vdy_playlist(playlist, new_pl, existing)
        else:
            insert_6vdy_playlist(playlist, new_pl, existing)

        info_updated = update_info_field_if_needed(existing, playlist, old_vdy_cnt)
        movie_info_updated = False
        if not info_updated:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)

        if _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                                    info_updated, movie_info_updated, matched_group, old_max_episodes):
            fields_updated = True

        return "updated"

    else:
        if len(url_keys) == 1 and "url" in existing:
            new_url_key = "url1"
        else:
            max_num = 0
            for k in url_keys:
                m = re.match(r"^url(\d+)$", k)
                if m:
                    max_num = max(max_num, int(m.group(1)))
            new_url_key = f"url{max_num + 1}"

        new_ordered_dict = {}
        last_url_key = url_keys[-1] if url_keys else None

        for k, v in existing.items():
            new_ordered_dict[k] = v
            if k == last_url_key:
                new_ordered_dict[new_url_key] = sub_url

        if new_url_key not in new_ordered_dict:
            new_ordered_dict[new_url_key] = sub_url

        existing.clear()
        existing.update(new_ordered_dict)

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
        insert_6vdy_playlist(playlist, new_pl, existing)

        print(f"      ✅[新增渠道] 已将 6vdy 写入 {new_url_key}")

        info_updated = update_info_field_if_needed(existing, playlist, 0)
        movie_info_updated = False
        if not info_updated:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)

        if _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                                    info_updated, movie_info_updated, matched_group, old_max_episodes):
            fields_updated = True

        return "channel_added"

def detect_group(episodes, actors, types):
    if not episodes:
        return "Movie"

    has_ep_concept = has_episode_concept(episodes)
    if has_ep_concept:
        is_anime = False
        if not actors:
            is_anime = True
        else:
            for t in types:
                if "动漫" in t or "动画" in t:
                    is_anime = True
                    break
        return "Anime" if is_anime else "Drama"

    return "Movie"

def get_list_by_tab(tab_index):
    html, eff_url = fetch_ex(BASE_URL)
    soup = BeautifulSoup(html, "lxml")
    tab_content = soup.select_one("#tab-content")
    if not tab_content:
        raise RuntimeError("找不到 #tab-content")

    uls = [ul for ul in tab_content.find_all("ul", recursive=False) if ul.find("li")]
    if len(uls) <= tab_index:
        return []

    origin_host = _host_of(BASE_URL)
    target_ul = uls[tab_index]
    items = []
    for a in target_ul.select("li > a[href]"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        name, info = split_name_info(title)
        full = urljoin(eff_url, href)
        full = normalize_link_host(full, origin_host)
        items.append((name, info, full))
    return items

def get_homepage_list_6vdy():
    html, eff_url = fetch_ex(HOME_URL_6VDY)
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("#post_container")
    if not container:
        raise RuntimeError("找不到 #post_container（6vdy 首页）")

    origin_host = _host_of(HOME_URL_6VDY)
    items = []
    seen = set()
    for li in container.select("li.post"):
        h2 = li.find("h2")
        a = h2.find("a", href=True) if h2 else None
        if not a:
            a = li.select_one("a.zoom[href]")
        if not a:
            continue
        title = (a.get("title") or "").strip() or a.get_text(strip=True)
        href = a.get("href", "").strip()
        if not title or not href:
            continue
        full_url = urljoin(eff_url, href)
        full_url = normalize_link_host(full_url, origin_host)
        if full_url in seen:
            continue
        seen.add(full_url)
        name, info = split_name_info(title)
        items.append((name, info, full_url))
    return items

def process_items(data, items, tab_name):
    total = len(items)
    ok, fail = 0, 0

    for idx, (name, info, url) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{total}) {name} [在黑名单中，跳过]")
            continue

        print(f"  ({idx}/{total}) {name}  [{info}]")
        try:
            rec = parse_subpage(url, name, info)
            real_name = rec["name"]

            new_6vdy_eps = {}
            for pl in rec.get("playlist", []):
                if pl.get("name") == PLAYLIST_NAME:
                    new_6vdy_eps = pl.get("episodes", {})
                    break

            if not new_6vdy_eps:
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            matched_group, existing = find_existing_global(data, real_name, url)

            if real_name in WHITELIST_NAMES:
                print(f"    ✅ 白名单放行：{real_name}，跳过地区屏蔽校验")
            elif existing is not None:
                print(f"    ✓ 已存在记录放行（{matched_group}）：跳过地区屏蔽，持续更新")
            else:
                group_guess = detect_group(
                    new_6vdy_eps, rec.get("主演", []), rec.get("类型", [])
                )
                if group_guess == "Anime":
                    print(f"    ✓ 动漫/动画分类放行：跳过地区屏蔽校验")
                else:
                    region = (rec.get("地区", "") or "").strip()
                    region_match = any(keyword == region for keyword in FILTER_REGIONS)

                    if region_match:
                        max_rating = get_max_rating(rec.get("评分", {}))
                        if max_rating is not None and max_rating >= MIN_RATING_7:
                            print(f"    ✅ 地区「{region}」命中过滤名单，但评分 {max_rating} ≥ {MIN_RATING_7}，放行")
                        else:
                            rating_desc = "无有效评分" if max_rating is None else f"评分 {max_rating}"
                            print(f"    - 跳过：地区「{region}」命中过滤名单，且{rating_desc} 未达阈值 {MIN_RATING_7}")
                            ok += 1
                            time.sleep(SLEEP_BETWEEN)
                            continue

            if MIN_RATING and existing is None and real_name not in WHITELIST_NAMES:
                max_rating = get_max_rating(rec.get("评分", {}))
                if max_rating is not None and max_rating < MIN_RATING:
                    print(f"    - 跳过：评分 {max_rating} 低于阈值 {MIN_RATING}")
                    ok += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

            if existing:
                status = process_existing_record(existing, new_6vdy_eps, url, rec, matched_group)
                if status == "updated":
                    print(f"    ✅ 更新({matched_group})：6vdy 渠道发现新剧集，已覆盖更新")
                    save_json(data)
                    ok += 1
                elif status == "meta_updated":
                    print(f"    更新({matched_group})：仅补充/修正影片元数据，播放源无变化")
                    save_json(data)
                    ok += 1
                elif status == "quality_updated":
                    print(f"    ✅ 更新({matched_group})：影片画质标识升级，播放源无变化")
                    save_json(data)
                    ok += 1
                elif status == "channel_added":
                    print(f"    ✅ 更新({matched_group})：成功作为新渠道插入到 playlist 里")
                    save_json(data)
                    ok += 1
                elif status == "no_change":
                    ok += 1
                elif status == "decreased":
                    print(f"    - 忽略({matched_group})：抓取集数少于已有集数")
                    ok += 1
                else:
                    print(f"    ! 忽略({matched_group})：未成功更新")
                    fail += 1
            else:
                img_url = rec.get("image", "")
                rec["image"] = download_and_localize_image(img_url)

                group = detect_group(new_6vdy_eps, rec.get("主演", []), rec.get("类型", []))

                if group in ["Drama", "Anime"] and new_6vdy_eps:
                    has_ep_kw = any("集" in str(k) or re.search(r"S\d+E\d+", str(k), re.I) for k in new_6vdy_eps.keys())
                    if has_ep_kw:
                        episode_count = get_real_episode_count(new_6vdy_eps)
                        rec["info"] = f"更新至第{episode_count}集"
                        print(f"      [新增剧集info初始化] 自动写入 info: 「更新至第{episode_count}集」")
                    else:
                        if not rec.get("info"):
                            first_ep_name = list(new_6vdy_eps.keys())[0]
                            rec["info"] = first_ep_name
                else:
                    if new_6vdy_eps and not rec.get("info"):
                        first_ep_name = list(new_6vdy_eps.keys())[0]
                        rec["info"] = first_ep_name

                data.setdefault(group, []).append(rec)
                print(f"    ✅ 新增 -> {group} (共 {len(new_6vdy_eps)} 集) [真实名称: {real_name}] [URL: {rec['url']}]")
                save_json(data)
                ok += 1

        except Exception as e:
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    return ok, fail

def process_tab_unified(data, tab_index, tab_name):
    print(f"\n[抓取] {tab_name} ...")
    try:
        items = get_list_by_tab(tab_index)
    except Exception as e:
        print(f"  ✗ 列表页抓取失败，跳过「{tab_name}」: {e}")
        return 0, 1
    print(f"  共发现 {len(items)} 条")
    return process_items(data, items, tab_name)

def process_homepage_6vdy(data):
    print(f"\n[抓取] 6vdy 首页 ...")
    try:
        items = get_homepage_list_6vdy()
    except Exception as e:
        print(f"  ✗ 首页抓取失败，跳过: {e}")
        return 0, 1
    print(f"  共发现 {len(items)} 条")
    return process_items(data, items, "6vdy首页")

# ============== 补全模式 ==============
def fetch_new_format_data(url):
    html, eff_url = fetch_ex(url)
    soup = BeautifulSoup(html, "lxml")
    post = soup.select_one("#post_content")
    if not post:
        return None, None, None
    h1 = soup.select_one(".article_container h1")
    h1_text = h1.get_text(strip=True) if h1 else ""
    real_name, _ = split_name_info(h1_text) if h1_text else ("", "")

    img_tag = post.find("img")
    img_url = urljoin(eff_url, img_tag["src"]) if (img_tag and img_tag.get("src")) else ""

    lines = parse_post_lines(post)
    nf = parse_new_format(lines, real_name or h1_text)
    return nf, img_url, real_name

def fill_empty_fields(item, nf, img_url=""):
    changed = False
    if not item.get("导演") and nf.get("导演"):
        item["导演"] = nf["导演"]; changed = True
    for f in ["编剧", "主演", "类型", "地区", "date", "alias", "intro"]:
        if not item.get(f) and nf.get(f):
            item[f] = nf[f]; changed = True
    if not item.get("info") and nf.get("info"):
        item["info"] = nf["info"]; changed = True

    old_rating = item.setdefault("评分", {})
    nf_rating = nf.get("评分", {})
    for rk in ["豆瓣", "IMDB"]:
        if not old_rating.get(rk) and nf_rating.get(rk):
            old_rating[rk] = nf_rating[rk]; changed = True

    if img_url and not item.get("image"):
        local = download_and_localize_image(img_url)
        if local:
            item["image"] = local; changed = True

    return changed

def backfill_existing(data):
    print("\n[补全模式] 扫描已有 6vdy 记录中字段缺失的资源 ...")
    total, updated = 0, 0
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            url_keys = [k for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)]
            target_url = next((item.get(k, "") for k in url_keys if item.get(k, "") and "xb6v" in item.get(k, "")), None)
            if not target_url:
                continue

            need = (not item.get("导演") and not item.get("编剧")
                    and not item.get("主演") and not item.get("类型")
                    and not item.get("地区") and not item.get("intro"))
            if not need:
                continue

            total += 1
            print(f"  [{group}] 补全: {item.get('name')}  <- {target_url}")
            try:
                nf, img_url, _ = fetch_new_format_data(target_url)
                if nf is None:
                    print("    ✗ 跳过：无 #post_content")
                    time.sleep(SLEEP_BETWEEN)
                    continue
                if fill_empty_fields(item, nf, img_url):
                    updated += 1
                    save_json(data)
                    print(f"    ✓ 已补全 (导演:「{item.get('导演')}」 类型:{item.get('类型')} 地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            time.sleep(SLEEP_BETWEEN)

    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")

# ============== 连通性自检 ==============
def preflight_check():
    print(">>> [自检] 正在探测可用站点 ...")
    for host in MIRROR_HOSTS:
        test_url = f"https://{host}/"
        try:
            content, eff = fetch_ex(test_url, allow_mirror=False)
            if content:
                print(f">>> [自检] 可用站点: {eff}")
                return True
        except Exception as e:
            print(f">>> [自检] 不可用: {test_url} ({type(e).__name__})")
    print(">>> [自检] 所有镜像站均不可访问！")
    return False

# ============== 主流程 ==============
def main():
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)
    print("=" * 60)
    print("📦 数据安全检查")
    print("=" * 60)
    data = load_existing(JSON_PATH)
    snapshot_backup(JSON_PATH)
    before_total = count_items(data)
    if os.path.exists(JSON_PATH + ".tmp"):
        print(f">>> [提示] 发现残留临时文件 {JSON_PATH}.tmp，可自行检查后删除")

    if not preflight_check():
        print("\n已中止：网络层不可用，未对 JSON 做任何修改。")
        return

    if len(sys.argv) > 1 and sys.argv[1] in ("backfill", "--backfill"):
        backfill_existing(data)
        print("\n====================================")
        print(f"补全任务完成! 数据已保存在 {JSON_PATH}")
        return

    m_ok, m_fail = process_tab_unified(data, 0, "最新电影")
    d_ok, d_fail = process_tab_unified(data, 1, "最新剧集")
    r_ok, r_fail = process_tab_unified(data, 2, "小编推荐")
    h_ok, h_fail = process_homepage_6vdy(data)

    print("\n====================================")
    print(f"统计：电影 {m_ok}成功/{m_fail}失败 | 剧集 {d_ok}/{d_fail} | 推荐 {r_ok}/{r_fail} | 首页 {h_ok}/{h_fail}")
    print(f"所有抓取任务完成! 数据已实时安全保存在 {JSON_PATH}")

if __name__ == "__main__":
    main()