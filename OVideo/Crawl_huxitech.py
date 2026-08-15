# -*- coding: utf-8 -*-
"""
cifppc.com 分类页（电影/电视剧/综艺/动漫 + 混合页37）爬取脚本
基于 Crawl_chnland.py 改写
"""

import os
import re
import sys
import json
import time
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
DOMAIN        = "https://www.cifppc.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "huxitech"
SITE_KEY      = "huxitech"
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0
BLACKLIST_NAMES = ["天堂之剑", "定海神针：九尾三世劫",
                   "机甲少女破时空战记", "无名传奇", "魔彩王国历险记", "阿松与阿暖", "欲望的陷阱"]
# 支持填写完整的 URL 或 URL 包含的关键词/路径片段（例如 "/voddetail/1234.html" 或特定 ID片段）
BLACKLIST_URLS = [
    "https://www.cifppc.com/voddetail/99927.html",
]

# 白名单（在这里添加你要放行的名称，跳过地区屏蔽）
WHITELIST_NAMES = [
    # "镖人 第二季"
]

# 渠道优先级：数字越小优先级越高，playlist 排序时靠前
SITE_PRIORITY = {
    "huxitech": 0,
    "chnland":  1,
    "6vdy":     2,
}

# 分类页 -> 分组
#   group 为 "AUTO" 时，抓完详情后根据选集列表自动判定 电影/电视剧
LIST_PAGES = [
    ("https://www.cifppc.com/vodshow/4--time---------2026.html",  "Anime", "动漫"),
    ("https://www.cifppc.com/vodshow/3--time---------2026.html",  "Show",  "综艺"),
    ("https://www.cifppc.com/vodshow/35--time---------.html",     "Movie", "电影(35)"),
    ("https://www.cifppc.com/vodshow/2--time---------2026.html",  "Drama", "电视剧"),
    ("https://www.cifppc.com/vodshow/1--time---------2026.html",  "Movie", "电影(1)"),
    ("https://www.cifppc.com/vodshow/37--time---------2026.html", "AUTO",  "混合(37)"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "日本"]
# 针对特定列表页的地区过滤覆盖（key = 列表页 URL，value = 该页要屏蔽的地区名单）
FILTER_REGIONS_OVERRIDE = {
    # 电影(35)：放开「日本」，其余保持屏蔽
    "https://www.cifppc.com/vodshow/35--time---------.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],

    # 电影(1)：只屏蔽「泰国和中国」，其余地区全部放开
    "https://www.cifppc.com/vodshow/1--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],

    # 电视剧(1)：
    "https://www.cifppc.com/vodshow/2--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "国产剧", "国产", "泰国", "台湾", "中国台湾", "日本"],

    # 动漫(4)：
    "https://www.cifppc.com/vodshow/4--time---------2026.html":
        ["中国", "大陆", "内地", "国产", "中国大陆", "中国内地", "国产剧", "泰国", "台湾", "中国台湾", "日本"],
}

# 视为"空值"的占位文案
EMPTY_VALUES = {"未知", "内详", "暂无", "/"}

# 无效的集名（需要从 playlist 中过滤掉）
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Referer": DOMAIN,
}

# ============== 工具函数 ==============
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
    """从本机 Chrome 读取 huxitech 的 Cookie（含 cf_clearance）"""
    try:
        cj = browser_cookie3.chrome(domain_name="cifppc.com")
        cookies = {c.name: c.value for c in cj}
        if cookies:
            print(f">>> [Cookie] 已从 Chrome 读取 {len(cookies)} 个 cookie: "
                  f"{list(cookies.keys())}")
        else:
            print(">>> [Cookie] 未读到 huxitech 的 cookie，请先在 Chrome 里手动过一次验证并浏览一下该站")
        return cookies
    except Exception as e:
        print(f">>> [Cookie] 读取 Chrome cookie 失败: {e}")
        return {}

def fetch(url, is_binary=False):
    global _chrome_cookies
    if _chrome_cookies is None:
        _chrome_cookies = _load_chrome_cookies()
    resp = _session.get(
        url,
        headers=HEADERS,
        cookies=_chrome_cookies,
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
    """
    把单下划线写法的类名转成兼容"单/双下划线"的正则。
    例如 "ewave-content_detail" -> 同时匹配 ewave-content_detail 和 ewave-content__detail
    """
    return re.compile(r"^" + base.replace("_", "_+") + r"$")


def is_garbled(value):
    """判断是否为乱码/无效值"""
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
    """把更新信息标准化，用于对比语义是否相同，忽略：04→4、多余的第字"""
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

def extract_info_date(info):
    """从 info 文本中提取 8 位日期数字 (YYYYMMDD)，找不到返回 None"""
    if not info:
        return None
    m = re.search(r"(20\d{6})", info)
    if m:
        return m.group(1)
    return None

def get_max_episode_number(episodes):
    """从选集字典的集名中提取最大集编号；集名里没有数字时退回到集数总量"""
    max_num = 0
    for name in episodes.keys():
        m = re.search(r'(\d+)\s*[集期话話]', name)   # 优先 "第20集" / "20期"
        if not m:
            m = re.search(r'第\s*(\d+)', name)         # 其次 "第20"
        if not m:
            m = re.search(r'(\d+)', name)              # 最后任意数字
        if m:
            max_num = max(max_num, int(m.group(1)))
    if max_num == 0:
        max_num = len(episodes)
    return max_num


def _url_keys_sorted(existing):
    """按 url, url1, url2 ... 的顺序返回所有 url 键"""
    return sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )


def _ensure_site_url(existing, sub_url, force_new=False):
    """
    确保 existing 里存在指向本站(SITE_KEY)的 urlX。
      - 已存在（含 SITE_KEY 或值等于 sub_url）-> 直接返回该键名
      - 不存在 -> 分配新的 urlX，并插到最后一个 url 键之后（保持字段顺序）
    返回使用/新建的键名
    """
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
    new_url_key = f"url{max_num + 1}"   # 只有 base "url" 时 -> url1

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

    # 注意：clear + update 不会改变 playlist 列表对象的身份，外部持有的引用依然有效
    existing.clear()
    existing.update(new_ordered)
    return new_url_key


def append_huxitech_channel(existing, new_episodes, sub_url):
    """
    把 huxitech 作为【新渠道】追加：
      - 分配新的 urlX，并插到最后一个 url 键之后
      - playlist 直接追加到末尾（不按优先级插队）
    返回新分配的 url 键名
    """
    new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
    existing.setdefault("playlist", []).append(
        {"name": PLAYLIST_NAME, "episodes": new_episodes}
    )
    return new_url_key


def promote_huxitech_to_front(existing, new_episodes, sub_url, insert_pos=0):
    """
    把 huxitech 渠道放到指定位置 insert_pos（0 = 最前）
      - 已存在 huxitech 渠道 -> 覆盖其 episodes，并移动到 insert_pos
      - 不存在 -> 新建 urlX，playlist 插入 insert_pos
    返回 (url_key, action)，action ∈ {"in_place", "moved", "inserted"}

    ★ 关键修复：pop 出来之后必须【无条件】插回去，
      并且要修正"pop 导致后续下标前移 1"的偏移，否则会直接丢渠道。
    """
    playlist = existing.setdefault("playlist", [])
    hux_index = next(
        (i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME),
        None
    )

    # ---- 情况 A：已存在 huxitech，覆盖 episodes 并移动到目标位置 ----
    if hux_index is not None:
        pl = playlist.pop(hux_index)
        pl["episodes"] = new_episodes

        # pop 之后，若原下标在目标位置之前，目标下标要 -1
        target = insert_pos - 1 if hux_index < insert_pos else insert_pos
        target = max(0, min(target, len(playlist)))
        playlist.insert(target, pl)        # ★ 无论如何都插回来

        # 顺带确保 urlX 中存在本站链接
        _ensure_site_url(existing, sub_url)
        return None, ("in_place" if target == hux_index else "moved")

    # ---- 情况 B：不存在 huxitech，新建 urlX 并插入 playlist ----
    new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
    playlist = existing.setdefault("playlist", [])
    pos = max(0, min(insert_pos, len(playlist)))
    playlist.insert(pos, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return new_url_key, "inserted"


def extract_episode_count_from_info(info):
    """从 info 文本中提取已更新的集数"""
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
    """判断集名是否有效（过滤非正式集名）"""
    if not name:
        return False
    if name in INVALID_EPISODE_NAMES:
        return False
    if re.match(r"^更新[至到]", name):
        return False
    return True


def filter_episodes(eps):
    """过滤无效集名，只保留正式播放条目"""
    return {k: v for k, v in eps.items() if is_valid_episode_name(k)}


def detect_group_by_episodes(episodes):
    """
    根据选集列表判定分类（用于混合页37）：
      - 集名含"集"字，且数量 > 2  -> Drama（电视剧）
      - 其余（HD / HD中字 / HD国语 等，1~2 项） -> Movie（电影）
    """
    names = list(episodes.keys())
    count = len(names)
    has_ji = any("集" in n for n in names)
    if has_ji and count > 2:
        return "Drama"
    return "Movie"


def insert_playlist_by_priority(playlist, new_pl):
    """按 SITE_PRIORITY 把 new_pl 插入到 playlist 的正确位置，返回插入下标"""
    new_prio = SITE_PRIORITY.get(new_pl.get("name"), 99)
    pos = len(playlist)
    for i, pl in enumerate(playlist):
        if new_prio < SITE_PRIORITY.get(pl.get("name"), 99):
            pos = i
            break
    playlist.insert(pos, new_pl)
    return pos


def merge_missing_fields(existing, rec, log=print):
    """只补全 existing 里为空的字段（不覆盖已有值）。返回是否发生修改"""
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

    old_rating = existing.setdefault("评分", {})
    new_rating = rec.get("评分", {})
    if isinstance(new_rating, dict):
        for rate_key in ["豆瓣", "IMDB"]:
            if not old_rating.get(rate_key, "") and new_rating.get(rate_key, ""):
                old_rating[rate_key] = new_rating[rate_key]
                changed = True
                log(f"      [字段更新] 补充评分「{rate_key}」: {new_rating[rate_key]}")
    return changed


# ============== 列表页解析 ==============
def get_list(list_url):
    """返回 [(name, info, detail_url, img_url), ...]"""
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

        name, _ = split_name_info(title)
        if not name:
            name = title
        items.append((name, info, urljoin(DOMAIN, href), img))
    return items


# ============== 详情页解析 ==============
def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES:
        return ""
    if is_garbled(v):
        return ""
    return v


def parse_detail_fields(detail_div):
    """解析 p.data 区域：类型/地区/年份(date)/主演/导演"""
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

    if not any([result["类型"], result["地区"], result["date"], result["主演"], result["导演"]]):
        for span in detail_div.find_all("span"):
            classes = span.get("class", []) or []
            if "split-line" in classes:
                continue
            text = span.get_text(strip=True)
            field = detect_field(text)
            if not field:
                continue
            parent = span.parent
            if not parent:
                continue
            found_span = False
            for sibling in parent.children:
                if sibling is span:
                    found_span = True
                    continue
                if not found_span:
                    continue
                if isinstance(sibling, Tag):
                    if sibling.name == "span":
                        sib_classes = sibling.get("class", []) or []
                        if "split-line" in sib_classes:
                            break
                        sib_text = sibling.get_text(strip=True)
                        if detect_field(sib_text):
                            break
                    elif sibling.name == "a":
                        assign(field, sibling.get_text(strip=True))

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
    """取剧集最多的那个云播列表，返回 {集名: 播放url}，已过滤无效集名"""
    best = {}

    # 策略1：标准播放列表 ewave-content_playlist
    for ul in soup.find_all("ul", class_=_re_class("ewave-content_playlist")):
        eps = {}
        for a in ul.select("li a[href]"):
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
        if len(eps) > len(best):
            best = eps

    if best:
        return filter_episodes(best)

    # 策略2：兜底——只从 .ewave-pannel_bd 内抓 /vodplay/ 链接
    pannel_bd = soup.find_all(class_=_re_class("ewave-pannel_bd"))
    eps = {}
    exclude_pat = re.compile(r"ewave-content_+thumb|play-btn|ewave-vodlist_+thumb")
    for bd in pannel_bd:
        for a in bd.select('a[href*="/vodplay/"]'):
            if a.find_parent(class_=exclude_pat):
                continue
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
    if eps:
        return filter_episodes(eps)

    # 策略3：全页面兜底
    eps = {}
    for a in soup.select('a[href*="/vodplay/"]'):
        if a.find_parent(class_=exclude_pat):
            continue
        name = a.get_text(strip=True)
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
    t = h1.get_text(strip=True)
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t


def extract_image_from_detail(soup):
    """从详情页提取封面图 URL"""
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
    """从详情页提取 info（pic-text 内容）"""
    thumb = soup.find(class_=_re_class("ewave-vodlist_thumb"))
    if thumb:
        pic = thumb.select_one("span.pic-text")
        if pic:
            return pic.get_text(strip=True)
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
def load_json():
    if not os.path.exists(JSON_PATH):
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def find_existing_global(data, name, sub_url, log=print):
    def normalize_name(s):
        return s.replace(" ", "").strip() if s else ""

    norm_name = normalize_name(name)

    # 1. 优先跨分类按 URL 全局检索
    if sub_url:
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                existing_urls = {item.get(k) for k in item.keys()
                                 if k == "url" or re.match(r"^url\d+$", k)}
                if sub_url in existing_urls:
                    existing_name = item.get("name", "")
                    if existing_name != name:
                        log(f"      [URL匹配去重] 发现 URL 一致但名称不同的记录 "
                            f"(URL: {sub_url}, 已有:「{existing_name}」, "
                            f"抓取:「{name}」, 所在分类:{group})")
                    return group, item

    # 2. 按【去空格名称】全局检索
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            existing_raw_name = item.get("name", "")
            existing_norm_name = normalize_name(existing_raw_name)
            if existing_norm_name == norm_name:
                log(f"      [名称去重（忽略空格）] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
                return group, item

    return None, None

def process_existing_record(existing, new_episodes, sub_url, rec, matched_group, old_max_episodes, log=print):
    """处理已存在的记录：合并字段、更新播放源和 info"""
    # ==================== 1. 字段合并与更新逻辑 ====================
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
    new_scraped_info = rec.get("info", "")

    if has_site_url:
        old_eps = {}
        old_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_eps = pl.get("episodes", {})
                old_idx = idx
                break

        if new_episodes == old_eps:
            if new_scraped_info and new_scraped_info != existing.get("info", ""):
                old_info = existing.get("info", "")
                old_ep = extract_episode_number(old_info)
                new_ep = extract_episode_number(new_scraped_info)
                if not old_info:
                    existing["info"] = new_scraped_info
                    update_time_if_needed()
                    log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
                    return "updated"
                elif old_ep is not None and new_ep is not None:
                    if new_ep > old_ep:
                        existing["info"] = new_scraped_info
                        update_time_if_needed()
                        log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
                        return "updated"
                    else:
                        log(f"      [info跳过] 新集数 {new_ep} 未超过现有 {old_ep}，"
                            f"保留原有info：「{old_info}」")
                        return "updated" if fields_updated else "no_change"
                else:
                    log(f"      [info跳过] 无法比较集数，保留原有info：「{old_info}」")
                    return "updated" if fields_updated else "no_change"
            return "updated" if fields_updated else "no_change"

        if len(new_episodes) < len(old_eps):
            return "updated" if fields_updated else "decreased"

        # 播放源有变更，更新 playlist
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        if old_idx != -1:
            playlist[old_idx] = new_pl
            
            # ===== 新增：如果 huxitech 集数大于其他所有渠道，移到第一位 =====
            hux_max = get_max_episode_number(new_episodes)
            other_max = 0
            for i, pl in enumerate(playlist):
                if i != old_idx:
                    other_max = max(other_max, get_max_episode_number(pl.get("episodes", {})))
            if hux_max > other_max and old_idx != 0:
                playlist.insert(0, playlist.pop(old_idx))
                log(f"      [排序调整] {SITE_KEY} 最大集数({hux_max}) > 其他渠道最大集数({other_max})，已移动至第一位")
        else:
            # ===== 新增：如果是新渠道且集数最大，直接插入第一位 =====
            hux_max = get_max_episode_number(new_episodes)
            other_max = max([0] + [get_max_episode_number(pl.get("episodes", {})) for pl in playlist])
            if hux_max > other_max:
                playlist.insert(0, new_pl)
                log(f"      [排序调整] {SITE_KEY} 最大集数({hux_max}) > 其他渠道最大集数({other_max})，已直接插入至第一位")
            else:
                insert_playlist_by_priority(playlist, new_pl)

        if new_scraped_info and new_scraped_info != existing.get("info", ""):
            old_info = existing.get("info", "")
            old_ep = extract_episode_number(old_info)
            new_ep = extract_episode_number(new_scraped_info)
            if not old_info:
                existing["info"] = new_scraped_info
                log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
            elif old_ep is not None and new_ep is not None:
                if new_ep > old_ep:
                    existing["info"] = new_scraped_info
                    log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
                else:
                    log(f"      [info跳过] 集数相同，保留优质原有info：「{old_info}」")

        update_time_if_needed()
        return "updated"

    else:
        # 新增渠道（按优先级插入）
        new_url_key = _ensure_site_url(existing, sub_url, force_new=True)
        playlist = existing.setdefault("playlist", [])
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        pos = insert_playlist_by_priority(playlist, new_pl)
        log(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}，"
            f"并按优先级把播放源插入至第 {pos + 1} 位")

        if new_scraped_info:
            old_info = existing.get("info", "")
            old_date = extract_info_date(old_info)
            new_date = extract_info_date(new_scraped_info)
            old_ep_count = extract_episode_count_from_info(old_info)
            should_update = False
            if not old_info:
                should_update = True
            elif new_date and (not old_date or new_date > old_date):
                should_update = True
            elif old_ep_count is not None and len(new_episodes) > old_ep_count:
                should_update = True
            if should_update and new_scraped_info != old_info:
                existing["info"] = new_scraped_info
                log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")

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
        # 1. 检查名称黑名单
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在名称黑名单中，跳过]")
            continue

        # ===== 2. 新增：检查 URL 黑名单 =====
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

            # ===== AUTO 混合页：根据选集列表判定 电影/电视剧 =====
            current_group = group
            if group == "AUTO":
                current_group = detect_group_by_episodes(new_eps)
                buf.append(f"    [自动分类] 选集共 {len(new_eps)} 项，判定为「{current_group}」")

            # ===== 集数上限过滤 =====
            MAX_EPISODES = 30
            if current_group in ("Drama", "Anime") and len(new_eps) > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」属于「{current_group}」，"
                      f"集数 {len(new_eps)} 超过 {MAX_EPISODES} 集(期) 上限 ")
                ok += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # ===== 先跨分类按 URL 全局检索（再按名称）=====
            matched_group, existing = find_existing_global(data, real_name, url, buf.append)

            effective_group = matched_group if existing else current_group
            if existing and matched_group != current_group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，"
                           f"将按「{matched_group}」规则处理（当前抓取分类为「{current_group}」）")

            # 白名单直接放行，不检查地区
            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            elif current_group in ("Anime", "Drama", "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = rec.get("地区", "")
                region_clean = region.strip()

                if any(keyword == region_clean for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    ok += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

                if region_clean in ("", "未知"):
                    cn_type_keywords = ["国产", "中国", "大陆", "内地"]
                    type_text = " ".join(rec.get("类型", []) or [])
                    matched_kw = next(
                        (kw for kw in cn_type_keywords if kw in type_text),
                        None
                    )
                    if matched_kw:
                        flush()
                        print(f"    - 跳过：地区未知，但类型「{type_text}」含"
                              f"「{matched_kw}」，判定为国产内容")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

            if existing:
                old_max_episodes = 0
                for pl in existing.get("playlist", []):
                    old_max_episodes = max(old_max_episodes, get_max_episode_number(pl.get("episodes", {})))

                has_huxitech_channel = any(
                    pl.get("name") == PLAYLIST_NAME
                    for pl in existing.get("playlist", [])
                )
                new_max = get_max_episode_number(new_eps)

                # ===== Drama/Anime 排序规则 =====
                promote_to_front = False
                insert_at = None
                if matched_group in ("Drama", "Anime"):
                    playlist_all = existing.get("playlist", [])

                    # 统计"除 huxitech 之外"的其他渠道最大集数
                    global_max = 0
                    idx_global_max = -1
                    for i, pl in enumerate(playlist_all):
                        if pl.get("name") == PLAYLIST_NAME:
                            continue
                        pl_max = get_max_episode_number(pl.get("episodes", {}))
                        if pl_max > global_max:
                            global_max = pl_max
                            idx_global_max = i
                    buf.append(f"    [{matched_group}] 其他渠道最大集数={global_max}, "
                               f"huxitech新抓取max={new_max}")
                    if new_max > global_max:
                        promote_to_front = True
                        insert_at = 0
                        buf.append(f"    [{matched_group}] huxitech({new_max}) > 其他最大"
                                   f"({global_max})，目标位置 playlist[0]")
                    elif new_max == global_max and global_max > 0:
                        promote_to_front = True
                        insert_at = idx_global_max + 1 if idx_global_max >= 0 else 0
                        buf.append(f"    [{matched_group}] huxitech({new_max}) == 其他最大"
                                   f"({global_max})，目标下标 {insert_at}")
                    elif new_max > 0:
                        promote_to_front = True
                        insert_at = idx_global_max + 1 if idx_global_max >= 0 else 0
                        buf.append(f"    [{matched_group}] huxitech({new_max}) < 其他最大"
                                   f"({global_max})，目标下标 {insert_at}")
                    else:
                        buf.append(f"    [{matched_group}] huxitech无有效集数，不调整顺序")

                if promote_to_front:
                    playlist = existing.setdefault("playlist", [])
                    hux_index = next(
                        (i for i, pl in enumerate(playlist)
                         if pl.get("name") == PLAYLIST_NAME),
                        None
                    )
                    old_hux_eps = (playlist[hux_index].get("episodes", {})
                                   if hux_index is not None else {})

                    # ---- 安全阀：新抓取比已有 huxitech 少 -> 不覆盖，防止数据丢失 ----
                    if hux_index is not None and len(new_eps) < len(old_hux_eps):
                        flush()
                        print(f"    - 忽略({matched_group})：本次抓取 {len(new_eps)} 集 少于已有 "
                              f"{len(old_hux_eps)} 集，保留原有 playlist")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

                    eps_changed = (new_eps != old_hux_eps)

                    # ---- 执行插入/移动（内部保证不会丢渠道）----
                    url_key, action = promote_huxitech_to_front(
                        existing, new_eps, url, insert_pos=insert_at
                    )

                    # ---- info：只增不减 ----
                    candidate_info = f"更新至第{new_max}集"
                    old_info = existing.get("info", "")
                    old_num = extract_episode_number(old_info)
                    info_changed = False
                    if normalize_info_text(old_info) != normalize_info_text(candidate_info):
                        if (not old_info) or (old_num is None) or (new_max > old_num):
                            existing["info"] = candidate_info
                            info_changed = True
                            buf.append(f"    [info更新] 「{old_info}」 -> 「{candidate_info}」")
                        else:
                            buf.append(f"    [info跳过] 新集数 {new_max} 未超过现有 {old_num}，"
                                       f"保留「{old_info}」")
                    else:
                        buf.append("    [info跳过] info 文本无变化，不覆盖")

                    # ---- 顺手补全空字段 ----
                    fields_changed = merge_missing_fields(existing, rec, buf.append)
                    actual_changed = (eps_changed or info_changed or fields_changed
                                      or action in ("moved", "inserted"))

                    if actual_changed:
                        if matched_group in ("Drama", "Anime"):
                            if new_max > old_max_episodes:
                                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(data)
                    flush()

                    if not actual_changed:
                        print(f"    - 无变更({matched_group})：集数、顺序、info、字段均无变化")
                        ok += 1
                    elif action == "inserted":
                        print(f"    ✅ 更新({matched_group})：huxitech 作为新渠道写入 {url_key}，"
                              f"已插入 playlist 下标 {insert_at}")
                        ok += 1
                    elif action == "moved":
                        print(f"    ✅ 更新({matched_group})：huxitech 已更新集数"
                              f"({len(old_hux_eps)} -> {len(new_eps)})，并移动到目标位置")
                        ok += 1
                    elif eps_changed:
                        print(f"    ✅ 更新({matched_group})：huxitech 已更新集数"
                              f"({len(old_hux_eps)} -> {len(new_eps)})，位置保持不变")
                        ok += 1
                    else:
                        print(f"    ✅ 更新({matched_group})：仅 info/字段发生更新")
                        ok += 1

                elif has_huxitech_channel:
                    status = process_existing_record(existing, new_eps, url, rec, matched_group, old_max_episodes, buf.append)
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
                    # ===== 无 huxitech 渠道，且未触发排序调整 =====
                    can_add = False
                    playlist_len = len(existing.get("playlist", []))
                    episode_total = len(new_eps)

                    if matched_group == "Movie":
                        if playlist_len == 1:
                            can_add = True
                            buf.append("    [Movie] 现有单一渠道，允许把 huxitech 作为新渠道插入")
                        else:
                            buf.append(f"    [Movie] 现有渠道数 {playlist_len} != 1，不插入")
                    elif matched_group == "Drama":
                        if playlist_len == 1 and episode_total < 20:
                            can_add = True
                            buf.append(f"    [Drama] 现有单一渠道，总集数{episode_total}<20，"
                                       f"允许追加huxitech渠道至末尾")
                        elif playlist_len != 1:
                            buf.append(f"    [Drama] 现有渠道数 {playlist_len} != 1，不插入")
                        else:
                            buf.append(f"    [Drama] 总集数{episode_total}≥20，不自动追加渠道")

                    if can_add:
                        new_url_key = append_huxitech_channel(existing, new_eps, url)
                        merge_missing_fields(existing, rec, buf.append)
                        if matched_group in ("Drama", "Anime"):
                            if new_max > old_max_episodes:
                                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(data)
                        flush()
                        print(f"    ✅ 更新({matched_group})：已把 {SITE_KEY} 作为新渠道写入 "
                              f"{new_url_key}，并追加到 playlist 末尾")
                        ok += 1
                    else:
                        flush()
                        print(f"    - 跳过({matched_group})：项目已存在但无 {SITE_KEY} 渠道，"
                              f"且不满足补充渠道条件，保持原样")
                        ok += 1
            else:
                # 新增记录（用生效分类）
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                data.setdefault(current_group, []).append(rec)
                print(f"    ✅ 新增 -> {current_group} (共 {len(new_eps)} 集) "
                      f"[真实名称: {real_name}] [URL: {rec['url']}]")
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
    """请求一个 huxitech 详情页，返回 (字段字典, 远程图片URL)"""
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    if detail is None:
        return None, None
    fields = parse_detail_fields(detail)
    fields["intro"] = parse_intro(soup)
    img_url = extract_image_from_detail(soup)
    return fields, img_url

def fill_empty_fields(item, fields, img_url=""):
    """只补全空字段，已有的不动。返回是否发生过修改"""
    changed = False
    if not item.get("导演") and fields.get("导演"):
        item["导演"] = fields["导演"]; changed = True
    for f in ["主演", "类型"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    for f in ["地区", "date", "intro"]:
        if not item.get(f) and fields.get(f):
            item[f] = fields[f]; changed = True
    if img_url and not item.get("image"):
        local = download_and_localize_image(img_url)
        if local:
            item["image"] = local; changed = True
    return changed

def backfill_existing(data):
    print("\n[补全模式] 扫描已有 huxitech 记录中字段缺失的资源 ...")
    total, updated = 0, 0
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            url_keys = [k for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)]
            target_url = None
            for k in url_keys:
                u = item.get(k, "")
                if u and SITE_KEY in u:
                    target_url = u
                    break
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
    data = load_json()

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
