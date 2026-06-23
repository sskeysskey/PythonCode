# -*- coding: utf-8 -*-
"""
chnland.com 单个视频详情页抓取脚本
运行后输入详情页 URL（如 https://www.chnland.com/voddetail/53997.html）
再选择分类（Movie/Drama/Show/Anime），即可抓取并写入 JSON。
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
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime

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

atexit.register(stop_caffeinate)

# ============== 配置 ==============
DOMAIN        = "https://www.chnland.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "chnland"
SITE_KEY      = "chnland"
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0

# FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地"]
FILTER_REGIONS = ["测试"]

# 视为"空值"的占位文案
EMPTY_VALUES = {"未知", "内详", "暂无", "/"}

# 无效的集名（需要从 playlist 中过滤掉）
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}

# 合法分类
VALID_GROUPS = ["Movie", "Drama", "Show", "Anime"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": DOMAIN,
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


def _re_class(base):
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


# ============== 详情页解析 ==============
def _clean_val(v):
    v = normalize_text(v)
    if v in EMPTY_VALUES:
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
    best = {}

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

    pannel_bd = soup.find_all(class_=_re_class("stui-pannel_bd"))
    eps = {}
    exclude_pat = re.compile(r"stui-content_+thumb|play-btn|stui-vodlist_+thumb")
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
    thumb = soup.find(class_=_re_class("stui-content_thumb"))
    if not thumb:
        return ""
    img_tag = thumb.select_one("img[data-original]")
    if img_tag:
        return img_tag.get("data-original", "")
    img_tag = thumb.select_one("img")
    if img_tag:
        return img_tag.get("data-original", "") or img_tag.get("src", "") or ""
    a_tag = thumb.select_one("a")
    if a_tag:
        return a_tag.get("data-original", "") or ""
    return ""


def extract_info_from_detail(soup):
    thumb = soup.find(class_=_re_class("stui-content_thumb"))
    if thumb:
        pic = thumb.select_one("span.pic-text")
        if pic:
            return pic.get_text(strip=True)
    return ""


def parse_subpage(sub_url, default_name="", default_info=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    if not real_name:
        # 如果连标题都拿不到，用 URL 作兜底
        real_name = default_name or sub_url

    detail = soup.find(class_=_re_class("stui-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    info = default_info
    if not info:
        info = extract_info_from_detail(soup)

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


def find_existing_global(data, name, sub_url):
    for group in VALID_GROUPS:
        for item in data.get(group, []):
            if item.get("name") == name:
                return group, item

    if sub_url:
        for group in VALID_GROUPS:
            for item in data.get(group, []):
                existing_urls = {item.get(k) for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)}
                if sub_url in existing_urls:
                    print(f"      [URL匹配去重] 发现 URL 一致但名称不同的记录 (URL: {sub_url}, 已有:「{item.get('name')}」, 抓取:「{name}」)")
                    return group, item

    return None, None


def process_existing_record(existing, new_episodes, sub_url, rec):
    fields_updated = False

    normal_fields = ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]
    for field in normal_fields:
        old_val = existing.get(field)
        new_val = rec.get(field)
        if (not old_val) and new_val:
            existing[field] = new_val
            fields_updated = True
            print(f"      [字段更新] 补充缺失字段「{field}」: {new_val}")

    old_date = existing.get("date", "")
    new_date = rec.get("date", "")
    if new_date:
        if not old_date or len(str(new_date)) > len(str(old_date)):
            existing["date"] = new_date
            fields_updated = True
            print(f"      [字段更新] 更新「date」字段: 「{old_date}」 -> 「{new_date}」")

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
                existing["info"] = new_scraped_info
                existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_episodes) < len(old_eps):
            return "updated" if fields_updated else "decreased"

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        if old_idx != -1:
            playlist[old_idx] = new_pl
        else:
            playlist.insert(0, new_pl)

        if new_scraped_info and new_scraped_info != existing.get("info", ""):
            old_info = existing.get("info", "")
            existing["info"] = new_scraped_info
            print(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")

        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        playlist.insert(0, new_pl)

        print(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}，并将播放源插入至第一位")

        if new_scraped_info and not existing.get("info", ""):
            existing["info"] = new_scraped_info
            print(f"      [info更新] 补充 info: 「{new_scraped_info}」")

        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return "channel_added"


# ============== 交互输入 ==============
def ask_url():
    while True:
        url = input("\n请输入视频详情页的 URL（如 https://www.chnland.com/voddetail/53997.html）：\n> ").strip()
        if not url:
            print("  ! URL 不能为空，请重新输入。")
            continue
        if not url.startswith("http"):
            print("  ! URL 格式不正确，应以 http(s) 开头，请重新输入。")
            continue
        if "chnland.com" not in url:
            confirm = input("  ! 该 URL 似乎不是 chnland.com 域名，仍要继续吗？(y/N) ").strip().lower()
            if confirm != "y":
                continue
        return url


def ask_group():
    print("\n请选择该视频的分类：")
    for i, g in enumerate(VALID_GROUPS, 1):
        zh = {"Movie": "电影", "Drama": "电视剧", "Show": "综艺", "Anime": "动漫"}[g]
        print(f"  {i}. {g} ({zh})")
    while True:
        choice = input("> 请输入数字 1-4，或直接输入分类名称：").strip()
        if choice in ("1", "2", "3", "4"):
            return VALID_GROUPS[int(choice) - 1]
        # 支持直接输入名称（大小写不敏感）
        for g in VALID_GROUPS:
            if choice.lower() == g.lower():
                return g
        print("  ! 输入无效，请重新选择。")


# ============== 主流程 ==============
def main():
    start_caffeinate()
    os.makedirs(IMG_DIR, exist_ok=True)
    data = load_json()

    sub_url = ask_url()
    group = ask_group()

    print(f"\n[抓取] 目标分类：{group}")
    print(f"[抓取] 详情页：{sub_url}")

    try:
        rec = parse_subpage(sub_url)
    except Exception as e:
        print(f"  ✗ 抓取失败: {e}")
        return

    real_name = rec["name"]
    print(f"  解析到名称：{real_name}")
    print(f"  地区：{rec.get('地区', '')}  类型：{rec.get('类型', [])}")

    # ===== 地区过滤 =====
    region = rec.get("地区", "")
    if "泰国" in region:
        print(f"  - 跳过：地区为泰国（{region}），不写入。")
        return
    if any(keyword == region.strip() for keyword in FILTER_REGIONS):
        print(f"  - 跳过：地区命中过滤列表（{region}），不写入。")
        return

    # ===== 检查播放源 =====
    new_eps = {}
    for pl in rec.get("playlist", []):
        if pl.get("name") == PLAYLIST_NAME:
            new_eps = pl.get("episodes", {})
            break

    if not new_eps:
        print("  ! 无播放源，未写入。")
        return

    print(f"  共解析到 {len(new_eps)} 集。")

    # ===== 写入逻辑 =====
    matched_group, existing = find_existing_global(data, real_name, sub_url)

    if existing:
        status = process_existing_record(existing, new_eps, sub_url, rec)
        if status == "updated":
            print(f"  ✓ 更新({matched_group})：{SITE_KEY} 渠道发现新内容，已覆盖更新")
            save_json(data)
        elif status == "channel_added":
            print(f"  ✓ 更新({matched_group})：成功作为新渠道插入到 playlist 第一位")
            save_json(data)
        elif status == "no_change":
            print(f"  - 无变化({matched_group})：内容与已有记录一致")
        elif status == "decreased":
            print(f"  - 忽略({matched_group})：抓取集数少于已有集数")
        else:
            print(f"  ! 忽略({matched_group})：未成功更新")
    else:
        rec["image"] = download_and_localize_image(rec.get("image", ""))
        data.setdefault(group, []).append(rec)
        print(f"  ✓ 新增 -> {group} (共 {len(new_eps)} 集) [真实名称: {real_name}]")
        save_json(data)

    print("\n====================================")
    print(f"任务完成! 数据已保存在 {JSON_PATH}")


if __name__ == "__main__":
    main()