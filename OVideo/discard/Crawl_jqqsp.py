# -*- coding: utf-8 -*-
"""
jqqsp (m.jqqsp.com) 分类页（电影/电视剧/综艺/动漫）爬取脚本
基于 chnland.py 改造，模板同为 maccms
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
from playwright.sync_api import sync_playwright
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
DOMAIN        = "https://m.jqqsp.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "jqqsp"          # 仅作站点标识保留，渠道名现在使用原站名(云播线路X)
SITE_KEY      = "jqqsp"
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0

# 综艺每个渠道保留的“最新（倒数）”集数（后续可调整）
SHOW_EPISODE_LIMIT = 5

BLACKLIST_NAMES = ["美凤有约", "红色珍珠"]
# ===================== 白名单（在这里添加你要放行的名称）
WHITELIST_NAMES = []

# 分类页 -> 分组（分组由 URL 直接决定）
LIST_PAGES = [
    ("https://m.jqqsp.com/jdvodshow/dianying--time---------.html", "Movie", "电影"),
    ("https://m.jqqsp.com/jdvodshow/dianshij--time---------.html", "Drama", "电视剧"),
    # ("https://m.jqqsp.com/jdvodshow/zongyi--time---------.html",   "Show",  "综艺"),
    ("https://m.jqqsp.com/jdvodshow/dongm--time---------.html",    "Anime", "动漫"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "日本"]
# 针对特定列表页的地区过滤覆盖（key = 列表页 URL）
FILTER_REGIONS_OVERRIDE = {
    # 电影：放开日本，其余保持屏蔽
    "https://m.jqqsp.com/jdvodshow/dianying--time---------.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "菲律宾"],

    # 电视剧：额外屏蔽台湾、日本
    "https://m.jqqsp.com/jdvodshow/dianshij--time---------.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "台湾", "中国台湾", "日本"],
}

# 视为"空值"的占位文案
EMPTY_VALUES = {"未知", "内详", "暂无", "/"}

# 无效的集名（需要从 playlist 中过滤掉）
INVALID_EPISODE_NAMES = {"立即播放", "收藏"}

SESSION = requests.Session()

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                   "Version/16.0 Mobile/15E148 Safari/604.1"),
    "Referer": DOMAIN + "/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ============== 浏览器（用于通过 JS 反爬挑战） ==============
_pw = None
_browser = None
_page = None

def init_browser():
    """惰性启动无头浏览器"""
    global _pw, _browser, _page
    if _page is not None:
        return
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=False)
    ctx = _browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="zh-CN",
        viewport={"width": 414, "height": 896},
    )
    _page = ctx.new_page()

def close_browser():
    global _pw, _browser, _page
    try:
        if _browser:
            _browser.close()
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _browser = None
    _pw = None
    _page = None

atexit.register(close_browser)

def _sync_cookies_to_session():
    """把浏览器过关后的 cookie 同步到 requests，供图片下载复用"""
    try:
        for c in _page.context.cookies():
            SESSION.cookies.set(c.get("name"), c.get("value"),
                                domain=c.get("domain"), path=c.get("path", "/"))
    except Exception:
        pass

def fetch(url, is_binary=False):
    # 图片等二进制：用 requests（cookie 已从浏览器同步过来）
    if is_binary:
        resp = SESSION.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content

    # HTML：用浏览器加载，自动执行 JS 通过反爬挑战
    init_browser()
    _page.goto(url, wait_until="domcontentloaded", timeout=REQUEST_TIMEOUT * 1000)

    # 等待挑战页自动跳转/重载后出现真实内容
    try:
        # 优先等真正的列表/详情标志元素出现
        _page.wait_for_selector(
            "ul.stui-vodlist, .stui-content__detail, .stui-content_detail",
            timeout=8000,
        )
    except Exception:
        # 兜底：多等一会儿让 JS 挑战完成
        _page.wait_for_timeout(2500)

    # ★ 详情页：依次点击所有“云播线路”标签，触发每条线路 tab-pane 的懒加载渲染
    try:
        tabs = _page.query_selector_all("a[href^='#playlist']")
        # 依据 href 去重（#playlist1 / #playlist2 ...）
        seen, targets = set(), []
        for a in tabs:
            href = a.get_attribute("href") or ""
            if href.startswith("#playlist") and href not in seen:
                seen.add(href)
                targets.append(a)

        if len(targets) > 1:
            for a in targets:
                try:
                    a.click(timeout=2000)
                    _page.wait_for_timeout(350)
                except Exception:
                    pass
            # 点完所有线路后，等一次网络空闲，确保 DOM 稳定
            try:
                _page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                _page.wait_for_timeout(500)
    except Exception:
        pass

    html = _page.content()
    _sync_cookies_to_session()
    return html

# ============== 工具函数 ==============
def extract_episode_number(info_text):
    """从 info 中提取纯数字集数，找不到返回 None"""
    if not info_text:
        return None
    match = re.search(r'(\d+)', info_text)
    return int(match.group(1)) if match else None


def _re_class(base):
    """把单下划线写法的类名转成兼容"单/双下划线"的正则。"""
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
    """从 info 文本中提取已更新的集数，找不到返回 None"""
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


def keep_latest_episodes(episodes, limit):
    """综艺：只保留最新（倒数）limit 条 episode，保持原顺序"""
    items = list(episodes.items())
    if limit and len(items) > limit:
        items = items[-limit:]
    return dict(items)


def get_latest_episode_name(channels):
    """综艺：取集数最多渠道的“最后一期”名称，作为 info"""
    best = None
    best_len = -1
    for pl in channels:
        eps = pl.get("episodes", {})
        if len(eps) > best_len:
            best_len = len(eps)
            best = eps
    if best:
        keys = list(best.keys())
        if keys:
            return keys[-1]
    return ""

def get_movie_episode_name(channels):
    """电影：取集数最多渠道的第一个 episode 名称作为 info（如 HD）"""
    best = None
    best_len = -1
    for pl in channels:
        eps = pl.get("episodes", {})
        if len(eps) > best_len:
            best_len = len(eps)
            best = eps
    if best:
        keys = list(best.keys())
        if keys:
            return keys[0]
    return ""

def max_episode_count_of_record(item):
    """一条已有记录中所有渠道的最大集数"""
    return max((len(pl.get("episodes", {})) for pl in item.get("playlist", [])), default=0)


def is_likely_different_work(existing, matched_group, new_group, new_ep_count):
    """
    需求3：跨分类且仅按名称匹配时，判断是否极可能是“同名不同作品”。
    规则：Movie(集数少) 与 Drama/Anime(集数多) 之间，
          若新抓集数 > 3 且原数据集数 < 3（或反之），判定为不同作品。
    """
    if matched_group == new_group:
        return False
    old_ep_count = max_episode_count_of_record(existing)
    movie_like = {"Movie"}
    series_like = {"Drama", "Anime"}
    if matched_group in movie_like and new_group in series_like:
        if new_ep_count > 3 and old_ep_count < 3:
            return True
    if matched_group in series_like and new_group in movie_like:
        if new_ep_count < 3 and old_ep_count > 3:
            return True
    return False


def is_our_playlist(pl):
    """判断某条 playlist 是否属于本站(jqqsp)——依据 episode 的 URL 是否包含站点标识"""
    for u in (pl.get("episodes") or {}).values():
        if u and SITE_KEY in u:
            return True
    return False


# ============== 列表页解析 ==============
def get_list(list_url):
    """返回 [(name, info, detail_url, img_url), ...]"""
    html = fetch(list_url)
    # ===== 调试 =====
    print(f"    [调试] HTML 长度: {len(html)}")
    print(f"    [调试] 是否含 stui-vodlist: {'stui-vodlist' in html}")
    print(f"    [调试] 是否含 <li: {'<li' in html}")
    # 把原始 HTML 存下来看
    with open("/tmp/jqqsp_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    # ================
    soup = BeautifulSoup(html, "lxml")
    items = []

    # 兼容 stui-vodlist / stui-vodlist__ 等各种写法，直接找所有含该类名的 ul
    lis = soup.select("ul[class*='stui-vodlist'] li")
    if not lis:
        # 再兜底：直接找所有带 h4.title 的 li
        lis = [h4.find_parent("li") for h4 in soup.select("h4.title") if h4.find_parent("li")]

    for li in lis:
        h4a = li.select_one("h4.title a[href]")
        if not h4a:
            continue
        href = h4a.get("href", "")
        title = (h4a.get("title") or h4a.get_text(strip=True)).strip()
        if not href or not title:
            continue

        thumb = li.find("a", class_=re.compile(r"stui-vodlist_+thumb"))
        info = ""
        img = ""
        if thumb:
            pic = thumb.select_one("span.pic-text")
            if pic:
                info = pic.get_text(strip=True)
            img = thumb.get("data-original", "") or thumb.get("data-src", "") or ""
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


def extract_channels(soup):
    """
    jqqsp 详情页结构说明：
      - 导航标签 ul.stui-content_playlist（<a href="#playlistN">云播线路N</a>）
      - 真实剧集列表在 div.tab-content > div#playlistN > ul.stui-content_playlist
        （<a href="jplay/xxx.html">集名</a>）

    返回 [(渠道名, {集名: url}), ...]，渠道名取自导航标签(云播线路X)。
    """
    # 1) 建立 pane id -> 渠道名 的映射
    nav_map = {}
    for ul in soup.find_all("ul", class_=_re_class("stui-content_playlist")):
        for a in ul.select("li a[href^='#']"):
            pane_id = (a.get("href", "") or "").lstrip("#")
            name = a.get_text(strip=True)
            if pane_id and name:
                nav_map[pane_id] = name

    channels = []
    tab_content = soup.find("div", class_="tab-content")
    if tab_content:
        for pane in tab_content.find_all("div", class_="tab-pane"):
            pane_id = pane.get("id", "") or ""
            cname = nav_map.get(pane_id) or pane_id or "云播线路"
            eps = {}
            for ul in pane.find_all("ul", class_=_re_class("stui-content_playlist")):
                for a in ul.select("li a[href]"):
                    href = a.get("href", "")
                    if not href or href.startswith("#"):
                        continue
                    ename = a.get_text(strip=True)
                    if ename and href:
                        eps[ename] = urljoin(DOMAIN, href)
            eps = filter_episodes(eps)
            if eps:
                channels.append((cname, eps))

    # 兜底：没有 tab-content 结构时，抓第一条有效 playlist
    if not channels:
        for ul in soup.find_all("ul", class_=_re_class("stui-content_playlist")):
            eps = {}
            for a in ul.select("li a[href]"):
                href = a.get("href", "")
                if not href or href.startswith("#"):
                    continue
                ename = a.get_text(strip=True)
                if ename and href:
                    eps[ename] = urljoin(DOMAIN, href)
            eps = filter_episodes(eps)
            if eps:
                channels.append(("云播线路", eps))
                break

    return channels


def select_channels(channels):
    """
    按需求筛选渠道：
      - 只有 1 个渠道：原样保留（名字用抓到的原名，如 "云播线路" 或 "云播线路1"）
      - 2 个及以上：若存在无编号的 "云播线路" 则丢弃它，其余（云播线路1/2/...）全部保留；
                    若某视频压根没有无编号的 "云播线路"，则全部保留（从云播线路1开始）
    """
    if len(channels) <= 1:
        return channels
    filtered = [(n, e) for (n, e) in channels if n.strip() != "云播线路"]
    return filtered if filtered else channels


def parse_real_name(soup, default_name):
    detail = soup.find(class_=_re_class("stui-content_detail"))
    if not detail:
        return default_name
    h1 = detail.find("h1", class_="title")
    if not h1:
        return default_name
    # 移除评分等 span，只保留标题文字
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

    # 渠道：抓取 -> 按规则筛选
    channels = select_channels(extract_channels(soup))

    # info：jqqsp 详情页通常无 info，优先用列表页
    info = default_info
    if not info:
        info = extract_info_from_detail(soup)

    # 封面图：优先列表页 img，其次详情页
    img_url = list_img
    if not img_url:
        img_url = extract_image_from_detail(soup)

    # 每个渠道单独作为一条 playlist（name = 原站渠道名）
    playlist = [{"name": cname, "episodes": eps} for (cname, eps) in channels]

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
    """
    返回 (group, item, match_type)
      match_type: "url" —— 按 URL 命中（同一作品）
                  "name" —— 按名称命中（可能同名不同作品）
                  None  —— 未命中
    """
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
                    return group, item, "url"

    # 2. 再按名称全局检索
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            if item.get("name") == name:
                return group, item, "name"

    return None, None, None


def _register_site_url(existing, url_keys, sub_url, log):
    """把本站 URL 登记到新的 urlN 键（插在最后一个 url 键之后，保持顺序）"""
    if len(url_keys) == 1 and "url" in existing:
        new_url_key = "url1"
    else:
        max_num = 0
        for k in url_keys:
            m = re.match(r"^url(\d+)$", k)
            if m:
                max_num = max(max_num, int(m.group(1)))
        new_url_key = f"url{max_num + 1}"

    new_ordered = {}
    last_url_key = url_keys[-1] if url_keys else None
    for k, v in existing.items():
        new_ordered[k] = v
        if k == last_url_key:
            new_ordered[new_url_key] = sub_url
    if new_url_key not in new_ordered:
        new_ordered[new_url_key] = sub_url

    existing.clear()
    existing.update(new_ordered)
    log(f"      [新增渠道] 已将 {SITE_KEY} 写入 {new_url_key}")


def process_existing_record(existing, new_channels, sub_url, rec, effective_group, log=print):
    """处理已存在的记录：合并字段、更新本站(多渠道)播放源和 info

    new_channels: [{"name": 渠道名, "episodes": {...}}, ...]（均属于本站 jqqsp）
    effective_group: 该记录所在（生效）分类，用于决定 info 计算方式
    """
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
    if not new_channels:
        return "updated" if fields_updated else "no_new"

    playlist = existing.setdefault("playlist", [])

    # 现有的本站渠道（按 URL 判定）及其在 playlist 中的位置
    old_our = {}
    old_our_idx = []
    for i, pl in enumerate(playlist):
        if is_our_playlist(pl):
            old_our[pl.get("name")] = pl.get("episodes", {})
            old_our_idx.append(i)

    # 新抓取的本站渠道
    new_our = {pl["name"]: pl["episodes"] for pl in new_channels}

    new_ep_count = max((len(e) for e in new_our.values()), default=0)
    old_ep_count = max((len(e) for e in old_our.values()), default=0)

    # 抓取前“已有数据”里所有渠道（含其他站）的最大集数
    old_max_all = max((len(pl.get("episodes", {})) for pl in playlist), default=0)

    # url 键
    url_keys = sorted(
        [k for k in existing.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )
    has_site_url = any(
        (SITE_KEY in existing.get(k, "")) or (existing.get(k, "") == sub_url)
        for k in url_keys
    )
    newly_added = not has_site_url

    # -------- 统一的 info 计算（按分类决定策略） --------
    def apply_info_update():
        """按分类计算 info，成功更新返回 True"""
        old_info = existing.get("info", "")

        if effective_group in ("Drama", "Anime"):
            # 用抓到 episode 的最大集数；仅当比“已有数据最大集数”更大才更新
            if new_ep_count > old_max_all:
                new_info = f"更新至第{new_ep_count}集"
                if new_info != old_info:
                    existing["info"] = new_info
                    log(f"      [info更新] 「{old_info}」 -> 「{new_info}」")
                    return True
            else:
                log(f"      [info跳过] 抓取最大集数 {new_ep_count} 未超过已有最大 "
                    f"{old_max_all}，保留原 info：「{old_info}」")
            return False

        if effective_group == "Show":
            # 综艺：info 用最新一期 episode 的名称
            latest = get_latest_episode_name(new_channels)
            if latest and latest != old_info:
                existing["info"] = latest
                log(f"      [info更新] 「{old_info}」 -> 「{latest}」")
                return True
            return False

        # Movie：info 用抓取到的 episode 名称（如 HD），不使用不稳定的 info 文本
        new_info = get_movie_episode_name(new_channels)
        if new_info and new_info != old_info:
            existing["info"] = new_info
            log(f"      [info更新] 「{old_info}」 -> 「{new_info}」")
            return True
        return False

    # ---------- 情况A：本站渠道内容完全一致 ----------
    if old_our and new_our == old_our:
        if newly_added:
            _register_site_url(existing, url_keys, sub_url, log)

        info_changed = apply_info_update()

        if info_changed or newly_added:
            existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if newly_added:
            return "channel_added"
        if info_changed:
            return "updated"
        return "updated" if fields_updated else "no_change"

    # ---------- 情况B：集数减少 ----------
    if old_our and new_ep_count < old_ep_count:
        return "updated" if fields_updated else "decreased"

    # ---------- 情况C：更新本站渠道 / 新增本站渠道 ----------
    old_our_idx_set = set(old_our_idx)
    other_pls = [pl for i, pl in enumerate(playlist) if i not in old_our_idx_set]

    new_pls = [{"name": pl["name"], "episodes": pl["episodes"]} for pl in new_channels]

    # 组合所有渠道，按“集数降序；集数相同本站优先；再按各自原顺序稳定排序”
    combined = []
    for idx, pl in enumerate(new_pls):
        combined.append((len(pl.get("episodes", {})), 0, idx, pl))   # 0 = 本站(优先)
    for idx, pl in enumerate(other_pls):
        combined.append((len(pl.get("episodes", {})), 1, idx, pl))   # 1 = 其他站

    combined.sort(key=lambda t: (-t[0], t[1], t[2]))

    playlist.clear()
    for _cnt, _src, _idx, pl in combined:
        playlist.append(pl)

    order_desc = "、".join(f"{pl['name']}({len(pl.get('episodes', {}))})"
                          for pl in playlist)
    log(f"      [排序] 已按集数降序重排 playlist：{order_desc}")

    # URL 登记
    if newly_added:
        _register_site_url(existing, url_keys, sub_url, log)

    # info 更新（分类感知）
    apply_info_update()

    existing["update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return "channel_added" if newly_added else "updated"


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
            print(f"  ({idx}/{len(items)}) {name} [在黑名单中，跳过]")
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

            # 本站所有渠道
            new_channels = rec.get("playlist", [])

            # 需求2：综艺——每个渠道只保留最新(倒数) SHOW_EPISODE_LIMIT 条
            if group == "Show":
                for pl in new_channels:
                    pl["episodes"] = keep_latest_episodes(
                        pl.get("episodes", {}), SHOW_EPISODE_LIMIT)

            # ★ 本站多渠道：集数多的云播线路排在前面
            new_channels.sort(key=lambda pl: -len(pl.get("episodes", {})))

            max_new_eps = max((len(pl.get("episodes", {})) for pl in new_channels), default=0)

            if not new_channels:
                flush()
                print("    ! 无播放源，跳过")
                fail += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            matched_group, existing, match_type = find_existing_global(
                data, real_name, url, buf.append)

            # 需求3：仅按名称匹配时，判断是否“同名不同作品”
            if (existing and match_type == "name"
                    and is_likely_different_work(existing, matched_group, group, max_new_eps)):
                buf.append(
                    f"    * 名称相同但判定为“不同作品”"
                    f"（已有分类:{matched_group} 集数:{max_episode_count_of_record(existing)}，"
                    f"当前分类:{group} 集数:{max_new_eps}），"
                    f"将在「{group}」中作为新记录处理")
                existing = None
                matched_group = None

            effective_group = matched_group if existing else group
            if existing and matched_group != group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，"
                           f"将按「{matched_group}」规则处理（当前抓取分类为「{group}」）")

            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            elif (group == "Anime" or group == "Drama" or group == "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = rec.get("地区", "")
                if any(keyword == region.strip() for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    ok += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

            if effective_group in ("Drama", "Anime") and max_new_eps > 30:
                flush()
                print(f"    - 跳过：{effective_group} 最大渠道集数为 {max_new_eps} 集，超过 30 集上限")
                ok += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            if existing:
                status = process_existing_record(
                    existing, new_channels, url, rec, effective_group, buf.append)
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
                flush()
                # 根据分类生成 info
                if group in ("Drama", "Anime"):
                    rec["info"] = f"更新至第{max_new_eps}集" if max_new_eps else rec.get("info", "")
                elif group == "Show":
                    latest = get_latest_episode_name(new_channels)
                    if latest:
                        rec["info"] = latest
                elif group == "Movie":
                    ename = get_movie_episode_name(new_channels)
                    if ename:
                        rec["info"] = ename
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                data.setdefault(group, []).append(rec)
                ch_names = "、".join(pl["name"] for pl in new_channels)
                print(f"    ✅ 新增 -> {group} (渠道: {ch_names}，最大 {max_new_eps} 集) "
                      f"[真实名称: {real_name}] [URL: {rec['url']}] [info: {rec.get('info','')}]")
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
    """请求一个 jqqsp 详情页，返回 (字段字典, 远程图片URL)"""
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
        director_str = " / ".join(fields["导演"]) if isinstance(fields["导演"], list) else fields["导演"]
        item["导演"] = director_str; changed = True
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
    print("\n[补全模式] 扫描已有 jqqsp 记录中字段缺失的资源 ...")
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
    # 预热：用浏览器访问首页，先通过一次 JS 挑战、拿到 cookie
    try:
        init_browser()
        fetch(DOMAIN + "/")
        print(">>> [浏览器] 已通过首页验证")
    except Exception as e:
        print(f">>> 首页预热失败: {e}")

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