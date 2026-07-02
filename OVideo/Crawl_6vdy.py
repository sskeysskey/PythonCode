# -*- coding: utf-8 -*-
"""
6vdy.org 最新剧集、最新电影、小编推荐、首页 爬取脚本
（升级版 + 防休眠 + 国产/泰国地区过滤(仅分集剧集) + 新格式兼容 + 补全模式 + 6vdy首页抓取）

新增能力：
1. 自动识别"新格式详情页"（无 ◎ 标记的纯文本字段页），并切换为新版解析逻辑。
2. 提供补全模式 backfill：python 脚本.py backfill
   - 扫描 JSON 中所有来自 6vdy 且字段缺失的记录，用新方法重抓并只补空字段（已有/正确的不动）。
3. 新增 6vdy.org 首页抓取。
4. 过滤规则变更：仅当【地区命中过滤名单】且【6vdy渠道为分集剧集(键名含"集")】时才跳过。
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
from urllib.parse import urljoin, urlparse
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
BASE_URL    = "https://www.6vdy.org/qian50m.html"
HOME_URL_6VDY = "https://www.6vdy.org/"
JSON_PATH   = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "6vdy"
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0
BLACKLIST_NAMES = ["乘风2026"]
WHITELIST_NAMES = [
    "镖人 第二季"
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "China"]
# FILTER_REGIONS = ["测试",]

# ============== 镜像站识别（同源不同域名）==============
MIRROR_DOMAINS = ("6vdy", "xb6v")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
}

# ============== 工具函数 ==============
def fetch(url, is_binary=False):
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if is_binary:
        return resp.content
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def update_movie_quality_info_if_needed(existing, new_6vdy_episodes):
    # if not new_6vdy_episodes:
    #     return False

    # old_info = existing.get("info", "")
    # lowered_old_info = old_info.upper()
    # keywords = ['TC', 'TS', '抢先', 'HC']
    # has_low_quality_keyword = any(kw in lowered_old_info for kw in keywords)

    # if not has_low_quality_keyword:
    #     return False

    # target_hd_key = None
    # for ep_name in new_6vdy_episodes.keys():
    #     if "HD" in ep_name.upper():
    #         target_hd_key = ep_name
    #         break

    # if target_hd_key:
    #     existing["info"] = target_hd_key
    #     print(f"      [画质升级更新] 检测到原 info「{old_info}」为抢先版本，"
    #           f"新源包含高清格式，info 已更新为「{target_hd_key}」")
    #     return True

    # first_new_key = list(new_6vdy_episodes.keys())[0]
    # first_new_key_upper = first_new_key.upper()
    # new_key_is_clean = not any(kw in first_new_key_upper for kw in keywords)

    # if new_key_is_clean:
    #     existing["info"] = first_new_key
    #     print(f"      [画质升级更新] 检测到原 info「{old_info}」为抢先版本，"
    #           f"新源「{first_new_key}」无抢先标识，info 已更新为「{first_new_key}」")
    #     return True

    return False


def normalize_text(s):
    if not s:
        return ""
    # 修正可能未正确闭合的 HTML 实体（兼容半角分号 ; 与 OCR/源码里的全角分号 ；）
    entity_map = {
        "&middot": "·", "&mdash": "—", "&ndash": "–",
        "&ldquo": "“", "&rdquo": "”", "&lsquo": "‘", "&rsquo": "’",
        "&iacute": "í", "&nbsp": " ", "&lrm": "", "&rlm": "",
    }
    for ent, ch in entity_map.items():
        s = s.replace(ent + ";", ch).replace(ent + "；", ch)
    # 去除方向控制符
    s = s.replace("\u200e", "").replace("\u200f", "")
    # 各类中点统一为居中点 ·
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

    bracket_match = re.search(r"^(.*?)[[［](.*?)[\]］]$", raw_title)
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


# ============== 播放列表提取 ==============
def extract_episodes(soup, base_url=BASE_URL):
    for widget in soup.select("div.widget.box.row"):
        h3 = widget.find("h3")
        if h3 and "播放地址（无需安装插件" in h3.get_text():
            eps = {}
            for a in widget.select("a.lBtn[href]"):
                href = a["href"]
                if "DownSys/play" in href:
                    ep_name = a.get_text(strip=True) or a.get("title", "").strip()
                    if ep_name:
                        eps[ep_name] = urljoin(base_url, href)
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


# ============== 新格式解析（无 ◎ 标记的纯文本字段页） ==============
JUNK_LINE_RE = re.compile(r"^[\s•·.。…\-—=\$~@®◎\u3000]*$")
INTRO_STOP_RE = re.compile(
    r"(磁\s*力|下载地址|【下载|下载|https?://|ftp://|magnet|ed2k|迅雷|thunder|\.mp4|\.mkv|BT类|本站推荐|播放地址)",
    re.I,
)


def parse_people_line(value):
    """将"A / B / C"形式的人名拆成去重列表"""
    parts = re.split(r"[/、]", value)
    out, seen = [], set()
    for p in parts:
        p = normalize_text(p)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_new_format(lines, h1_name):
    """
    解析新格式详情页（纯文本字段，无 ◎ 标记）。
    返回字段字典：info(年份)、alias、导演、编剧、主演、类型、地区、date、intro、评分。
    """
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

        # ---- 剧情简介段落 ----
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

        # 跳过纯符号行
        if JUNK_LINE_RE.match(ln):
            continue

        # ---- 字段匹配 ----
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
        # 跳过其他无关字段（语言/片长/IMDb ID/集数等）
        if re.match(r"^(?:语\s*言|片\s*长|单集片长|IMDb|集\s*数|首\s*播|季\s*数|官方网站|资\s*源|状\s*态)\s*[:：]", ln):
            continue

        # ---- 标题行（第一条内容行）：中文名 外文名（年份）[又名:...] ----
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
            # 去掉中文名得到外文名
            ali = work
            if h1_name:
                ali = work.replace(h1_name, "", 1).strip()
            title_alias = ali.strip(" /:：·").strip()
            title_found = True
            continue

    # alias 决策：优先"又名"，否则用标题外文名
    if youming:
        result["alias"] = youming
    elif title_alias:
        result["alias"] = title_alias

    # intro 清洗
    intro_text = " ".join(intro_parts).strip()
    intro_text = re.sub(r"^[\s！!·•．.　]+", "", intro_text)
    intro_text = normalize_text(intro_text)
    result["intro"] = intro_text

    return result


# ============== 子页面解析（旧格式 + 新格式自动回退） ==============
def parse_subpage(sub_url, default_name, default_info):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.select_one(".article_container h1")
    raw_title = h1.get_text(strip=True) if h1 else default_name
    name, info = split_name_info(raw_title)
    if not name:
        name = default_name
    if not info:
        info = default_info

    post = soup.select_one("#post_content")
    if not post:
        raise RuntimeError(f"子页面没有 #post_content: {sub_url}")

    # 旧格式简介与图片（注意 extract_intro 须在 parse_post_lines 之前调用）
    intro_text = extract_intro(post)

    img_url = ""
    img_tag = post.find("img")
    if img_tag and img_tag.get("src"):
        img_url = img_tag["src"]

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

    # ============ 新格式自动回退 ============
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

    # 用当前详情页 URL 作为播放链接拼接基准，兼容 xb6v 站内相对链接
    episodes = extract_episodes(soup, base_url=sub_url)
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
def load_json():
    if not os.path.exists(JSON_PATH):
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def _url_path(url):
    """提取 URL 的纯路径部分（去掉协议、域名、尾部斜杠，统一小写）"""
    if not url:
        return ""
    try:
        p = urlparse(url).path
    except Exception:
        return ""
    return p.rstrip("/").lower()


def _is_mirror(url):
    """判断该 URL 是否属于 6v 系同源镜像站"""
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(d in host for d in MIRROR_DOMAINS)


def find_existing_global(data, name, sub_url):
    # ---- 1) 名称精确匹配 ----
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            if item.get("name") == name:
                return group, item

    if sub_url:
        sub_path = _url_path(sub_url)
        sub_is_mirror = _is_mirror(sub_url)

        # ---- 2) URL 完全一致匹配 ----
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                existing_urls = {
                    item.get(k) for k in item.keys()
                    if k == "url" or re.match(r"^url\d+$", k)
                }
                if sub_url in existing_urls:
                    print(f"      [URL匹配去重] 发现 URL 一致但名称不同的记录 "
                          f"(URL: {sub_url}, 已有:「{item.get('name')}」, 抓取:「{name}」)")
                    return group, item

        # ---- 3) 同源镜像站「路径一致」匹配 ----
        #     6vdy.org 与 xb6v.com 等为同一站点的不同域名，
        #     其详情页路径(如 /dianshiju/oumeiju/28772.html)完全相同，
        #     故仅当双方都是镜像域名且 path 相同时判定为同一资源。
        if sub_is_mirror and sub_path:
            for group in ["Movie", "Drama", "Show", "Anime"]:
                for item in data.get(group, []):
                    for k in item.keys():
                        if k == "url" or re.match(r"^url\d+$", k):
                            u = item.get(k, "")
                            if _is_mirror(u) and _url_path(u) == sub_path:
                                print(f"      [镜像路径去重] 发现同源镜像路径一致的记录 "
                                      f"(路径: {sub_path}, 已有:「{item.get('name')}」@{u}, "
                                      f"抓取:「{name}」@{sub_url})")
                                return group, item

    return None, None


def extract_max_episodes_from_info(info_str):
    if not info_str:
        return 0
    match = re.search(r"(\d+)", info_str)
    if match:
        return int(match.group(1))
    return 0


def calculate_max_episodes_from_playlist(playlist):
    max_eps = 0
    if not playlist:
        return 0
    for pl in playlist:
        eps = pl.get("episodes", {})
        if isinstance(eps, dict):
            count = len(eps)
            if count > max_eps:
                max_eps = count
    return max_eps


def has_episode_concept(episodes):
    if not episodes:
        return False
    if len(episodes) >= 3:
        return True
    for key in episodes.keys():
        key_str = str(key)
        if "集" in key_str:
            return True
        if re.search(r"S.+E", key_str, re.IGNORECASE):
            return True
    return False


def update_info_field_if_needed(existing, new_playlist):
    """
    规则：
      - 唯一渠道且为 6vdy：按原逻辑，与 info 中记录的集数比较。
      - 多渠道：比较 6vdy 新抓取集数 Y 与「其他渠道中集数最多的那个」max_other，
                仅当 Y > max_other（严格大于）时才更新 info。
    """
    if not new_playlist:
        return False

    # 找到 6vdy 渠道及其集数
    vdy_pl = None
    for pl in new_playlist:
        if pl.get("name") == PLAYLIST_NAME:
            vdy_pl = pl
            break

    if vdy_pl is None:
        print(f"      [info字段跳过] playlist 中不含 6vdy 渠道，不更新 info")
        return False

    eps = vdy_pl.get("episodes", {})

    # 无集数概念（如单个电影文件）不更新
    if not has_episode_concept(eps):
        print(f"      [info字段跳过] 资源无集数概念，保持原 info「{existing.get('info', '')}」")
        return False

    Y = len(eps)                       # 6vdy 新抓取集数
    old_info = existing.get("info", "")
    X = extract_max_episodes_from_info(old_info)

    # ---- 场景一：唯一渠道且为 6vdy（原逻辑不变）----
    if len(new_playlist) == 1:
        if Y > X:
            new_info = f"更新至第{Y}集"
            existing["info"] = new_info
            print(f"      [info字段更新] playlist 仅含 6vdy，共 {Y} 集，"
                  f"info 由「{old_info}」更新为「{new_info}」")
            return True
        else:
            print(f"      [info字段未更新] 最新集数 {Y} 未大于原记录集数 {X}，保持原样")
            return False

    # ---- 场景二：多渠道，比较 6vdy 与其他渠道的最大集数 ----
    max_other = 0
    max_other_name = ""
    for pl in new_playlist:
        if pl.get("name") == PLAYLIST_NAME:
            continue
        cnt = len(pl.get("episodes", {})) if isinstance(pl.get("episodes"), dict) else 0
        if cnt > max_other:
            max_other = cnt
            max_other_name = pl.get("name", "")

    if Y > max_other:
        new_info = f"更新至第{Y}集"
        existing["info"] = new_info
        print(f"      [info字段更新] 多渠道场景下 6vdy 新集数 {Y} > 其他渠道最大集数 "
              f"{max_other}（渠道「{max_other_name}」），info 由「{old_info}」更新为「{new_info}」")
        return True
    else:
        print(f"      [info字段跳过] 多渠道场景下 6vdy 新集数 {Y} 未大于其他渠道最大集数 "
              f"{max_other}（渠道「{max_other_name}」），保持原 info「{old_info}」")
        return False


def insert_6vdy_playlist(playlist, new_pl):
    """
    将 6vdy 播放源插入到 playlist：
      - 若已存在 chnland 渠道，则紧跟在它后面；
      - 否则插入到第一位。
    """
    chnland_idx = -1
    for i, item in enumerate(playlist):
        if item.get("name") == "chnland":
            chnland_idx = i
            break
    if chnland_idx != -1:
        playlist.insert(chnland_idx + 1, new_pl)
        print(f"      [排序规则] 检测到 chnland，6vdy 已放在它后面")
    else:
        playlist.insert(0, new_pl)
        print(f"      [排序规则] 未检测到 chnland，6vdy 已放在第一位")

def should_touch_update_on_episode_change(playlist, new_6vdy_count):
    """
    集数更新场景下，判断是否刷新 update 时间戳（需求3）：
      - 现有 playlist 中【没有】chnland 渠道                    -> True
      - 存在 chnland 渠道，且【6vdy 新集数 > chnland 现有集数】 -> True
      - 其余情况                                               -> False
    """
    chnland_count = None
    for pl in playlist:
        if pl.get("name") == "chnland":
            eps = pl.get("episodes", {})
            chnland_count = len(eps) if isinstance(eps, dict) else 0
            break
    if chnland_count is None:
        return True          # 无 chnland 渠道
    return new_6vdy_count > chnland_count


def _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                             info_updated, movie_info_updated):
    """
    统一的 update 时间戳刷新决策：
      - 画质 / info 升级（movie_info_updated）→ 始终刷新（需求5）
      - 集数更新（info_updated）→ 仅当满足 chnland 规则时刷新（需求3）
    返回是否刷新。
    """
    touch = False
    if movie_info_updated:
        touch = True
    elif info_updated:
        if should_touch_update_on_episode_change(playlist, len(new_6vdy_episodes)):
            touch = True
            print("      [时间戳] 集数更新且满足 chnland 规则 → 刷新 update")
        else:
            print("      [时间戳] 集数更新但 chnland 集数 ≥ 6vdy → 保持 update 不变")
    if touch:
        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("      [字段更新] 已同步更新「update」时间戳")
    return touch

def process_existing_record(existing, new_6vdy_episodes, sub_url, rec):
    # ==================== 1. 字段合并与更新逻辑 ====================
    fields_updated = False

    normal_fields = ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]
    for field in normal_fields:
        old_val = existing.get(field)
        new_val = rec.get(field)
        is_old_empty = not old_val
        is_new_not_empty = bool(new_val)

        if is_old_empty and is_new_not_empty:
            existing[field] = new_val
            fields_updated = True
            print(f"      ✅[字段更新] 补充缺失字段「{field}」: {new_val}")

    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if new_date:
        if not old_date or len(str(new_date)) > len(str(old_date)):
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

    # ==================== 2. 播放源与URL更新逻辑 ====================
    if not new_6vdy_episodes:
        return "updated" if fields_updated else "no_new"

    url_keys = sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )

    has_6vdy_url = False
    for k in url_keys:
        val = existing.get(k, "")
        if "6vdy" in val or val == sub_url:
            has_6vdy_url = True
            break

    playlist = existing.setdefault("playlist", [])

    if has_6vdy_url:
        old_6vdy_eps = {}
        old_6vdy_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_6vdy_eps = pl.get("episodes", {})
                old_6vdy_idx = idx
                break

        if new_6vdy_episodes == old_6vdy_eps:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)
            if movie_info_updated:
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_6vdy_episodes) < len(old_6vdy_eps):
            return "updated" if fields_updated else "decreased"

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
        if old_6vdy_idx != -1:
            # 已存在 6vdy 播放源 → 原地覆盖，保持原有位置
            playlist[old_6vdy_idx] = new_pl
        else:
            # 有 6vdy 的 URL 但 playlist 里没有 6vdy 源 → 按 chnland 规则插入
            insert_6vdy_playlist(playlist, new_pl)

        info_updated = update_info_field_if_needed(existing, playlist)
        movie_info_updated = False
        if not info_updated:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)

        if _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                            info_updated, movie_info_updated):
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

        # 注意：playlist 变量仍指向原 list 对象，existing.clear() 后引用依然有效
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
        insert_6vdy_playlist(playlist, new_pl)

        print(f"      ✅[新增渠道] 已将 6vdy 写入 {new_url_key}")

        info_updated = update_info_field_if_needed(existing, playlist)
        movie_info_updated = False
        if not info_updated:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)

        if _decide_and_touch_update(existing, playlist, new_6vdy_episodes,
                            info_updated, movie_info_updated):
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
    html = fetch(BASE_URL)
    soup = BeautifulSoup(html, "lxml")
    tab_content = soup.select_one("#tab-content")
    if not tab_content:
        raise RuntimeError("找不到 #tab-content")

    uls = [ul for ul in tab_content.find_all("ul", recursive=False) if ul.find("li")]
    if len(uls) <= tab_index:
        print(f"警告：期望获取索引为 {tab_index} 的列表，但实际只找到 {len(uls)} 个有效列表")
        return []

    target_ul = uls[tab_index]
    items = []
    for a in target_ul.select("li > a[href]"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        name, info = split_name_info(title)
        items.append((name, info, urljoin(BASE_URL, href)))
    return items


def get_homepage_list_6vdy():
    """抓取 6vdy.org 首页 #post_container 中的所有条目"""
    html = fetch(HOME_URL_6VDY)
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("#post_container")
    if not container:
        raise RuntimeError("找不到 #post_container（6vdy 首页）")

    items = []
    seen = set()
    for li in container.select("li.post"):
        h2 = li.find("h2")
        a = h2.find("a", href=True) if h2 else None
        if not a:
            # 退而求其次：取缩略图链接
            a = li.select_one("a.zoom[href]")
        if not a:
            continue
        title = (a.get("title") or "").strip() or a.get_text(strip=True)
        href = a.get("href", "").strip()
        if not title or not href:
            continue
        full_url = urljoin(HOME_URL_6VDY, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        name, info = split_name_info(title)
        items.append((name, info, full_url))
    return items


# ============== 公共逐条处理逻辑（三个列表页 + 6vdy 首页 共用） ==============
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

            # 无播放源直接判为失败（提前，逻辑不变）
            if not new_6vdy_eps:
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # 先做全局查重，过滤逻辑要依赖"是否已存在"
            matched_group, existing = find_existing_global(data, real_name, url)

            # ============ 过滤规则（地区屏蔽）============
            # 放行优先级：白名单 > 已存在记录 > Anime 分类；其余才执行地区屏蔽
            if real_name in WHITELIST_NAMES:
                print(f"    ✅ 白名单放行：{real_name}，跳过地区屏蔽校验")
            elif existing is not None:
                print(f"    ✓ 已存在记录放行（{matched_group}）：跳过地区屏蔽，持续更新")
            else:
                # 新增记录：先预判分类，Anime 不做地区屏蔽
                group_guess = detect_group(
                    new_6vdy_eps, rec.get("主演", []), rec.get("类型", [])
                )
                if group_guess == "Anime":
                    print(f"    ✓ 动漫/动画分类放行：跳过地区屏蔽校验")
                else:
                    region = rec.get("地区", "")
                    region_match = any(keyword == region.strip() for keyword in FILTER_REGIONS)
                    has_episode_keyword = any("集" in str(k) for k in new_6vdy_eps.keys())

                    if region_match and has_episode_keyword:
                        print(f"    - 跳过：地区「{region}」命中过滤名单 且 为分集剧集资源（两条件同时满足）")
                        ok += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

            if existing:
                status = process_existing_record(existing, new_6vdy_eps, url, rec)
                if status == "updated":
                    print(f"    ✅ 更新({matched_group})：6vdy 渠道发现新剧集，已覆盖更新")
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
                    has_ep_kw = any("集" in str(k) for k in new_6vdy_eps.keys())
                    if has_ep_kw:
                        episode_count = len(new_6vdy_eps)
                        rec["info"] = f"更新至第{episode_count}集"
                        print(f"      [新增剧集info初始化] 自动写入 info: 「更新至第{episode_count}集」")
                    else:
                        # 无“集”字但属于剧集/动漫，且新格式可能已写入年份，仅在为空时写入播放源名
                        if not rec.get("info"):
                            first_ep_name = list(new_6vdy_eps.keys())[0]
                            rec["info"] = first_ep_name
                            print(f"      [新增无集数剧集info初始化] 自动写入 info: 「{first_ep_name}」")
                else:
                    if new_6vdy_eps and not rec.get("info"):
                        first_ep_name = list(new_6vdy_eps.keys())[0]
                        rec["info"] = first_ep_name
                        print(f"      [新增电影info初始化] 自动写入 info: 「{first_ep_name}」")

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
    items = get_list_by_tab(tab_index)
    print(f"  共发现 {len(items)} 条")
    return process_items(data, items, tab_name)


def process_homepage_6vdy(data):
    print(f"\n[抓取] 6vdy 首页 ...")
    items = get_homepage_list_6vdy()
    print(f"  共发现 {len(items)} 条")
    return process_items(data, items, "6vdy首页")


# ============== 补全模式（用新方法补全已有记录的缺失字段） ==============
def fetch_new_format_data(url):
    """请求一个 6vdy 详情页，返回 (新格式字段字典, 远程图片URL, 真实名称)"""
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")
    post = soup.select_one("#post_content")
    if not post:
        return None, None, None
    h1 = soup.select_one(".article_container h1")
    h1_text = h1.get_text(strip=True) if h1 else ""
    real_name, _ = split_name_info(h1_text) if h1_text else ("", "")

    img_tag = post.find("img")
    img_url = img_tag["src"] if (img_tag and img_tag.get("src")) else ""

    lines = parse_post_lines(post)
    nf = parse_new_format(lines, real_name or h1_text)
    return nf, img_url, real_name


def fill_empty_fields(item, nf, img_url=""):
    """只补全空字段，已有/正确的不动。返回是否发生过修改"""
    changed = False

    if not item.get("导演") and nf.get("导演"):
        item["导演"] = nf["导演"]; changed = True
    for f in ["编剧", "主演", "类型"]:
        if not item.get(f) and nf.get(f):
            item[f] = nf[f]; changed = True
    for f in ["地区", "date", "alias", "intro"]:
        if not item.get(f) and nf.get(f):
            item[f] = nf[f]; changed = True
    if not item.get("info") and nf.get("info"):
        item["info"] = nf["info"]; changed = True

    old_rating = item.setdefault("评分", {})
    nf_rating = nf.get("评分", {})
    for rk in ["豆瓣", "IMDB"]:
        if not old_rating.get(rk) and nf_rating.get(rk):
            old_rating[rk] = nf_rating[rk]; changed = True

    # 仅当原 image 为空时才补图
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
            target_url = None
            for k in url_keys:
                u = item.get(k, "")
                if u and "6vdy" in u:
                    target_url = u
                    break
            if not target_url:
                continue

            # 判断是否字段缺失（导演/编剧/主演/类型/地区/intro 全空才需要补）
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
                    print(f"    ✓ 已补全 (导演:「{item.get('导演')}」 类型:{item.get('类型')} 地区:「{item.get('地区')}」 年份:「{item.get('info')}」)")
                else:
                    print("    - 未发现可补全内容（可能该页同样缺数据）")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            time.sleep(SLEEP_BETWEEN)

    print(f"\n[补全模式] 完成：扫描 {total} 条候选，成功更新 {updated} 条。")


# ============== 主流程 ==============
def main():
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)
    data = load_json()

    # 补全模式：python 脚本.py backfill
    if len(sys.argv) > 1 and sys.argv[1] in ("backfill", "--backfill"):
        backfill_existing(data)
        print("\n====================================")
        print(f"补全任务完成! 数据已保存在 {JSON_PATH}")
        return

    # 正常抓取
    m_ok, m_fail = process_tab_unified(data, 0, "最新电影")
    d_ok, d_fail = process_tab_unified(data, 1, "最新剧集")
    r_ok, r_fail = process_tab_unified(data, 2, "小编推荐")

    # 新增：6vdy 首页抓取
    h_ok, h_fail = process_homepage_6vdy(data)

    print("\n====================================")
    print(f"所有抓取任务完成! 数据已实时安全保存在 {JSON_PATH}")


if __name__ == "__main__":
    main()