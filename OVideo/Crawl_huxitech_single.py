# -*- coding: utf-8 -*-
"""
huxitech.com 单个详情页抓取脚本（交互式）
运行后依次输入：详情页 URL、目标分类(Movie/Drama/Show/Anime)
抓取后的新增/更新规则完全沿用 Crawl_huxitech.py
"""

import os
import re
import json
from curl_cffi import requests as cffi
import browser_cookie3
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString, Tag
from datetime import datetime

# ============== 配置（与原程序保持一致）==============
DOMAIN        = "https://www.huxitech.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "huxitech"
SITE_KEY      = "huxitech"
REQUEST_TIMEOUT = 15

# 手动单抓时是否启用「地区屏蔽」和「集数上限」限制。
# 手动指定 URL 通常表示明确要收录，故默认关闭。改为 True 可恢复原程序逻辑。
ENABLE_FILTERS = False
FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "日本"]
DRAMA_ANIME_EP_LIMIT = 30

SITE_PRIORITY = {
    "huxitech": 0,
    "chnland":  1,
    "6vdy":     2,
}

EMPTY_VALUES = {"未知", "内详", "暂无", "/"}
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
    "Referer": DOMAIN,
}

VALID_GROUPS = ["Movie", "Drama", "Show", "Anime"]

# ============== 工具函数 ==============
def extract_episode_number(info_text):
    if not info_text:
        return None
    match = re.search(r'(\d+)', info_text)
    return int(match.group(1)) if match else None


# ============== 基于 curl_cffi 的会话（伪装 Chrome 指纹）==============
# impersonate 的版本尽量贴近你真实 Chrome 大版本，可选：chrome124 / chrome131 / chrome
_session = cffi.Session(impersonate="chrome124")
_chrome_cookies = None

def _load_chrome_cookies():
    """从本机 Chrome 读取 huxitech 的 Cookie（含 cf_clearance）"""
    try:
        cj = browser_cookie3.chrome(domain_name="huxitech.com")
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
        return f"{match.group(1)}{num_to_chinese(match.group(2))}{match.group(3)}"

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
            return f"{base_name} {season_clean}", base_info
    elif base_info.endswith("季"):
        return f"{base_name} {base_info}", ""
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
    if not info:
        return None
    m = re.search(r"(20\d{6})", info)
    return m.group(1) if m else None


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
    has_ji = any("集" in n for n in names)
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
            field = detect_field(span.get_text(strip=True))
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
                        if detect_field(sibling.get_text(strip=True)):
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
    if not text:
        return ""
    m = re.search(r"剧情简介[：:]\s*(.+)", text)
    if m:
        return normalize_text(m.group(1))
    return text


def extract_episodes(soup):
    best = {}
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
            return pic.get_text(strip=True)
    return ""


def parse_subpage(sub_url, default_name="", default_info=""):
    html = fetch(sub_url)
    soup = BeautifulSoup(html, "lxml")

    real_name = parse_real_name(soup, default_name)
    detail = soup.find(class_=_re_class("ewave-content_detail"))
    fields = parse_detail_fields(detail)
    intro  = parse_intro(soup)
    episodes = extract_episodes(soup)

    info = default_info or extract_info_from_detail(soup)
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


# ============== JSON 读写与去重逻辑 ==============
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

    if sub_url:
        for group in VALID_GROUPS:
            for item in data.get(group, []):
                existing_urls = {item.get(k) for k in item.keys()
                                 if k == "url" or re.match(r"^url\d+$", k)}
                if sub_url in existing_urls:
                    existing_name = item.get("name", "")
                    if existing_name != name:
                        log(f"      [URL匹配去重] URL 一致但名称不同 "
                            f"(URL: {sub_url}, 已有:「{existing_name}」, "
                            f"抓取:「{name}」, 分类:{group})")
                    return group, item

    for group in VALID_GROUPS:
        for item in data.get(group, []):
            existing_raw_name = item.get("name", "")
            if normalize_name(existing_raw_name) == norm_name:
                log(f"      [名称去重（忽略空格）] 已有「{existing_raw_name}」 ↔ 抓取「{name}」")
                return group, item
    return None, None


def process_existing_record(existing, new_episodes, sub_url, rec, log=print):
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
            log(f"      [字段更新] 更新「date」: 「{old_date}」 -> 「{new_date}」")

    old_rating = existing.setdefault("评分", {})
    new_rating = rec.get("评分", {})
    if isinstance(new_rating, dict):
        for rate_key in ["豆瓣", "IMDB"]:
            if not old_rating.get(rate_key, "") and new_rating.get(rate_key, ""):
                old_rating[rate_key] = new_rating[rate_key]
                fields_updated = True
                log(f"      [字段更新] 补充评分「{rate_key}」: {new_rating[rate_key]}")

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
                log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")
                return "updated"
            return "updated" if fields_updated else "no_change"

        if len(new_episodes) < len(old_eps):
            return "updated" if fields_updated else "decreased"

        new_pl = {"name": PLAYLIST_NAME, "episodes": new_episodes}
        if old_idx != -1:
            playlist[old_idx] = new_pl
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
                    log(f"      [info跳过] 集数相同，保留原有：「{old_info}」")

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
        pos = insert_playlist_by_priority(playlist, new_pl)
        log(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}，"
            f"播放源插入至第 {pos + 1} 位")

        if new_scraped_info:
            old_info = existing.get("info", "")
            old_date = extract_info_date(old_info)
            new_d = extract_info_date(new_scraped_info)
            old_ep_count = extract_episode_count_from_info(old_info)
            should_update = False
            if not old_info:
                should_update = True
            elif new_d and (not old_date or new_d > old_date):
                should_update = True
            elif old_ep_count is not None and len(new_episodes) > old_ep_count:
                should_update = True
            if should_update and new_scraped_info != old_info:
                existing["info"] = new_scraped_info
                log(f"      [info更新] 「{old_info}」 -> 「{new_scraped_info}」")

        existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return "channel_added"


# ============== 交互式主流程 ==============
def ask_url():
    while True:
        url = input("\n请输入视频详情页 URL（回车退出）：").strip()
        if not url:
            return None
        if not url.startswith("http"):
            # 允许只输入 /voddetail/xxx.html 之类的相对路径
            url = urljoin(DOMAIN, url)
        return url


def ask_group():
    prompt = f"请选择分类 {VALID_GROUPS}（可输入序号 1-4 或名称）："
    mapping = {str(i + 1): g for i, g in enumerate(VALID_GROUPS)}
    while True:
        raw = input(prompt).strip()
        if raw in VALID_GROUPS:
            return raw
        if raw in mapping:
            return mapping[raw]
        print(f"  ✗ 无效输入，请输入 1-4 或 {VALID_GROUPS} 之一。")


def process_one(data, url, group):
    print(f"\n[抓取] {url}  -> 目标分类: {group}")
    buf = []

    try:
        rec = parse_subpage(url)
    except Exception as e:
        print(f"  ✗ 抓取失败: {e}")
        return

    real_name = rec["name"]
    print(f"  真实名称: {real_name}  [info: {rec.get('info')}]")

    new_eps = {}
    for pl in rec.get("playlist", []):
        if pl.get("name") == PLAYLIST_NAME:
            new_eps = pl.get("episodes", {})
            break

    if not new_eps:
        print("  ! 无播放源，终止。")
        return

    print(f"  解析到 {len(new_eps)} 个播放条目")

    # 全局去重查找
    matched_group, existing = find_existing_global(data, real_name, url, buf.append)
    effective_group = matched_group if existing else group

    if existing and matched_group != group:
        buf.append(f"    * 该资源已存在于「{matched_group}」，将按其规则处理"
                   f"（你指定的分类为「{group}」）")

    # 可选的地区 / 集数限制（默认关闭）
    if ENABLE_FILTERS:
        if not existing:
            region = (rec.get("地区") or "").strip()
            if any(kw == region for kw in FILTER_REGIONS):
                for l in buf: print(l)
                print(f"    - 跳过：地区「{region}」在过滤列表中")
                return
        if effective_group in ("Drama", "Anime") and len(new_eps) > DRAMA_ANIME_EP_LIMIT:
            for l in buf: print(l)
            print(f"    - 跳过：{effective_group} 集数 {len(new_eps)} 超过 {DRAMA_ANIME_EP_LIMIT} 上限")
            return

    if existing:
        status = process_existing_record(existing, new_eps, url, rec, buf.append)
        for l in buf: print(l)
        if status == "updated":
            print(f"    ✅ 更新({matched_group})：发现新内容，已覆盖更新")
            save_json(data)
        elif status == "channel_added":
            print(f"    ✅ 更新({matched_group})：作为新渠道插入 playlist")
            save_json(data)
        elif status == "no_change":
            print(f"    - 无变化({matched_group})：内容一致")
        elif status == "decreased":
            print(f"    - 忽略({matched_group})：抓取集数少于已有")
        elif status == "no_new":
            print(f"    - 无新增播放源({matched_group})")
        else:
            print(f"    ! 未成功更新({matched_group})：{status}")
    else:
        for l in buf: print(l)
        rec["image"] = download_and_localize_image(rec.get("image", ""))
        data.setdefault(group, []).append(rec)
        print(f"    ✅ 新增 -> {group} (共 {len(new_eps)} 集) "
              f"[名称: {real_name}] [URL: {rec['url']}]")
        save_json(data)


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    data = load_json()
    print("=" * 50)
    print("huxitech 单详情页抓取工具（输入空 URL 退出）")
    print("=" * 50)

    while True:
        url = ask_url()
        if not url:
            print("\n已退出。")
            break
        group = ask_group()
        process_one(data, url, group)
        print("\n" + "-" * 50)


if __name__ == "__main__":
    main()