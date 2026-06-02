# -*- coding: utf-8 -*-
"""
6vdy.org 最新剧集、最新电影、小编推荐爬取脚本（升级版 + 防休眠）
- 支持 OVideos.json 多 URL 格式 (url, url1, url2...)
- 跨分类全局 Name 唯一性校验 + URL 存在性双重校验
- 智能 6vdy 渠道插入与更新机制
- 智能 info 字段集数对比更新（不更新 update 字段）
- 升级版分类判定规则（支持自动分流至 Anime）
"""

import os
import re
import json
import time
import requests
import platform
import subprocess
import atexit
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

# ================= 防止系统休眠控制 =================
_caffeinate_proc = None

def start_caffeinate():
    """启动 caffeinate 以防止系统休眠 (仅限 macOS)"""
    global _caffeinate_proc
    if platform.system() == 'Darwin':
        try:
            # -i: 防止系统空闲休眠, -d: 防止显示器休眠, -m: 防止磁盘休眠, -u: 声明用户活动
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

# 注册程序退出时自动关闭，确保不会留下僵尸进程
atexit.register(stop_caffeinate)

# ============== 配置 ==============
BASE_URL    = "https://www.6vdy.org/qian50m.html"
JSON_PATH   = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "6vdy"         # 6vdy 专有播放列表名称
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0           # 每次抓取子页面后的休眠时间（秒）
BLACKLIST_NAMES = ["乘风2026"] 

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
    """
    针对无集数概念的电影项目：
    如果原 info 包含 'TC', 'TS', '抢先', 'HC' 之一，
    且新写入的播放源 episodes 的 key 中包含 'HD'，则将 info 更新为该 key。
    【新增】：如果新 key 中不含 'HD'，但新 key 本身也不含低画质关键字（如 '正片'），则也将 info 更新为新 key。
    """
    if not new_6vdy_episodes:
        return False

    old_info = existing.get("info", "")
    
    # 1. 检查原 info 是否含有抢先版关键字（忽略大小写）
    lowered_old_info = old_info.upper()
    keywords = ['TC', 'TS', '抢先', 'HC']
    has_low_quality_keyword = any(kw in lowered_old_info for kw in keywords)
    
    if not has_low_quality_keyword:
        return False

    # 2. 寻找新播放源中第一个包含 "HD" 的 key（忽略大小写）
    target_hd_key = None
    for ep_name in new_6vdy_episodes.keys():
        if "HD" in ep_name.upper():
            target_hd_key = ep_name
            break

    # 3. 如果找到了 HD 播放源，执行更新
    if target_hd_key:
        existing["info"] = target_hd_key
        print(f"      [画质升级更新] 检测到原 info「{old_info}」为抢先版本，"
              f"新源包含高清格式，info 已更新为「{target_hd_key}」")
        return True

    # 4. 【新增兜底逻辑】如果没有找到 "HD" 关键字，但新源的第一个 key 本身不包含任何低画质关键字
    first_new_key = list(new_6vdy_episodes.keys())[0]
    first_new_key_upper = first_new_key.upper()
    
    # 检查新 key 是否不含低画质关键字
    new_key_is_clean = not any(kw in first_new_key_upper for kw in keywords)
    
    if new_key_is_clean:
        existing["info"] = first_new_key
        print(f"      [画质升级更新] 检测到原 info「{old_info}」为抢先版本，"
              f"新源「{first_new_key}」无抢先标识，info 已更新为「{first_new_key}」")
        return True

    return False

def normalize_text(s):
    if not s:
        return ""
    s = s.replace("&middot;", "·").replace("·", "·")
    s = s.replace("\xa0", " ").replace("&nbsp;", " ")
    s = re.sub(r"[，；;]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(":：·•")
    return s

def num_to_chinese(num_str):
    """将 1-99 的阿拉伯数字字符串转换为中文数字"""
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
    return num_str  # 超过99则返回原样

def split_name_info(raw_title):
    raw_title = raw_title.strip()
    
    base_name = raw_title
    base_info = ""
    has_bracket = False

    # 1. 尝试匹配中括号（兼容半角 [ ] 和全角 ［ ］）
    # 匹配格式如： 浪漫的绝对值［全集］ 或 纸钞屋：柏林［第1-2季全］
    bracket_match = re.search(r"^(.*?)[[［](.*?)[\］]]$", raw_title)
    if bracket_match:
        base_name = bracket_match.group(1).strip()
        base_info = bracket_match.group(2).strip()
        has_bracket = True
    else:
        # 2. 如果没有中括号，尝试匹配空格后跟着“第X季”或“第X季全”的后缀
        # 例如："达顿牧场 第一季" 或 "驱车向前 第一季全"
        season_match = re.search(r"^(.*?)\s+((?:第[0-9一二三四五六七八九十百\-]+季)(?:全)?)$", raw_title)
        if season_match:
            base_name = season_match.group(1).strip()
            base_info = season_match.group(2).strip()

    # ==================== 新增：阿拉伯数字季数转中文数字逻辑 ====================
    # 无论是 base_name 还是 base_info，只要包含“第[0-9]+季”，就将其转换为中文数字
    def replace_season(match):
        prefix = match.group(1)  # "第"
        num = match.group(2)     # 阿拉伯数字，如 "5"
        suffix = match.group(3)  # "季"
        return f"{prefix}{num_to_chinese(num)}{suffix}"

    # 替换 base_name 中的阿拉伯数字季（例如："斗破苍穹 第5季" -> "斗破苍穹 第五季"）
    base_name = re.sub(r"(第)(\d+)(季)", replace_season, base_name)
    # 替换 base_info 中的阿拉伯数字季（例如："第5季全" -> "第五季全"）
    base_info = re.sub(r"(第)(\d+)(季)", replace_season, base_info)
    # ====================================================================

    # 如果既没有中括号，也不符合季数后缀规则，则直接返回原标题作为 name，info 为空
    if not base_info:
        return base_name, ""  # 注意：这里原代码是 raw_title，改成 base_name 可以应用上面的替换

    # 3. 根据提取出的 base_name 和 base_info 进行精细化转换
    
    # 情况 A: 括号内/后缀是 "全集"
    if base_info == "全集":
        return base_name, "全集"
        
    # 情况 C: 括号内/后缀以 "季全" 结尾 (例如 "第五季全", "第1-2季全")
    elif base_info.endswith("季全"):
        # 判断是否包含范围符号（如 1-2季、1至3季等）
        if re.search(r"[\-\d~至]", base_info):
            # 如果是多季范围（如 "第1-2季全"），不拼接，直接返回原 base_name
            return base_name, base_info
        else:
            # 如果是单季（如 "第五季全"），则拼接成 "黑袍纠察队 第五季"
            season_clean = base_info[:-1] # 去掉末尾的 "全"
            name = f"{base_name} {season_clean}"
            return name, base_info
        
    # 情况 B: 括号内/后缀以 "季" 结尾 (例如 "第五季", "第一季")
    elif base_info.endswith("季"):
        name = f"{base_name} {base_info}"
        info = ""
        return name, info

    # 其他未覆盖的括号内容情况，保留原样拆分
    return base_name, base_info


def safe_filename(url):
    return os.path.basename(url.split("?")[0])


# ============== 播放列表提取 ==============
def extract_episodes(soup):
    for widget in soup.select("div.widget.box.row"):
        h3 = widget.find("h3")
        if h3 and "播放地址（无需安装插件" in h3.get_text():
            eps = {}
            for a in widget.select("a.lBtn[href]"):
                href = a["href"]
                if "DownSys/play" in href:
                    ep_name = a.get_text(strip=True) or a.get("title", "").strip()
                    if ep_name:
                        eps[ep_name] = urljoin(BASE_URL, href)
            return eps
    return {}


# ============== 字段解析正则 ==============
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


# ============== 子页面解析 ==============
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

    episodes = extract_episodes(soup)
    playlist = []
    if episodes:
        playlist.append({"name": PLAYLIST_NAME, "episodes": episodes})

    rating = {"豆瓣": douban_score if douban_score else ""}
    if imdb_score:
        rating["IMDB"] = imdb_score

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


def find_existing_global(data, name, sub_url):
    """
    全局跨分类查找：
    1. 优先通过 name 进行匹配。
    2. 如果 name 不匹配，但新抓取的 sub_url 在已有记录的任何 url 字段 (url, url1, url2...) 中存在，也视为重复。
    返回: (分类名, 匹配到的记录字典)
    """
    # 1. 第一轮：通过 Name 匹配
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            if item.get("name") == name:
                return group, item

    # 2. 第二轮：通过 URL 匹配（解决 name 略有差别但 URL 完全一致的情况）
    if sub_url:
        for group in ["Movie", "Drama", "Show", "Anime"]:
            for item in data.get(group, []):
                # 收集该条记录所有的 url 字段值
                existing_urls = {item.get(k) for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)}
                if sub_url in existing_urls:
                    print(f"      [URL匹配去重] 发现 URL 一致但名称不同的记录 (URL: {sub_url}, 已有:「{item.get('name')}」, 抓取:「{name}」)")
                    return group, item

    return None, None


def extract_max_episodes_from_info(info_str):
    """从 info 字符串中提取出集数数字 (例如 '更新至第224集' -> 224, '28集全' -> 28)"""
    if not info_str:
        return 0
    match = re.search(r"(\d+)", info_str)
    if match:
        return int(match.group(1))
    return 0


def calculate_max_episodes_from_playlist(playlist):
    """计算当前所有 playlist 渠道中，单源最大的集数"""
    max_eps = 0
    if not playlist:
        return 0
    for pl in playlist:
        eps = pl.get("episodes", {})
        if isinstance(eps, dict):
            # 统计当前渠道的集数
            count = len(eps)
            if count > max_eps:
                max_eps = count
    return max_eps


# ==================== 新增/修改：集数概念判定辅助函数 ====================
def has_episode_concept(episodes):
    """
    判定播放列表是否符合“集”的概念：
    1. 键名中包含“集”
    2. 键名中同时包含“S”和“E”且不相邻（例如 S01E01）
    3. 播放项目总数大于等于 3
    三者符合任意一个即返回 True，否则返回 False。
    """
    if not episodes:
        return False
    
    # 条件 3：项目总数 >= 3
    if len(episodes) >= 3:
        return True

    # 遍历键名检查条件 1 和条件 2
    for key in episodes.keys():
        key_str = str(key)
        # 条件 1：包含“集”字
        if "集" in key_str:
            return True
        # 条件 2：包含不相邻的 S 和 E (不区分大小写)
        if re.search(r"S.+E", key_str, re.IGNORECASE):
            return True
            
    return False


def update_info_field_if_needed(existing, new_playlist):
    """
    智能更新 info 字段：
    1. 提取原 info 中的数字 X
    2. 计算所有渠道（合并新数据后）的最大集数 Y
    3. 只有当 Y > X 时，才更新 info。
    4. 增加判断：只有当存在“集”的概念时，才修改为“更新至第Y集”。
    """
    old_info = existing.get("info", "")
    X = extract_max_episodes_from_info(old_info)
    
    # 1. 计算合并新 playlist 后的最大集数
    Y = calculate_max_episodes_from_playlist(new_playlist)
    
    # 2. 判断是否需要更新
    if Y > X:
        # 3. 核心改进：检查播放列表是否满足“集”的概念
        has_ep_concept = False
        for pl in new_playlist:
            eps = pl.get("episodes", {})
            if has_episode_concept(eps):
                has_ep_concept = True
                break
        
        # 如果符合集数概念，则更新为“更新至第Y集”
        if has_ep_concept:
            new_info = f"更新至第{Y}集"
            existing["info"] = new_info
            print(f"      [info字段更新] 共有 {Y} 集，info由原来的「{old_info}」更新为「{new_info}」")
            return True
        else:
            # 如果没有集数概念（比如电影），通常保持原样，避免把“HD”之类的标签覆盖掉
            print(f"      [info字段跳过] 资源无集数概念，保持原 info「{old_info}」")
            return False
    else:
        print(f"      [info字段未更新] 最新集数 {Y} 未大于原记录集数 {X}，保持原样")
        return False


def process_existing_record(existing, new_6vdy_episodes, sub_url, rec):
    """
    处理已存在记录的更新逻辑：
    - 补充/更新空字段（编剧、导演、主演、类型、地区、alias、intro、评分）
    - 依据特殊规则更新 date 字段（新抓取的长度更长则更新）
    - 检查 url, url1, url2... 中是否有包含 '6vdy' 的 URL 或者当前子页面的 sub_url
    - 如果有：针对 name='6vdy' 的播放列表进行长度对比更新，不新增 urlX 字段
    - 如果没有：将 6vdy 作为新渠道插入到 playlist 的第一位，并新增 urlX 字段（紧挨着原有 url 字段下方放置）
    """
    # ==================== 1. 字段合并与更新逻辑 ====================
    fields_updated = False

    # 普通字段更新 (若原有为空，新抓取不为空，则更新)
    normal_fields = ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]
    for field in normal_fields:
        old_val = existing.get(field)
        new_val = rec.get(field)
        # 判断是否为空（支持 字符串、列表 等类型）
        is_old_empty = not old_val 
        is_new_not_empty = bool(new_val)

        if is_old_empty and is_new_not_empty:
            existing[field] = new_val
            fields_updated = True
            print(f"      [字段更新] 补充缺失字段「{field}」: {new_val}")

    # 2. date 字段特殊更新规则 (新抓取的长度更长，或原有为空，则更新)
    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if new_date:
        if not old_date or len(str(new_date)) > len(str(old_date)):
            existing["date"] = new_date
            fields_updated = True
            print(f"      [字段更新] 更新「date」字段: 「{old_date}」 -> 「{new_date}」")

    # 3. 评分字段更新 (分别检查 豆瓣 和 IMDB)
    old_rating = existing.setdefault("评分", {})
    new_rating = rec.get("评分", {})
    if isinstance(new_rating, dict):
        for rate_key in ["豆瓣", "IMDB"]:
            old_rate_val = old_rating.get(rate_key, "")
            new_rate_val = new_rating.get(rate_key, "")
            if not old_rate_val and new_rate_val:
                old_rating[rate_key] = new_rate_val
                fields_updated = True
                print(f"      [字段更新] 补充评分「{rate_key}」: {new_rate_val}")

    # ==================== 2. 播放源与URL更新逻辑 ====================
    if not new_6vdy_episodes:
        return "updated" if fields_updated else "no_new"

    # 搜集该记录所有的 url 字段
    url_keys = sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )
    
    # 5. 检查 6vdy 是否已存在于已有 url 中，或者 sub_url 是否已经存在于已有 url 中
    has_6vdy_url = False
    for k in url_keys:
        val = existing.get(k, "")
        # 如果已有 URL 包含 '6vdy' 或者完全等于当前的 sub_url，都判定为“渠道已存在”
        if "6vdy" in val or val == sub_url:
            has_6vdy_url = True
            break

    playlist = existing.setdefault("playlist", [])

    if has_6vdy_url:
        # --- 6vdy 渠道已存在：直接执行 6vdy 播放列表长度对比更新，不新增 urlX 键 ---
        old_6vdy_eps = {}
        old_6vdy_idx = -1
        for idx, pl in enumerate(playlist):
            if pl.get("name") == PLAYLIST_NAME:
                old_6vdy_eps = pl.get("episodes", {})
                old_6vdy_idx = idx
                break

        if new_6vdy_episodes == old_6vdy_eps:
            # 即使播放列表完全一致，也尝试进行一次电影画质 info 更新
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)
            if movie_info_updated:
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_6vdy_episodes) < len(old_6vdy_eps):
            return "updated" if fields_updated else "decreased"

        # 覆盖更新 6vdy 播放列表
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
        if old_6vdy_idx != -1:
            playlist[old_6vdy_idx] = new_pl
        else:
            playlist.insert(0, new_pl)

        # 智能更新 info，并捕获是否进行了更新
        info_updated = update_info_field_if_needed(existing, playlist)
        # 【新增逻辑】：如果常规集数 info 未更新，则尝试进行电影画质 info 更新
        movie_info_updated = False
        if not info_updated:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)

        if info_updated or movie_info_updated:
            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fields_updated = True
            print(f"      [字段更新] 检测到 info 变化，已同步更新「update」时间戳")

        return "updated"

    else:
        # --- 6vdy 渠道不存在：作为新渠道插入到第一位，并新增 urlX（保持顺序紧挨着） ---
        
        # 1. 确定新键名
        if len(url_keys) == 1 and "url" in existing:
            new_url_key = "url1"
        else:
            # 找出当前最大的 urlX 数字并递增
            max_num = 0
            for k in url_keys:
                m = re.match(r"^url(\d+)$", k)
                if m:
                    max_num = max(max_num, int(m.group(1)))
            new_url_key = f"url{max_num + 1}"

        # 核心逻辑：重构字典以实现“紧挨着原有的下面放置”
        new_ordered_dict = {}
        last_url_key = url_keys[-1] if url_keys else None
        
        for k, v in existing.items():
            new_ordered_dict[k] = v
            # 当写入到最后一个已有的 url 键时，立刻在后面插入新的 urlX 键
            if k == last_url_key:
                new_ordered_dict[new_url_key] = sub_url

        # 如果原本没有任何 url 键（防空保护），直接加在最前面
        if new_url_key not in new_ordered_dict:
            new_ordered_dict[new_url_key] = sub_url

        # 3. 将重构顺序后的字典写回 existing
        existing.clear()
        existing.update(new_ordered_dict)

        # 4. 插入 6vdy 播放列表到第一位
        new_pl = {"name": PLAYLIST_NAME, "episodes": new_6vdy_episodes}
        playlist.insert(0, new_pl)
        
        print(f"      [新增渠道] 已将 6vdy 写入 {new_url_key}，并将播放源插入至第一位")

        # 智能更新 info，并捕获是否进行了更新
        info_updated = update_info_field_if_needed(existing, playlist)
        # 【新增逻辑】：如果常规集数 info 未更新，则尝试进行电影画质 info 更新
        movie_info_updated = False
        if not info_updated:
            movie_info_updated = update_movie_quality_info_if_needed(existing, new_6vdy_episodes)

        if info_updated or movie_info_updated:
            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fields_updated = True
            print(f"      [字段更新] 检测到 info 变化，已同步更新「update」时间戳")

        return "channel_added"


# ==================== 修改：智能分类判定 ====================
def detect_group(episodes, actors, types):
    """
    智能分类判定：
    - 第一步：检查是否有“集”的概念（调用 has_episode_concept）
        - 如果没有 -> Movie (电影)
        - 如果有 -> 进入第二步判定（区分是动漫还是剧集）
    - 第二步：
        - 如果 '演员/主演' 字段为空，或者 '类型' 包含 '动漫'、'动画' -> Anime
        - 否则 -> Drama
    """
    if not episodes:
        return "Movie"
    
    # 第一步：检查是否有“集”的概念（包含“集”字、S.*E、或项目数>=3）
    has_ep_concept = has_episode_concept(episodes)

    if has_ep_concept:
        # 第二步：判断是否为动漫
        is_anime = False
        if not actors: # 主演为空
            is_anime = True
        else:
            # 类型里包含 动漫 或 动画
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


def process_tab_unified(data, tab_index, tab_name):
    """
    统一抓取与更新流程：
    - 详情页获取真实 name
    - 跨分类全局去重
    - 智能分流与更新
    """
    print(f"\n[抓取] {tab_name} ...")
    items = get_list_by_tab(tab_index)
    print(f"  共发现 {len(items)} 条")
    ok, fail = 0, 0

    for idx, (name, info, url) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在黑名单中，跳过]")
            continue
        
        print(f"  ({idx}/{len(items)}) {name}  [{info}]")
        try:
            # 1. 抓取子页面，获取真实数据
            rec = parse_subpage(url, name, info)
            real_name = rec["name"]
            
            # 提取 6vdy 播放列表
            new_6vdy_eps = {}
            for pl in rec.get("playlist", []):
                if pl.get("name") == PLAYLIST_NAME:
                    new_6vdy_eps = pl.get("episodes", {})
                    break

            # 如果抓取到的 6vdy 播放列表为空，则直接跳过，不下载图片
            if not new_6vdy_eps:
                print("    ! 忽略跳过：该记录未抓取到任何 6vdy 播放列表")
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # 升级版去重：传入 real_name 和当前子页面的 url
            matched_group, existing = find_existing_global(data, real_name, url)

            if existing:
                # 已存在：执行更新/插入渠道逻辑
                status = process_existing_record(existing, new_6vdy_eps, url, rec)
                if status == "updated":
                    print(f"    ✓ 更新({matched_group})：6vdy 渠道发现新剧集，已覆盖更新")
                    save_json(data)
                    ok += 1
                elif status == "channel_added":
                    print(f"    ✓ 更新({matched_group})：成功作为新渠道插入到 playlist 第一位")
                    save_json(data)
                    ok += 1
                elif status == "no_change":
                    print(f"    - 无更新({matched_group})：6vdy 渠道内容及条数无变化")
                    ok += 1
                elif status == "decreased":
                    print(f"    - 忽略({matched_group})：抓取集数少于已有集数")
                    ok += 1
                else:
                    print(f"    ! 忽略({matched_group})：未成功更新")
                    fail += 1
            else:
                # 3. 全新记录：下载图片并本地化
                img_url = rec.get("image", "")
                rec["image"] = download_and_localize_image(img_url)

                # 智能分类判定
                group = detect_group(new_6vdy_eps, rec.get("主演", []), rec.get("类型", []))
                
                # ==================== 新增：全新剧集自动写入 info 字段逻辑 ====================
                # 判断条件：
                # 1. 分类属于 Drama (剧集) 或 Anime (动漫)
                # 2. 且抓取到的 6vdy 播放列表不为空
                # 3. 且播放列表中存在含有“集”字的单集（避免把一些单集电影或特殊SP也格式化为“更新至第X集”）
                if group in ["Drama", "Anime"] and new_6vdy_eps:
                    has_episode_keyword = any("集" in str(k) for k in new_6vdy_eps.keys())
                    if has_episode_keyword:
                        episode_count = len(new_6vdy_eps)
                        rec["info"] = f"更新至第{episode_count}集"
                        print(f"      [新增剧集info初始化] 自动写入 info: 「更新至第{episode_count}集」")
                    else:
                        # 虽是 Drama/Anime 分类但无“集”字，写入第一个播放源名称
                        first_ep_name = list(new_6vdy_eps.keys())[0]
                        rec["info"] = first_ep_name
                        print(f"      [新增无集数剧集info初始化] 自动写入 info: 「{first_ep_name}」")
                else:
                    # 针对 Movie (电影) 或其他无“集”字概念的新增资源
                    if new_6vdy_eps:
                        first_ep_name = list(new_6vdy_eps.keys())[0]
                        rec["info"] = first_ep_name
                        print(f"      [新增电影info初始化] 自动写入 info: 「{first_ep_name}」")

                # 写入 JSON
                data.setdefault(group, []).append(rec)
                print(f"    ✓ 新增 -> {group} (共 {len(new_6vdy_eps)} 集) [真实名称: {real_name}] [URL: {rec['url']}]")
                save_json(data)
                ok += 1

        except Exception as e:
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    return ok, fail


# ============== 主流程 ==============
def main():
    # 在程序开始时开启防休眠
    start_caffeinate()
    
    os.makedirs(IMG_DIR, exist_ok=True)
    data = load_json()

    # 1. 抓取最新电影 (Tab 0)
    m_ok, m_fail = process_tab_unified(data, 0, "最新电影")

    # 2. 抓取最新剧集 (Tab 1)
    d_ok, d_fail = process_tab_unified(data, 1, "最新剧集")

    # 3. 抓取小编推荐 (Tab 2)
    r_ok, r_fail = process_tab_unified(data, 2, "小编推荐")
    
    print("\n====================================")
    print(f"所有抓取任务完成! 数据已实时安全保存在 {JSON_PATH}")
    # print(f"统计: 电影 成功 {m_ok}/失败 {m_fail}, 剧集 成功 {d_ok}/失败 {d_fail}, 推荐 成功 {r_ok}/失败 {r_fail}")


if __name__ == "__main__":
    main()