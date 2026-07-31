# -*- coding: utf-8 -*-
"""
chnland.com 分类页（电影/电视剧/综艺/动漫）爬取脚本
"""

import os
import re
import sys
import json
import time
import requests
import platform
import subprocess
import atexit
import urllib3   # 新增
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) #屏蔽ssl警告
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
DOMAIN        = "https://www.chnland.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "chnland"
SITE_KEY      = "chnland"
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0
BLACKLIST_NAMES = ["去火星", "返校惊魂", "白蛇传之我叫王道灵", "J Music 第二季",
                   "拳锋", "除却巫山不是云", "最后的秘密", "雪落六月"]
# ===================== 新增：白名单（在这里添加你要放行的名称）
WHITELIST_NAMES = [
    "镖人 第二季"
]

# 分类页 -> 分组（分组由 URL 直接决定，无需 detect_group）
LIST_PAGES = [
    ("https://www.chnland.com/vodshow/4--time---------2026.html",  "Anime", "动漫"),
    ("https://www.chnland.com/vodshow/3--time---------2026.html",  "Show",  "综艺"),
    ("https://www.chnland.com/vodshow/35--time---------2026.html", "Movie", "电影(35)"),
    ("https://www.chnland.com/vodshow/2--time---------2026.html",  "Drama", "电视剧"),
    ("https://www.chnland.com/vodshow/1--time---------2026.html",  "Movie", "电影(1)"),
    
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "日本"]
# 针对特定列表页的地区过滤覆盖（key = 列表页 URL，value = 该页要屏蔽的地区名单）
# 未在此字典中的页面，仍使用上面默认的 FILTER_REGIONS
FILTER_REGIONS_OVERRIDE = {
    # 电影(35)：放开「日本」，其余保持屏蔽
    "https://www.chnland.com/vodshow/35--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],

    # 电影(1)：只屏蔽「泰国和中国」，其余地区全部放开
    "https://www.chnland.com/vodshow/1--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],
    
    # 电视剧
    "https://www.chnland.com/vodshow/2--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "台湾", "中国台湾", "日本"],
}

# 视为"空值"的占位文案
EMPTY_VALUES = {"未知", "内详", "暂无", "/"}

# 无效的集名（需要从 playlist 中过滤掉）
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": DOMAIN,
}

# ============== 工具函数 ==============
def extract_episode_number(info_text):
    """
    从 info 中提取纯数字集数
    例如：
    "14集全" → 14
    "更新至第14集" →14
    "全24集" →24
    找不到返回 None
    """
    if not info_text:
        return None
    match = re.search(r'(\d+)', info_text)
    return int(match.group(1)) if match else None

def fetch(url, is_binary=False):
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if is_binary:
        return resp.content
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _re_class(base):
    """
    把单下划线写法的类名转成兼容"单/双下划线"的正则。
    例如 "stui-content_detail" -> 同时匹配 stui-content_detail 和 stui-content__detail
    """
    return re.compile(r"^" + base.replace("_", "_+") + r"$")


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

def extract_episode_count_from_info(info):
    """
    从 info 文本中提取已更新的集数。
    例如 '更新至08期' -> 8, '更新至第10集' -> 10, '全12集' -> 12
    找不到返回 None
    """
    if not info:
        return None
    # 优先匹配 '更新至...数字'
    m = re.search(r"更新[至到]\D*?(\d+)", info)
    if m:
        return int(m.group(1))
    # 兜底：匹配结尾的 '数字 + 集/期/话'
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


# ============== 列表页解析 ==============
def get_list(list_url):
    """返回 [(name, info, detail_url, img_url), ...]"""
    html = fetch(list_url)
    soup = BeautifulSoup(html, "lxml")
    items = []
    for li in soup.select("ul.stui-vodlist li"):
        h4a = li.select_one("h4.title a[href]")
        if not h4a:
            continue
        href = h4a.get("href", "")
        title = (h4a.get("title") or h4a.get_text(strip=True)).strip()
        if not href or not title:
            continue

        # 查找缩略图区域（兼容单/双下划线）
        thumb = li.find("a", class_=_re_class("stui-vodlist_thumb"))
        info = ""
        img = ""
        if thumb:
            pic = thumb.select_one("span.pic-text")
            if pic:
                info = pic.get_text(strip=True)
            # 图片：优先 <a> 上的 data-original，其次 <img> 上的 data-original
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
        """根据 span 文本判断当前字段（兼容全/半角冒号与中英文）"""
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

    # 方法1：遍历 p.data 子节点
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
                        # 有 text-muted 但不匹配已知字段，重置
                        current = None
                elif node.name == "a":
                    if current:
                        assign(current, node.get_text(strip=True))
            elif isinstance(node, NavigableString):
                if current:
                    val = _clean_val(str(node))
                    if val:
                        assign(current, val)

    # 方法2：如果方法1全部为空，尝试全局搜索 span + 后续 <a>
    if not any([result["类型"], result["地区"], result["date"], result["主演"], result["导演"]]):
        for span in detail_div.find_all("span"):
            classes = span.get("class", []) or []
            if "split-line" in classes:
                continue
            text = span.get_text(strip=True)
            field = detect_field(text)
            if not field:
                continue
            # 获取同一父级中紧随其后的 <a> 标签
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
    desc = soup.select_one("#desc")
    if not desc:
        return ""
    bd = desc.find(class_=_re_class("stui-pannel_bd"))
    p = bd.find("p") if bd else None
    if not p:
        p = desc.select_one("p.col-pd")
    if not p:
        return ""
    text = p.get_text(" ", strip=True)
    return normalize_text(text)


def extract_episodes(soup):
    """取剧集最多的那个云播列表，返回 {集名: 播放url}，已过滤无效集名"""
    best = {}

    # 策略1：标准 maccms 播放列表（兼容单/双下划线）
    for ul in soup.find_all("ul", class_=_re_class("stui-content_playlist")):
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

    # 策略2：兜底——只从 .stui-pannel_bd 内抓 /vodplay/ 链接（排除缩略图和按钮区域）
    pannel_bd = soup.find_all(class_=_re_class("stui-pannel_bd"))
    eps = {}
    exclude_pat = re.compile(r"stui-content_+thumb|play-btn|stui-vodlist_+thumb")
    for bd in pannel_bd:
        for a in bd.select('a[href*="/vodplay/"]'):
            # 排除在 stui-content_thumb 或 play-btn 内的链接
            if a.find_parent(class_=exclude_pat):
                continue
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
    if eps:
        return filter_episodes(eps)

    # 策略3：全页面兜底（但排除已知非集名区域）
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
    detail = soup.find(class_=_re_class("stui-content_detail"))
    if not detail:
        return default_name
    h1 = detail.find("h1", class_="title")
    if not h1:
        return default_name
    for sp in h1.find_all("span"):
        sp.extract()
    t = h1.get_text(strip=True)
    if not t:
        return default_name
    name, _ = split_name_info(t)
    return name or t


def extract_image_from_detail(soup):
    """从详情页提取封面图 URL（兼容单/双下划线）"""
    thumb = soup.find(class_=_re_class("stui-content_thumb"))
    if not thumb:
        return ""
    # 优先找 <img> 的 data-original
    img_tag = thumb.select_one("img[data-original]")
    if img_tag:
        return img_tag.get("data-original", "")
    # 其次找任何 <img> 的 src
    img_tag = thumb.select_one("img")
    if img_tag:
        return img_tag.get("data-original", "") or img_tag.get("src", "") or ""
    # 最后尝试 <a> 的 data-original
    a_tag = thumb.select_one("a")
    if a_tag:
        return a_tag.get("data-original", "") or ""
    return ""


def extract_info_from_detail(soup):
    """从详情页提取 info（pic-text 内容，兼容单/双下划线）"""
    thumb = soup.find(class_=_re_class("stui-content_thumb"))
    if thumb:
        pic = thumb.select_one("span.pic-text")
        if pic:
            return pic.get_text(strip=True)
    return ""


def parse_subpage(sub_url, default_name, default_info, list_img=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    detail = soup.find(class_=_re_class("stui-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    # info：优先列表页，其次详情页
    info = default_info
    if not info:
        info = extract_info_from_detail(soup)

    # 封面图：优先列表页 img，其次详情页
    img_url = list_img
    if not img_url:
        img_url = extract_image_from_detail(soup)

    playlist = []
    if episodes:
        playlist.append({"name": PLAYLIST_NAME, "episodes": episodes})

    # 将导演列表转换为 " / " 分隔的字符串，若为空则保持空字符串
    director_str = " / ".join(fields["导演"]) if fields["导演"] else ""

    return {
        "name":   real_name,
        "url":    sub_url,
        "info":   info,
        "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":  img_url,
        "导演":   director_str,        # <--- 改为字符串
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
    # 1. 优先跨分类按 URL 全局检索
    if sub_url:
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                existing_urls = {item.get(k) for k in item.keys()
                                 if k == "url" or re.match(r"^url\d+$", k)}
                if sub_url in existing_urls:
                    if item.get("name") != name:
                        log(f"      [URL匹配去重] 发现 URL 一致但名称不同的记录 "
                            f"(URL: {sub_url}, 已有:「{item.get('name')}」, "
                            f"抓取:「{name}」, 所在分类:{group})")
                    return group, item

    # 2. 再按名称全局检索
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            if item.get("name") == name:
                return group, item

    return None, None


def process_existing_record(existing, new_episodes, sub_url, rec, matched_group, log=print):
    """处理已存在的记录：合并字段、更新播放源和info"""
    # ==================== 1. 字段合并与更新逻辑 ====================
    fields_updated = False

    normal_fields = ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]
    for field in normal_fields:
        old_val = existing.get(field)
        new_val = rec.get(field)
        if (not old_val) and new_val:
            existing[field] = new_val
            fields_updated = True
            log(f"      [字段更新] 补充缺失字段「{field}」: {new_val}")

    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if new_date:
        if not old_date or len(str(new_date)) > len(str(old_date)):
            existing["date"] = new_date
            fields_updated = True
            log(f"      [字段更新] 更新「date」字段: 「{old_date}」 -> 「{new_date}」")

    old_rating = existing.setdefault("评分", {})
    new_rating = rec.get("评分", {})
    if isinstance(new_rating, dict):
        for rate_key in ["豆瓣", "IMDB"]:
            old_rate_val = old_rating.get(rate_key, "")
            new_rate_val = new_rating.get(rate_key, "")
            if not old_rate_val and new_rate_val:
                old_rating[rate_key] = new_rate_val
                fields_updated = True
                log(f"      [字段更新] 补充评分「{rate_key}」: {new_rate_val}")

    # ==================== 2. 播放源与URL更新逻辑 ====================
    if not new_episodes:
        return "updated" if fields_updated else "no_new"

    url_keys = sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

    has_site_url = False
    for k in url_keys:
        val = existing.get(k, "")
        if SITE_KEY in val or val == sub_url:
            has_site_url = True
            break

    playlist = existing.setdefault("playlist", [])
    new_scraped_info = rec.get("info", "")
    new_ep_count = len(new_episodes)

    # 计算其他渠道最大集数（排除当前chnland）
    max_other_ep = 0
    other_pl_list = []
    chnland_old_idx = -1
    for idx, pl in enumerate(playlist):
        pl_name = pl.get("name", "")
        pl_eps = pl.get("episodes", {})
        if pl_name == PLAYLIST_NAME:
            chnland_old_idx = idx
        else:
            other_pl_list.append(pl)
            ep_num = len(pl_eps)
            if ep_num > max_other_ep:
                max_other_ep = ep_num

    if has_site_url:
        old_eps = {}
        old_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_eps = pl.get("episodes", {})
                old_idx = idx
                break

        # ==========【新增Movie特殊逻辑开始】==========
        # 获得当前这条记录所在分组，existing是data[group]里的对象，我们需要从上层调用传入matched_group，这里做一点兼容：
        # 注意：原函数没有传入matched_group，这里要修改函数入参！
        # ！！重要：你需要修改函数定义增加参数 matched_group，往下看完整函数签名
        # 对比新旧episode的url集合，忽略key(集名标签)
        old_url_set = set(old_eps.values())
        new_url_set = set(new_episodes.values())
        # 仅Movie分类，url完全相同，但key(集名)不一样
        if matched_group == "Movie" and old_url_set and new_url_set and (old_url_set == new_url_set) and (old_eps.keys() != new_episodes.keys()):
            log(f"      [Movie防护] 播放URL全部未变化，仅集名标签变更，不覆盖episodes、不修改info")
            log(f"        -> 旧标签:{list(old_eps.keys())}  新抓取标签:{list(new_episodes.keys())}")
            # 即使网站info变成HD，也拒绝修改，直接返回no_change
            return "no_change"
        # ==========【新增Movie特殊逻辑结束】==========

        if new_episodes == old_eps:
            # 集数内容完全相同，但可能 info 有变化
            if new_scraped_info and new_scraped_info != existing.get("info", ""):
                # 校验：新 info 声称的集数是否真的有对应 episode 存在
                claimed = extract_episode_count_from_info(new_scraped_info)
                if claimed is not None and claimed > len(new_episodes):
                    # info 声称的集数 > 实际抓到的集数，
                    # 说明网站只更新了文案，真正的 episode 并未出现 —— 不更新 info，也不打印
                    log(f"      [info跳过] info 声称 {claimed} 集，但实际仅抓到 "
                        f"{len(new_episodes)} 集，判定为虚假更新，保留原 info：「{existing.get('info', '')}」")
                    return "updated" if fields_updated else "no_change"

                old_info = existing.get("info", "")
                existing["info"] = new_scraped_info
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_episodes) < len(old_eps):
            return "updated" if fields_updated else "decreased"

        # 播放源有变更，更新 playlist
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        # 移除原有chnland条目
        if old_idx != -1:
            del playlist[old_idx]

        # 判断是否比其他所有渠道集数更多，决定放第一位还是原位
        chnland_on_top = new_ep_count > max_other_ep
        if chnland_on_top:
            playlist.insert(0, new_pl)
            log(f"      [排序] chnland集数({new_ep_count})大于其他渠道最大({max_other_ep})，置顶playlist")
        else:
            # 放回原来删除的位置
            playlist.insert(old_idx, new_pl)

        # ==================== info 更新 ====================
        if chnland_on_top:
            # chnland 已成为集数最多的渠道 → info 以「实际抓到的集数」为准
            actual_info = f"更新至第{new_ep_count}集"
            old_info = existing.get("info", "")
            if actual_info != old_info:
                existing["info"] = actual_info
                log(f"      [info更新] 「{old_info}」 -> 「{actual_info}」（按实际集数 {new_ep_count}）")
        elif new_scraped_info and new_scraped_info != existing.get("info", ""):
            # 非置顶：沿用原有的「优质info不被覆盖」逻辑
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

        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return "updated"

    else:
        # 新增渠道
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

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        # 新增渠道时对比集数，决定插入位置
        chnland_on_top = new_ep_count > max_other_ep
        if chnland_on_top:
            playlist.insert(0, new_pl)
            log(f"      [排序] 新增chnland集数({new_ep_count})大于其他渠道最大({max_other_ep})，置顶playlist")
        else:
            playlist.append(new_pl)

        log(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}")

        if chnland_on_top:
            # chnland 已成为集数最多的渠道 → info 以「实际抓到的集数」为准
            actual_info = f"更新至第{new_ep_count}集"
            old_info = existing.get("info", "")
            if actual_info != old_info:
                existing["info"] = actual_info
                log(f"      [info更新] 「{old_info}」 -> 「{actual_info}」（按实际集数 {new_ep_count}）")
        elif new_scraped_info:
            # 非置顶：沿用原有更新逻辑
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

        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return "channel_added"


# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    # 取出当前列表页对应的地区过滤名单（有覆盖用覆盖，没有则用默认）
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
            print(f"  ({idx}/{len(items)}) {name} [在黑名单中，跳过]")
            continue

        # 该条记录的所有日志先暂存到 buf，最后再决定是否打印
        header = f"  ({idx}/{len(items)}) {name}  [{info}]"
        buf = []

        def flush():
            """把表头和缓冲日志真正打印出来"""
            print(header)
            for line in buf:
                print(line)

        try:
            rec = parse_subpage(url, name, info, list_img=img)
            real_name = rec["name"]

            # 先解析播放源
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

            # ===== 先跨分类按 URL 全局检索（再按名称）=====
            matched_group, existing = find_existing_global(data, real_name, url, buf.append)

            # 生效分类：命中已有记录则以其所在分类为准，否则用当前抓取分类
            effective_group = matched_group if existing else group
            if existing and matched_group != group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，"
                           f"将按「{matched_group}」规则处理（当前抓取分类为「{group}」）")

            # 白名单直接放行，不检查地区
            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            # 动漫：若 JSON 中已存在（同 URL 或同名），跳过地区限制，正常更新
            elif (group == "Anime" or group == "Drama" or group == "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                # 不在白名单（且非"已存在的动漫"）才执行地区过滤
                region = rec.get("地区", "")
                if any(keyword == region.strip() for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    ok += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

            # ===== 电视剧/动漫集数超过 30 则跳过：按生效分类 =====
            if effective_group in ("Drama", "Anime") and len(new_eps) > 30:
                flush()
                print(f"    - 跳过：{effective_group} 集数为 {len(new_eps)} 集，超过 30 集上限")
                ok += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            if existing:
                status = process_existing_record(existing, new_eps, url, rec, matched_group, buf.append)
                if status == "updated":
                    buf.append(f"    ✅ 更新({matched_group})：{SITE_KEY} 渠道发现新内容，已覆盖更新")
                    save_json(data)
                    flush()
                    ok += 1
                elif status == "channel_added":
                    buf.append(f"    ✅ 更新({matched_group})：成功作为新渠道插入到 playlist 第一位")
                    save_json(data)
                    flush()
                    ok += 1
                elif status == "no_change":
                    # 【屏蔽】集数与已有内容一致，整条记录（含表头）都不显示
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
                # 新增记录（用当前抓取分类）
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                data.setdefault(group, []).append(rec)
                print(f"    ✅ 新增 -> {group} (共 {len(new_eps)} 集) "
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
    """请求一个 chnland 详情页，返回 (字段字典, 远程图片URL)"""
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    detail = soup.find(class_=_re_class("stui-content_detail"))
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
    print("\n[补全模式] 扫描已有 chnland 记录中字段缺失的资源 ...")
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