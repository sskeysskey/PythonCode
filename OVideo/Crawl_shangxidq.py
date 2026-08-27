# -*- coding: utf-8 -*-
"""
shangxidq.com 分类页（电影/电视剧/综艺/动漫）爬取脚本
基于 Crawl_huxitech.py 改写（两站同为 ewave 模板，DOM 结构一致）

用法：
    python Crawl_shangxidq.py              # 正常抓取
    python Crawl_shangxidq.py backfill     # 只补全已有 shangxidq 记录的空字段
"""

import os
import re
import sys
import json
import time
import glob
import shutil
from curl_cffi import requests as cffi
import browser_cookie3
import platform
import subprocess
import atexit
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString, Tag
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
DOMAIN        = "https://shangxidq.com"
COOKIE_DOMAIN = "shangxidq.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "shangxidq"
SITE_KEY      = "shangxidq"
REQUEST_TIMEOUT = 15
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

BLACKLIST_NAMES = [
    "天堂之剑", "定海神针：九尾三世劫", "机甲少女破时空战记",
    "无名传奇", "魔彩王国历险记", "阿松与阿暖", "欲望的陷阱", "轻松熊",
]
BLACKLIST_URLS = []

WHITELIST_NAMES = []

SITE_PRIORITY = {
    "huxitech":  0,
    "chnland":   1,
    "6vdy":      2,
    "shangxidq": 3,
}

LIST_PAGES = [
    ("https://shangxidq.com/vodshow/4--time---------2026.html", "Anime", "动漫(4)"),
    ("https://shangxidq.com/vodshow/3--time---------2026.html", "Show",  "综艺(3)"),
    ("https://shangxidq.com/vodshow/2--time---------2026.html", "Drama", "电视剧(2)"),
    ("https://shangxidq.com/vodshow/1--time---------2026.html", "Movie", "电影(1)"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "日本"]

FILTER_REGIONS_OVERRIDE = {
    "https://shangxidq.com/vodshow/1--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    "https://shangxidq.com/vodshow/2--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产",
         "泰国", "台湾", "中国台湾", "日本"],
    "https://shangxidq.com/vodshow/4--time---------2026.html":
        ["中国", "大陆", "内地", "国产", "中国大陆", "中国内地", "国产剧",
         "泰国", "台湾", "中国台湾", "日本"],
}

EMPTY_VALUES = {"未知", "内详", "暂无", "/"}
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}
MAX_EPISODES = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Referer": DOMAIN,
}

# ============== 工具函数 ==============
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
    """每次启动把当前有效文件另存一份时间戳快照，并做轮转清理"""
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

def extract_episode_number(info_text):
    """从 info 中提取纯数字集数"""
    if not info_text:
        return None
    match = re.search(r'(\d+)', info_text)
    return int(match.group(1)) if match else None

# ============== 基于 curl_cffi 的会话（伪装 Chrome 指纹）==============
_session = cffi.Session(impersonate="chrome124")
_chrome_cookies = None

def _load_chrome_cookies():
    """从本机 Chrome 读取 shangxidq 的 Cookie"""
    try:
        cj = browser_cookie3.chrome(domain_name=COOKIE_DOMAIN)
        cookies = {c.name: c.value for c in cj}
        if cookies:
            print(f">>> [Cookie] 已从 Chrome 读取 {len(cookies)} 个 cookie: {list(cookies.keys())}")
        else:
            print(f">>> [Cookie] 未读到 {COOKIE_DOMAIN} 的 cookie")
        return cookies
    except Exception as e:
        print(f">>> [Cookie] 读取 Chrome cookie 失败: {e}")
        return {}

def fetch(url, is_binary=False, use_cookies=True):
    global _chrome_cookies
    cookies = None
    if use_cookies:
        if _chrome_cookies is None:
            _chrome_cookies = _load_chrome_cookies()
        cookies = _chrome_cookies

    resp = _session.get(
        url,
        headers=HEADERS,
        cookies=cookies,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 403:
        print(f"    [403调试] {resp.text[:500]}")
    resp.raise_for_status()
    if is_binary:
        return resp.content
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text

def _re_class(base):
    return re.compile(r"^" + base.replace("_", "_+") + r"$")

def is_garbled(value):
    if not value:
        return False
    v = str(value)
    if "\ufffd" in v:
        return True
    stripped = re.sub(r"[\s/·,，、|\-]", "", v)
    if not stripped:
        return False
    if re.fullmatch(r"[?？]+", stripped):
        return True
    return False

def normalize_info_text(info_str):
    if not info_str:
        return ""
    num_match = re.search(r"(\d+)", info_str)
    if not num_match:
        return normalize_text(info_str)
    num = int(num_match.group(1))
    return f"更新至第{num}集"

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

def download_and_localize_image(img_url):
    if not img_url:
        return ""
    fn = safe_filename(img_url)
    if not fn:
        return ""
    local_path = os.path.join(IMG_DIR, fn)
    if not os.path.exists(local_path):
        content = None
        last_err = ""
        for use_cookies in (False, True):
            try:
                content = fetch(img_url, is_binary=True, use_cookies=use_cookies)
                break
            except Exception as e:
                last_err = e
        if content is None:
            print(f"  [图片下载失败] {img_url}: {last_err}")
            return ""
        try:
            os.makedirs(IMG_DIR, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            print(f"  [图片] 已下载 -> {fn}")
        except Exception as e:
            print(f"  [图片写入失败] {fn}: {e}")
            return ""
    return fn

def extract_info_date(info):
    if not info:
        return None
    m = re.search(r"(20\d{6})", info)
    return m.group(1) if m else None

def get_max_episode_number(episodes):
    """
    从选集字典的集名中提取最大有效集编号：
    1. 优先解析 SxxExx 格式（如 S05E08），自动提取最大季的对应最大集
    2. 解析 第X季第Y集 格式
    3. 解析常规单集数字
    """
    if not episodes:
        return 0

    # 1. 匹配 SxxExx 格式
    se_pairs = []
    for name in episodes.keys():
        m = re.search(r'S(\d+)E(\d+)', str(name), re.IGNORECASE)
        if m:
            se_pairs.append((int(m.group(1)), int(m.group(2))))
    if se_pairs:
        max_season = max(s for s, e in se_pairs)
        max_ep_in_latest_season = max(e for s, e in se_pairs if s == max_season)
        return max_ep_in_latest_season

    # 2. 匹配 第X季...第Y集 格式
    season_ep_pairs = []
    for name in episodes.keys():
        m = re.search(r'第\s*(\d+)\s*季.*?第\s*(\d+)\s*[集期话話]', str(name))
        if m:
            season_ep_pairs.append((int(m.group(1)), int(m.group(2))))
    if season_ep_pairs:
        max_season = max(s for s, e in season_ep_pairs)
        max_ep_in_latest_season = max(e for s, e in season_ep_pairs if s == max_season)
        return max_ep_in_latest_season

    # 3. 常规集数提取
    max_num = 0
    for name in episodes.keys():
        m = re.search(r'(\d+)\s*[集期话話]', str(name))
        if not m:
            m = re.search(r'第\s*(\d+)', str(name))
        if not m:
            m = re.search(r'(\d+)', str(name))
        if m:
            max_num = max(max_num, int(m.group(1)))
            
    # 【修改】：删除了 if max_num == 0: max_num = len(episodes)
    return max_num

def _url_keys_sorted(existing):
    return sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

def _ensure_site_url(existing, sub_url, force_new=False):
    url_keys = _url_keys_sorted(existing)
    if not force_new:
        for k in url_keys:
            v = existing.get(k, "") or ""
            if SITE_KEY in v or v == sub_url:
                return k

    max_num = 0
    for k in url_keys:
        m = re.match(r"^url(\d+)$", k)
        if m:
            max_num = max(max_num, int(m.group(1)))
    new_url_key = f"url{max_num + 1}"

    last_url_key = url_keys[-1] if url_keys else None
    new_ordered = {}
    inserted = False
    for k, v in existing.items():
        new_ordered[k] = v
        if k == last_url_key:
            new_ordered[new_url_key] = sub_url
            inserted = True
    if not inserted:
        new_ordered[new_url_key] = sub_url

    existing.clear()
    existing.update(new_ordered)
    return new_url_key

def append_site_channel(existing, new_episodes, sub_url):
    new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
    existing.setdefault("playlist", []).append(
        {"name": PLAYLIST_NAME, "episodes": new_episodes}
    )
    return new_url_key

def promote_site_to_pos(existing, new_episodes, sub_url, insert_pos=0):
    playlist = existing.setdefault("playlist", [])
    site_index = next(
        (i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME),
        None
    )

    if site_index is not None:
        pl = playlist.pop(site_index)
        pl["episodes"] = new_episodes
        target = insert_pos - 1 if site_index < insert_pos else insert_pos
        target = max(0, min(target, len(playlist)))
        playlist.insert(target, pl)
        _ensure_site_url(existing, sub_url)
        return None, ("in_place" if target == site_index else "moved")

    new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
    playlist = existing.setdefault("playlist", [])
    pos = max(0, min(insert_pos, len(playlist)))
    playlist.insert(pos, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return new_url_key, "inserted"

def extract_episode_count_from_info(info):
    if not info:
        return None
    m = re.search(r"更新[至到]\D*?(\d+)", info)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*[集期话話]\s*$", info)
    if m:
        return int(m.group(1))
    return None

def is_valid_episode_name(name):
    if not name:
        return False
    if name in INVALID_EPISODE_NAMES:
        return False
    if re.match(r"^更新[至到]", name):
        return False
    return True

def filter_episodes(eps):
    return {k: v for k, v in eps.items() if is_valid_episode_name(k)}

def detect_group_by_episodes(episodes):
    names = list(episodes.keys())
    count = len(names)
    has_ji = any("集" in n or re.search(r"S\d+E\d+", n, re.I) for n in names)
    if has_ji and count > 2:
        return "Drama"
    return "Movie"

def insert_playlist_by_priority(playlist, new_pl):
    new_prio = SITE_PRIORITY.get(new_pl.get("name"), 99)
    pos = len(playlist)
    for i, pl in enumerate(playlist):
        if new_prio < SITE_PRIORITY.get(pl.get("name"), 99):
            pos = i
            break
    playlist.insert(pos, new_pl)
    return pos

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

# ============== 列表页解析 ==============
def get_list(list_url):
    html = fetch(list_url)
    soup = BeautifulSoup(html, "lxml")
    items = []
    for li in soup.select("ul.ewave-vodlist li"):
        detail = li.find(class_=_re_class("ewave-vodlist_detail"))
        h4a = None
        if detail:
            h4a = detail.select_one("h4.title a[href]")
        if not h4a:
            h4a = li.select_one("h4.title a[href]")
        if not h4a:
            continue
        href = h4a.get("href", "")
        title = (h4a.get("title") or h4a.get_text(strip=True)).strip()
        if not href or not title:
            continue

        thumb = li.find(class_=_re_class("ewave-vodlist_thumb"))
        info = ""
        img = ""
        if thumb:
            pic = thumb.select_one("span.pic-text")
            if pic:
                info = pic.get_text(strip=True)
            img = thumb.get("data-original", "") or thumb.get("data-src", "") or ""
            if not img:
                img_tag = thumb.select_one("img[data-original]")
                if img_tag:
                    img = img_tag.get("data-original", "")
                if not img:
                    img_tag = thumb.select_one("img")
                    if img_tag:
                        img = img_tag.get("data-original", "") or img_tag.get("src", "") or ""

        info = normalize_text(info)
        img = urljoin(DOMAIN, img) if img else ""

        name, _ = split_name_info(title)
        if not name:
            name = title
        items.append((name, info, urljoin(DOMAIN, href), img))
    return items

# ============== 详情页解析 ==============
def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES or is_garbled(v):
        return ""
    return v

def parse_detail_fields(detail_div):
    result = {"类型": [], "地区": "", "date": "", "主演": [], "导演": []}
    if detail_div is None:
        return result

    def assign(field, value):
        value = _clean_val(value)
        if not value:
            return
        if field in ("类型", "主演", "导演"):
            if value not in result[field]:
                result[field].append(value)
        elif field == "地区":
            if not result["地区"]:
                result["地区"] = value
        elif field == "date":
            if not result["date"]:
                result["date"] = value

    def detect_field(text):
        if not text:
            return None
        if re.search(r"类\s*型", text):
            return "类型"
        if re.search(r"地\s*区", text):
            return "地区"
        if re.search(r"年\s*份", text):
            return "date"
        if re.search(r"主\s*演|演\s*员", text):
            return "主演"
        if re.search(r"导\s*演", text):
            return "导演"
        return None

    p_tags = detail_div.select("p.data")
    if not p_tags:
        p_tags = detail_div.select("p")

    for p in p_tags:
        current = None
        for node in p.children:
            if isinstance(node, Tag):
                if node.name == "span":
                    classes = node.get("class", []) or []
                    if "split-line" in classes:
                        current = None
                        continue
                    text = node.get_text(strip=True)
                    matched = detect_field(text)
                    if matched:
                        current = matched
                    elif "text-muted" in classes:
                        current = None
                elif node.name == "a":
                    if current:
                        assign(current, node.get_text(strip=True))
            elif isinstance(node, NavigableString):
                if current:
                    val = _clean_val(str(node))
                    if val:
                        assign(current, val)
    return result

def parse_intro(soup):
    desc = soup.find(id="desc")
    if not desc:
        return ""
    bd = desc.find(class_=_re_class("ewave-pannel_bd"))
    p = bd.find("p") if bd else None
    if not p:
        p = desc.select_one("p.col-pd")
    if not p:
        return ""
    text = normalize_text(p.get_text(" ", strip=True))
    if not text or is_garbled(text):
        return ""
    m = re.search(r"剧情简介[：:]\s*(.+)", text)
    if m:
        result = normalize_text(m.group(1))
        return "" if is_garbled(result) else result
    return text

def extract_episodes(soup):
    best = {}
    for ul in soup.find_all("ul", class_=_re_class("ewave-content_playlist")):
        eps = {}
        for a in ul.select("li a[href]"):
            name = normalize_text(a.get_text(strip=True))
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
        if len(eps) > len(best):
            best = eps

    if best:
        return filter_episodes(best)

    exclude_pat = re.compile(r"ewave-content_+thumb|play-btn|ewave-vodlist_+thumb")
    pannel_bd = soup.find_all(class_=_re_class("ewave-pannel_bd"))
    eps = {}
    for bd in pannel_bd:
        for a in bd.select('a[href*="/vodplay/"]'):
            if a.find_parent(class_=exclude_pat):
                continue
            name = normalize_text(a.get_text(strip=True))
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
    if eps:
        return filter_episodes(eps)

    eps = {}
    for a in soup.select('a[href*="/vodplay/"]'):
        if a.find_parent(class_=exclude_pat):
            continue
        name = normalize_text(a.get_text(strip=True))
        href = a.get("href", "")
        if name and href:
            eps[name] = urljoin(DOMAIN, href)
    return filter_episodes(eps)

def parse_real_name(soup, default_name):
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    if not detail:
        return default_name
    h1 = detail.find("h1", class_="title")
    if not h1:
        return default_name
    for sp in h1.find_all("span"):
        classes = sp.get("class", []) or []
        if any(("score" in c) or ("raty" in c) for c in classes):
            sp.extract()
    t = normalize_text(h1.get_text(strip=True))
    t = re.sub(r"\s*\d+(\.\d+)?\s*$", "", t).strip() or t
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t

def extract_image_from_detail(soup):
    thumb = soup.find(class_=_re_class("ewave-vodlist_thumb"))
    if not thumb:
        return ""
    img_tag = thumb.select_one("img[data-original]")
    if img_tag:
        return img_tag.get("data-original", "")
    img_tag = thumb.select_one("img")
    if img_tag:
        return img_tag.get("data-original", "") or img_tag.get("src", "") or ""
    return thumb.get("data-original", "") or ""

def extract_info_from_detail(soup):
    thumb = soup.find(class_=_re_class("ewave-vodlist_thumb"))
    if thumb:
        pic = thumb.select_one("span.pic-text")
        if pic:
            return normalize_text(pic.get_text(strip=True))
    return ""

def parse_subpage(sub_url, default_name, default_info, list_img=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    info = default_info
    if not info:
        info = extract_info_from_detail(soup)

    img_url = list_img
    if not img_url:
        img_url = extract_image_from_detail(soup)
    if img_url:
        img_url = urljoin(DOMAIN, img_url)

    playlist = []
    if episodes:
        playlist.append({"name": PLAYLIST_NAME, "episodes": episodes})

    director_str = " / ".join(fields["导演"]) if fields["导演"] else ""

    return {
        "name":   real_name,
        "url":    sub_url,
        "info":   info,
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   director_str,
        "编剧":   [],
        "主演":   fields["主演"],
        "类型":   fields["类型"],
        "地区":   fields["地区"],
        "date":   fields["date"],
        "alias":  "",
        "intro":  intro or "",
        "评分":   {"豆瓣": "", "IMDB": ""},
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

def normalize_url(u):
    """去除协议头、www、尾部斜杠，确保 URL 格式统一"""
    if not u:
        return ""
    u = str(u).strip()
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    u = re.sub(r"^www\.", "", u, flags=re.IGNORECASE)
    return u.rstrip("/")

def clean_season_one(s):
    """将'第一季'、'第1季'后缀剥离，用于基础名称比对"""
    if not s:
        return ""
    return re.sub(r"(?:第[一1]季)$", "", s).strip()

def find_existing_global(data, name, sub_url, log=print):
    def normalize_name(s):
        return s.replace(" ", "").strip() if s else ""

    norm_name = normalize_name(name)
    base_name = clean_season_one(norm_name)
    norm_sub_url = normalize_url(sub_url)

    # 1. 优先通过 URL 匹配（规范化后比对）
    if norm_sub_url:
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                for k in item.keys():
                    if k == "url" or re.match(r"^url\d+$", k):
                        val = item.get(k, "")
                        if val and normalize_url(val) == norm_sub_url:
                            existing_name = item.get("name", "")
                            if existing_name != name:
                                log(f"      [URL匹配去重] 发现 URL 一致 (URL: {sub_url}, 已有:「{existing_name}」, 抓取:「{name}」)")
                            return group, item

    # 2. 其次通过名称匹配（忽略空格）
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            existing_raw_name = item.get("name", "")
            existing_norm_name = normalize_name(existing_raw_name)
            
            # 2.1 完全相等
            if existing_norm_name == norm_name:
                log(f"      [名称去重（忽略空格）] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
                return group, item
            
            # 2.2 兼容“柯蒂斯总统”与“柯蒂斯总统 第一季 / 柯蒂斯总统第1季”
            existing_base_name = clean_season_one(existing_norm_name)
            if base_name and existing_base_name and base_name == existing_base_name:
                log(f"      [季数兼容去重] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
                return group, item

    return None, None

def process_existing_record(existing, new_episodes, sub_url, rec, matched_group,
                           old_max_episodes, log=print):
    """处理已存在的记录：合并字段、更新播放源和 info"""
    fields_updated = merge_missing_fields(existing, rec, log)

    def update_time_if_needed():
        if matched_group in ("Drama", "Anime"):
            new_max = get_max_episode_number(new_episodes)
            if new_max > old_max_episodes:
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not new_episodes:
        return "updated" if fields_updated else "no_new"

    url_keys = _url_keys_sorted(existing)
    has_site_url = False
    for k in url_keys:
        val = existing.get(k, "") or ""
        if SITE_KEY in val or val == sub_url:
            has_site_url = True
            break

    playlist = existing.setdefault("playlist", [])
    site_max = get_max_episode_number(new_episodes)
    
    # 统计其他渠道最大集数
    other_max = 0
    for pl in playlist:
        if pl.get("name") == PLAYLIST_NAME:
            continue
        other_max = max(other_max, get_max_episode_number(pl.get("episodes", {})))

    info_updated = False
    # 【修改】：增加 matched_group 判断，排除 Movie
    if matched_group in ("Drama", "Anime", "Show") and site_max > other_max and site_max > 0:
        candidate_info = f"更新至第{site_max}集"
        if existing.get("info") != candidate_info:
            old_info = existing.get("info", "")
            existing["info"] = candidate_info
            info_updated = True
            log(f"      ✅[info更新] 抓取最大集数 {site_max} > 其他渠道最大集数 {other_max}，info: 「{old_info}」 -> 「{candidate_info}」")

    if has_site_url:
        old_eps = {}
        old_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_eps = pl.get("episodes", {})
                old_idx = idx
                break

        if new_episodes == old_eps:
            if info_updated:
                update_time_if_needed()
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_episodes) < len(old_eps):
            return "updated" if (fields_updated or info_updated) else "decreased"

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        if old_idx != -1:
            playlist[old_idx] = new_pl
            if site_max > other_max and old_idx != 0:
                playlist.insert(0, playlist.pop(old_idx))
                log(f"      [排序调整] {SITE_KEY} 最大集数({site_max}) > 其他渠道最大集数({other_max})，已移动至第一位")
        else:
            if site_max > other_max:
                playlist.insert(0, new_pl)
                log(f"      [排序调整] {SITE_KEY} 最大集数({site_max}) > 其他渠道最大集数({other_max})，已直接插入至第一位")
            else:
                insert_playlist_by_priority(playlist, new_pl)

        update_time_if_needed()
        return "updated"

    else:
        new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        pos = insert_playlist_by_priority(playlist, new_pl)
        log(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}，并按优先级把播放源插入至第 {pos + 1} 位")
        update_time_if_needed()
        return "channel_added"

# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    filter_regions = FILTER_REGIONS_OVERRIDE.get(list_url, FILTER_REGIONS)
    try:
        items = get_list(list_url)
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        return 0, 0
    print(f"  共发现 {len(items)} 条")
    ok, fail = 0, 0

    for idx, (name, info, url, img) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在名称黑名单中，跳过]")
            continue

        if any(black_url in url for black_url in BLACKLIST_URLS if black_url):
            print(f"  ({idx}/{len(items)}) {name} [URL 在黑名单中，跳过: {url}]")
            continue

        header = f"  ({idx}/{len(items)}) {name}  [{info}]"
        buf = []

        def flush():
            print(header)
            for line in buf:
                print(line)

        try:
            rec = parse_subpage(url, name, info, list_img=img)
            real_name = rec["name"]

            new_eps = {}
            for pl in rec.get("playlist", []):
                if pl.get("name") == PLAYLIST_NAME:
                    new_eps = pl.get("episodes", {})
                    break

            if not new_eps:
                flush()
                print("    ! 无播放源，跳过")
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            current_group = group
            if group == "AUTO":
                current_group = detect_group_by_episodes(new_eps)
                buf.append(f"    [自动分类] 选集共 {len(new_eps)} 项，判定为「{current_group}」")

            if current_group in ("Drama", "Anime") and len(new_eps) > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」属于「{current_group}」，集数 {len(new_eps)} 超过 {MAX_EPISODES} 集(期) 上限 ")
                ok += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            matched_group, existing = find_existing_global(data, real_name, url, buf.append)
            if existing and matched_group != current_group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，将按「{matched_group}」规则处理")

            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            elif current_group in ("Anime", "Drama", "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = rec.get("地区", "").strip()
                if any(keyword == region for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    ok += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

                if region in ("", "未知"):
                    cn_type_keywords = ["国产", "中国", "大陆", "内地"]
                    type_text = " ".join(rec.get("类型", []) or [])
                    matched_kw = next((kw for kw in cn_type_keywords if kw in type_text), None)
                    if matched_kw:
                        flush()
                        print(f"    - 跳过：地区未知，但类型「{type_text}」含「{matched_kw}」，判定为国产内容")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

            if existing:
                old_max_episodes = 0
                for pl in existing.get("playlist", []):
                    old_max_episodes = max(old_max_episodes, get_max_episode_number(pl.get("episodes", {})))

                has_site_channel = any(pl.get("name") == PLAYLIST_NAME for pl in existing.get("playlist", []))
                new_max = get_max_episode_number(new_eps)

                promote = False
                insert_at = None
                if matched_group in ("Drama", "Anime"):
                    playlist_all = existing.get("playlist", [])
                    global_max = 0
                    idx_global_max = -1
                    for i, pl in enumerate(playlist_all):
                        if pl.get("name") == PLAYLIST_NAME:
                            continue
                        pl_max = get_max_episode_number(pl.get("episodes", {}))
                        if pl_max > global_max:
                            global_max = pl_max
                            idx_global_max = i
                    buf.append(f"    [{matched_group}] 其他渠道最大集数={global_max}, {SITE_KEY}新抓取max={new_max}")
                    if new_max > global_max:
                        promote = True
                        insert_at = 0
                        buf.append(f"    [{matched_group}] {SITE_KEY}({new_max}) > 其他最大({global_max})，目标位置 playlist[0]")
                    elif new_max == global_max and global_max > 0:
                        promote = True
                        insert_at = idx_global_max + 1 if idx_global_max >= 0 else 0
                        buf.append(f"    [{matched_group}] {SITE_KEY}({new_max}) == 其他最大({global_max})，目标下标 {insert_at}")
                    elif new_max > 0:
                        promote = True
                        insert_at = idx_global_max + 1 if idx_global_max >= 0 else 0
                        buf.append(f"    [{matched_group}] {SITE_KEY}({new_max}) < 其他最大({global_max})，目标下标 {insert_at}")

                if promote:
                    playlist = existing.setdefault("playlist", [])
                    site_index = next((i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME), None)
                    old_site_eps = (playlist[site_index].get("episodes", {}) if site_index is not None else {})

                    if site_index is not None and len(new_eps) < len(old_site_eps):
                        flush()
                        print(f"    - 忽略({matched_group})：本次抓取 {len(new_eps)} 集 少于已有 {len(old_site_eps)} 集，保留原有 playlist")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

                    eps_changed = (new_eps != old_site_eps)

                    if eps_changed:
                        url_key, action = promote_site_to_pos(existing, new_eps, url, insert_pos=insert_at)
                    else:
                        url_key = _ensure_site_url(existing, url, force_new=(site_index is None))
                        action = "in_place"

                    # 核心判断：新抓取集数严格大于其他所有渠道集数时，刷新 info
                    info_changed = False
                    if new_max > global_max and new_max > 0:
                        candidate_info = f"更新至第{new_max}集"
                        if existing.get("info") != candidate_info:
                            old_info = existing.get("info", "")
                            existing["info"] = candidate_info
                            info_changed = True
                            buf.append(f"    [info更新] {SITE_KEY}集数({new_max}) > 其他最大({global_max})，「{old_info}」 -> 「{candidate_info}」")

                    fields_changed = merge_missing_fields(existing, rec, buf.append)
                    actual_changed = (eps_changed or info_changed or fields_changed or action in ("moved", "inserted"))

                    if actual_changed:
                        if matched_group in ("Drama", "Anime"):
                            if new_max > old_max_episodes or info_changed:
                                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(data)
                    flush()

                    if not actual_changed:
                        print(f"    - 无变更({matched_group})：集数、info、字段均无变化，保持原有顺序")
                        ok += 1
                    elif action == "inserted":
                        print(f"    ✅ 更新({matched_group})：{SITE_KEY} 作为新渠道写入 {url_key}，已插入 playlist 下标 {insert_at}")
                        ok += 1
                    elif action == "moved":
                        print(f"    ✅ 更新({matched_group})：{SITE_KEY} 已更新集数({len(old_site_eps)} -> {len(new_eps)})，并移动到目标位置")
                        ok += 1
                    elif eps_changed:
                        print(f"    ✅ 更新({matched_group})：{SITE_KEY} 已更新集数({len(old_site_eps)} -> {len(new_eps)})，位置保持不变")
                        ok += 1
                    else:
                        print(f"    ✅ 更新({matched_group})：仅 info/字段更新，保持原有顺序")
                        ok += 1

                elif has_site_channel:
                    status = process_existing_record(existing, new_eps, url, rec,
                                                     matched_group, old_max_episodes,
                                                     buf.append)
                    if status == "updated":
                        buf.append(f"    ✅ 更新({matched_group})：{SITE_KEY} 渠道发现新内容，已覆盖更新")
                        save_json(data)
                        flush()
                        ok += 1
                    elif status == "channel_added":
                        buf.append(f"    ✅ 更新({matched_group})：成功作为新渠道插入到 playlist")
                        save_json(data)
                        flush()
                        ok += 1
                    elif status == "no_change":
                        ok += 1
                    elif status == "decreased":
                        flush()
                        print(f"    - 忽略({matched_group})：抓取集数少于已有集数")
                        ok += 1
                    else:
                        flush()
                        print(f"    ! 忽略({matched_group})：未成功更新")
                        fail += 1

                else:
                    can_add = False
                    playlist_len = len(existing.get("playlist", []))
                    episode_total = len(new_eps)

                    if matched_group == "Movie":
                        can_add = True
                        buf.append(f"    [Movie] 允许把 {SITE_KEY} 作为新渠道插入，现有渠道数 {playlist_len}")
                    elif matched_group == "Drama":
                        other_channels_max_eps = 0
                        for pl in existing.get("playlist", []):
                            if pl.get("name") == PLAYLIST_NAME:
                                continue
                            pl_eps = pl.get("episodes", {})
                            pl_max = get_max_episode_number(pl_eps)
                            if pl_max > other_channels_max_eps:
                                other_channels_max_eps = pl_max

                        cond_a = (playlist_len == 1 and episode_total < 20)
                        cond_b = (episode_total > other_channels_max_eps)

                        if cond_a:
                            can_add = True
                            buf.append(f"    [Drama] 现有单一渠道，总集数{episode_total}<20，允许追加{SITE_KEY}渠道至末尾")
                        elif cond_b:
                            can_add = True
                            buf.append(f"    [Drama] 本次抓取集数{episode_total} > 其它渠道最大集数{other_channels_max_eps}，允许追加{SITE_KEY}新渠道")

                    if can_add:
                        new_url_key = append_site_channel(existing, new_eps, url)
                        merge_missing_fields(existing, rec, buf.append)
                        
                        # 【修改】：仅限 Drama / Anime / Show 剧集类更新 info
                        if matched_group in ("Drama", "Anime", "Show") and new_max > other_channels_max_eps and new_max > 0:
                            existing["info"] = f"更新至第{new_max}集"

                        if matched_group in ("Drama", "Anime"):
                            if new_max > old_max_episodes:
                                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(data)
                        flush()
                        print(f"    ✅ 更新({matched_group})：已把 {SITE_KEY} 作为新渠道写入 {new_url_key}，并追加到 playlist 末尾")
                        ok += 1
                    else:
                        flush()
                        print(f"    - 跳过({matched_group})：项目已存在但无 {SITE_KEY} 渠道，且不满足补充渠道条件，保持原样")
                        ok += 1
            else:
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                
                # 新增时若是剧集且有集数，格式化 info
                ep_cnt = get_max_episode_number(new_eps)
                if current_group in ("Drama", "Anime") and ep_cnt > 0:
                    rec["info"] = f"更新至第{ep_cnt}集"

                data.setdefault(current_group, []).append(rec)
                print(f"    ✅ 新增 -> {current_group} (共 {len(new_eps)} 集) [真实名称: {real_name}] [URL: {rec['url']}]")
                save_json(data)
                ok += 1

        except Exception as e:
            flush()
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    return ok, fail

# ============== 补全模式 ==============
def fetch_detail_data(url):
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    if detail is None:
        return None, None
    fields = parse_detail_fields(detail)
    fields["intro"] = parse_intro(soup)
    img_url = extract_image_from_detail(soup)
    if img_url:
        img_url = urljoin(DOMAIN, img_url)
    return fields, img_url

def fill_empty_fields(item, fields, img_url=""):
    changed = False
    if not item.get("导演") and fields.get("导演"):
        item["导演"] = " / ".join(fields["导演"]) if isinstance(fields["导演"], list) else fields["导演"]
        changed = True
    for f in ["主演", "类型", "地区", "date", "intro"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    if img_url and not item.get("image"):
        local = download_and_localize_image(img_url)
        if local:
            item["image"] = local; changed = True
    return changed

def backfill_existing(data):
    print(f"\n[补全模式] 扫描已有 {SITE_KEY} 记录中字段缺失的资源 ...")
    total, updated = 0, 0
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            url_keys = [k for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)]
            target_url = next((item.get(k, "") for k in url_keys if item.get(k, "") and SITE_KEY in item.get(k, "")), None)
            if not target_url:
                continue
            need = (not item.get("导演") and not item.get("主演")
                    and not item.get("类型") and not item.get("地区")
                    and not item.get("intro"))
            if not need:
                continue
            total += 1
            print(f"  [{group}] 补全: {item.get('name')}  <- {target_url}")
            try:
                fields, img_url = fetch_detail_data(target_url)
                if fields is None:
                    print("    ✗ 跳过：无详情内容")
                    time.sleep(SLEEP_BETWEEN)
                    continue
                if fill_empty_fields(item, fields, img_url):
                    item["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    updated += 1
                    save_json(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} 地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            time.sleep(SLEEP_BETWEEN)
    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")

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

    if len(sys.argv) > 1 and sys.argv[1] in ("backfill", "--backfill"):
        backfill_existing(data)
        print("\n====================================")
        print(f"补全任务完成! 数据已保存在 {JSON_PATH}")
        return

    total_ok, total_fail = 0, 0
    for list_url, group, page_name in LIST_PAGES:
        ok, fail = process_list_page(data, list_url, group, page_name)
        total_ok += ok
        total_fail += fail

    print("\n====================================")
    print(f"所有抓取任务完成! 成功 {total_ok} 条，失败 {total_fail} 条。数据已实时保存在 {JSON_PATH}")

if __name__ == "__main__":
    main()