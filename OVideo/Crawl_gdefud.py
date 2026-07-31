# -*- coding: utf-8 -*-
"""
gdefud.com 分类页（电影/电视剧/综艺/动漫）爬取脚本
基于 Crawl_huxitech.py 改写（结构同为 stui 模板 + Cloudflare 防护）
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
DOMAIN        = "https://gdefud.com"
JSON_PATH     = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMG_DIR       = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
PLAYLIST_NAME = "gdefud"
SITE_KEY      = "gdefud"
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN  = 1.0

# 网络重试
MAX_RETRIES   = 3
RETRY_BACKOFF = 2.0     # 第 n 次失败后等待 RETRY_BACKOFF * n 秒

# 落盘节流：每 N 条变更写一次磁盘（1 = 实时写盘）
SAVE_EVERY    = 1

BLACKLIST_NAMES = ["天堂之剑", "定海神针：九尾三世劫",
                   "机甲少女破时空战记", "无名传奇", "魔彩王国历险记",
                   "阿松与阿暖", "红色珍珠", "飞越疯人院"]
# 白名单（在这里添加你要放行的名称，跳过地区屏蔽）
WHITELIST_NAMES = [
    "北斗神拳 拳王军杂兵们的挽歌", "麻辣教师第二季"
]

# 分类页 -> 分组
#   group 为 "AUTO" 时，抓完详情后根据选集列表自动判定 电影/电视剧
LIST_PAGES = [
    ("https://gdefud.com/vodshow/1--time---------2026.html", "Movie", "电影"),
    ("https://gdefud.com/vodshow/2--time---------2026.html", "Drama", "电视剧"),
    ("https://gdefud.com/vodshow/3--time---------2026.html", "Show",  "综艺"),
    ("https://gdefud.com/vodshow/4--time---------2026.html", "Anime", "动漫"),
]

FILTER_REGIONS = ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "日本"]
# 针对特定列表页的地区过滤覆盖（key = 列表页 URL，value = 该页要屏蔽的地区名单）
FILTER_REGIONS_OVERRIDE = {
    # 电影(1)：只屏蔽「泰国和中国」，其余地区全部放开
    "https://gdefud.com/vodshow/1--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国"],

    # 电视剧(2)：
    "https://gdefud.com/vodshow/2--time---------2026.html":
        ["中国", "大陆", "内地", "中国大陆", "中国内地", "泰国", "台湾", "中国台湾", "日本"],
}

# 视为"空值"的占位文案
EMPTY_VALUES = {"未知", "内详", "暂无", "/"}

# 无效的集名（需要从 playlist 中过滤掉）
INVALID_EPISODE_NAMES = {
    "立即播放", "收藏", "播放", "倒序", "正序", "排序",
    "下载", "分享", "报错", "举报", "评论",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Referer": DOMAIN,
}


# ============== 网络异常类型 ==============
class FetchError(Exception):
    pass


class NoRetryFetchError(FetchError):
    """客户端错误（403/404 等），重试无意义"""
    pass


# ============== 工具函数 ==============

def has_existing_site_url(item, target_url):
    """检查item中是否已经存在目标url（匹配url/url1/url2...）"""
    if not target_url:
        return False
    for k in item.keys():
        if k == "url" or re.match(r"^url\d+$", k):
            if item.get(k, "") == target_url:
                return True
    return False


def _url_keys_sorted(item):
    """按 url, url1, url2 ... 的顺序返回键名列表"""
    return sorted(
        [k for k in item.keys() if k == "url" or re.match(r"^url\d+$", k)],
        key=lambda x: (0, 0) if x == "url" else (1, int(re.search(r"\d+", x).group()))
    )


def _attach_url(existing, sub_url):
    """
    若 sub_url 不存在于 item 中，则分配一个新的 urlN 并保持字段顺序（插到最后一个 url 键之后），
    返回新键名；若已存在则返回 None。
    """
    if not sub_url or has_existing_site_url(existing, sub_url):
        return None

    url_keys = _url_keys_sorted(existing)
    nums = [int(re.match(r"^url(\d+)$", k).group(1))
            for k in url_keys if re.match(r"^url(\d+)$", k)]
    new_key = f"url{(max(nums) if nums else 0) + 1}"

    last = url_keys[-1] if url_keys else None
    ordered, done = {}, False
    for k, v in existing.items():
        ordered[k] = v
        if k == last:
            ordered[new_key] = sub_url
            done = True
    if not done:
        ordered[new_key] = sub_url

    existing.clear()
    existing.update(ordered)
    return new_key


# ============== 基于 curl_cffi 的会话（伪装 Chrome 指纹）==============
# impersonate 的版本尽量贴近你真实 Chrome 大版本，可选：chrome124 / chrome131 / chrome
_session = cffi.Session(impersonate="chrome")
_chrome_cookies = None

def _load_chrome_cookies():
    """从本机 Chrome 读取 gdefud 的 Cookie（含 cf_clearance）"""
    try:
        cj = browser_cookie3.chrome(domain_name="gdefud.com")
        cookies = {c.name: c.value for c in cj}
        if cookies:
            print(f">>> [Cookie] 已从 Chrome 读取 {len(cookies)} 个 cookie: "
                  f"{list(cookies.keys())}")
        else:
            print(">>> [Cookie] 未读到 gdefud 的 cookie，请先在 Chrome 里手动过一次验证并浏览一下该站")
        return cookies
    except Exception as e:
        print(f">>> [Cookie] 读取 Chrome cookie 失败: {e}")
        return {}


def fetch(url, is_binary=False):
    """带退避重试的请求；403/404 不重试"""
    global _chrome_cookies
    if _chrome_cookies is None:
        _chrome_cookies = _load_chrome_cookies()

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _session.get(
                url,
                headers=HEADERS,
                cookies=_chrome_cookies,
                timeout=REQUEST_TIMEOUT,
            )
            status = resp.status_code

            if status in (403, 404):
                if status == 403:
                    # 打印前 500 字符，判断是不是 Cloudflare 挑战页
                    print(f"    [403调试] {resp.text[:500]}")
                raise NoRetryFetchError(f"HTTP {status} (不重试): {url}")

            if status == 429 or status >= 500:
                raise FetchError(f"HTTP {status}: {url}")

            resp.raise_for_status()

            if is_binary:
                return resp.content
            if not resp.encoding or resp.encoding.lower() in ("iso-8859-1",):
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text

        except NoRetryFetchError:
            raise
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"    [重试 {attempt}/{MAX_RETRIES}] 请求失败: {e}，{wait:.1f}s 后重试")
                time.sleep(wait)

    raise last_err if last_err else FetchError(f"请求失败: {url}")


def _re_class(base):
    """
    把单下划线写法的类名转成兼容"单/双下划线"的正则。
    例如 "stui-content_detail" -> 同时匹配 stui-content_detail 和 stui-content__detail
    """
    return re.compile(r"^" + base.replace("_", "_+") + r"$")


def is_garbled(value):
    """判断是否为乱码/无效值：
       - 含 Unicode 替换字符 \ufffd (�)             -> 乱码
       - 去掉空白/常见分隔符后，全由 '?'/'？' 组成    -> 乱码
    """
    if not value:
        return False
    v = str(value)
    # 出现替换字符一律判为乱码
    if "\ufffd" in v:
        return True
    # 去掉空白与常见分隔符后判断
    stripped = re.sub(r"[\s/·,，、|\-]", "", v)
    if not stripped:
        return False
    if re.fullmatch(r"[?？]+", stripped):
        return True
    return False


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


def episodes_are_numbered(episodes):
    """判断选集是否是按 集/期 编号（用来排除电影的 HD / BD1080P / HD国语 之类）"""
    if not episodes:
        return False
    cnt = 0
    for n in episodes:
        n = n.strip()
        if re.search(r"\d+\s*[集期话話]", n) or re.fullmatch(r"第?\s*\d{1,4}\s*", n):
            cnt += 1
    # 至少一半的条目看起来像编号，才认为是连载型
    return cnt >= max(1, len(episodes) // 2)


def detect_episode_unit(episodes, fallback_info=""):
    """判断量词：期 / 集"""
    text = " ".join(episodes.keys())
    if "期" in text:
        return "期"
    if "集" in text or "话" in text or "話" in text:
        return "集"
    m = re.search(r"[集期话話]", fallback_info or "")
    if m:
        return "期" if m.group(0) == "期" else "集"
    return "集"


def info_episode_number(info):
    """从 info 里提取当前进度数字（不会把年份 2026 当集数）"""
    if not info:
        return None
    for pat in (r"更新[至到]?\s*第?\s*(\d+)\s*[集期话話]",
                r"第\s*(\d+)\s*[集期话話]",
                r"(\d+)\s*[集期话話]",
                r"更新[至到]\D*?(\d+)"):
        m = re.search(pat, info)
        if m:
            return int(m.group(1))
    return None

def same_progress_info(a, b):
    """判断两个 info 是否表达相同的更新进度（忽略 01 vs 1 之类写法差异）"""
    na = info_episode_number(a)
    nb = info_episode_number(b)
    if na is not None and nb is not None:
        return na == nb
    return normalize_text(a or "") == normalize_text(b or "")

def get_max_episode_number(episodes):
    """
    从选集字典的集名中提取最大集编号；
    若所有集名都没有可用编号，返回 0（是否兜底由调用方决定）。
    """
    max_num = 0
    for name in episodes.keys():
        m = re.search(r'(\d+)\s*[集期话話]', name)   # 优先 "第20集" / "20期"
        if not m:
            m = re.search(r'第\s*(\d+)', name)        # 其次 "第20"
        if not m:
            m = re.search(r'(\d+)', name)             # 最后任意数字
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num


def episode_progress(episodes):
    """用于渠道之间比较「谁更新得多」：
    - 如果选集是编号型(有集/期标记)，优先集号；
    - 如果是日期类等非编号选集，直接使用条目总数，避免把日期数字误判成巨大集数
    """
    if not episodes:
        return 0
    if episodes_are_numbered(episodes):
        n = get_max_episode_number(episodes)
        return n if n > 0 else len(episodes)
    else:
        # 非编号选集（例如纯日期），直接返回条目数量，不要解析里面的裸数字
        return len(episodes)


def build_progress_info(episodes, old_info=""):
    """根据选集生成「更新至第N集/期」；不适用或会造成降级时返回 None"""
    if not episodes_are_numbered(episodes):
        return None
    n = get_max_episode_number(episodes)
    if n <= 0:
        return None
    old_n = info_episode_number(old_info)
    if old_n is not None and n < old_n:
        return None                      # 不允许把 info 往回退
    return f"更新至第{n}{detect_episode_unit(episodes, old_info)}"


def merge_missing_fields(existing, rec, log=print):
    """只补空字段"""
    changed = False
    for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro", "date"]:
        new_val = rec.get(field)
        if isinstance(new_val, str):
            new_val = "" if is_garbled(new_val) else new_val.strip()
        elif isinstance(new_val, list):
            new_val = [x for x in new_val if x and not is_garbled(x)]
        if not new_val:
            continue
        if not existing.get(field):
            existing[field] = new_val
            changed = True
            log(f"    [字段补全] {field}: {new_val}")
    return changed


def promote_gdefud_to_front(existing, new_episodes, sub_url):
    """
    把 gdefud 渠道放到 playlist 首位；URL 缺失时自动补一个 urlN。
    返回 (url_key or None, action)，action ∈ {"moved", "inserted"}
    """
    url_key  = _attach_url(existing, sub_url)
    playlist = existing.setdefault("playlist", [])
    gd_index = next((i for i, pl in enumerate(playlist)
                     if pl.get("name") == PLAYLIST_NAME), None)
    if gd_index is not None:
        pl = playlist.pop(gd_index)
        pl["episodes"] = new_episodes
        playlist.insert(0, pl)
        return url_key, "moved"

    playlist.insert(0, {"name": PLAYLIST_NAME, "episodes": new_episodes})
    return url_key, "inserted"


def upsert_gdefud_channel(existing, new_episodes, sub_url):
    """
    插入/更新 gdefud 渠道，但【不改变其在 playlist 中的位置】（不置顶）。
    URL 缺失时自动补一个 urlN。
    返回 (url_key or None, action)，action ∈ {"updated", "appended"}
    """
    url_key  = _attach_url(existing, sub_url)
    playlist = existing.setdefault("playlist", [])
    for pl in playlist:
        if pl.get("name") == PLAYLIST_NAME:
            pl["episodes"] = new_episodes      # 就地更新，不动位置
            return url_key, "updated"

    playlist.append({"name": PLAYLIST_NAME, "episodes": new_episodes})
    return url_key, "appended"


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
    根据选集列表判定分类（用于 AUTO 混合页，本站暂未使用）：
      - 集名含"集"字，且数量 > 2  -> Drama（电视剧）
      - 其余（HD / HD中字 / HD国语 等，1~2 项） -> Movie（电影）
    """
    names = list(episodes.keys())
    count = len(names)
    has_ji = any("集" in n for n in names)
    if has_ji and count > 2:
        return "Drama"
    return "Movie"


# ============== 列表页解析 ==============
def get_list(list_url):
    """返回 [(name, info, detail_url, img_url), ...]"""
    html = fetch(list_url)
    soup = BeautifulSoup(html, "lxml")
    items = []
    for li in soup.select("ul.stui-vodlist li"):
        # 标题在 detail 区域
        detail = li.find(class_=_re_class("stui-vodlist_detail"))
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

        # 缩略图（a.stui-vodlist_thumb，图片在 data-original 上）
        thumb = li.find(class_=_re_class("stui-vodlist_thumb"))
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
    if is_garbled(v):        # 乱码直接丢弃
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
    desc = soup.find(id="desc")
    if not desc:
        return ""
    bd = desc.find(class_=_re_class("stui-pannel_bd"))
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
    """只抓取【云播资源】下面的选集，忽略高清资源，返回 {集名: 播放url}，已过滤无效集名"""
    # 排除缩略图 / 大播放按钮里的链接（提到函数顶部，避免作用域隐患）
    exclude_pat = re.compile(r"stui-content_+thumb|play-btn|stui-vodlist_+thumb")

    best = {}

    # 精准定位标题文字=云播资源对应的播放列表
    target_playlist_ul = None
    for head_div in soup.select(".stui-pannel_head.bottom-line.active"):
        h3_title = head_div.select_one("h3.title")
        if not h3_title:
            continue
        title_text = normalize_text(h3_title.get_text(strip=True))
        if "云播资源" in title_text:
            parent_box = head_div.find_parent(class_=_re_class("stui-pannel-box"))
            if parent_box:
                target_playlist_ul = parent_box.select_one("ul.stui-content_playlist")
            break

    # 解析云播资源下的剧集
    if target_playlist_ul:
        eps = {}
        for a in target_playlist_ul.select("li a[href]"):
            href = a.get("href", "")
            if "/vodplay/" not in href:      # 过滤「收藏/报错」之类的按钮
                continue
            if a.find_parent(class_=exclude_pat):
                continue
            name = a.get_text(strip=True)
            if name and href:
                eps[name] = urljoin(DOMAIN, href)
        if len(eps) > len(best):
            best = eps

    if best:
        return filter_episodes(best)

    # 策略2：兜底——只从 .stui-pannel_bd 内抓 /vodplay/ 链接
    pannel_bd = soup.find_all(class_=_re_class("stui-pannel_bd"))
    eps = {}
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
    detail = soup.find(class_=_re_class("stui-content_detail"))
    if not detail:
        return default_name
    h1 = detail.find("h1", class_="title")
    if not h1:
        return default_name
    # 只移除评分等附加 span，保留名字文本
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
    thumb = soup.find(class_=_re_class("stui-vodlist_thumb"))
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
    thumb = soup.find(class_=_re_class("stui-vodlist_thumb"))
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


# ============== JSON 读写（原子写 + 节流） ==============
def load_json():
    if not os.path.exists(JSON_PATH):
        return {"Movie": [], "Drama": [], "Show": [], "Anime": []}
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    """写临时文件 + os.replace 原子替换，避免中途中断损坏文件"""
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JSON_PATH)


_pending_changes = 0
_pending_data = None


def mark_dirty(data, force=False):
    """记录一次变更，达到 SAVE_EVERY 条或 force 时落盘"""
    global _pending_changes, _pending_data
    _pending_data = data
    _pending_changes += 1
    if force or _pending_changes >= SAVE_EVERY:
        save_json(data)
        _pending_changes = 0


def flush_pending():
    """程序结束（含异常退出）时把未落盘的变更写下去"""
    global _pending_changes
    if _pending_changes and _pending_data is not None:
        try:
            save_json(_pending_data)
            print(">>> [保存] 已写入未落盘的变更")
        except Exception as e:
            print(f">>> [保存失败] {e}")
        _pending_changes = 0


atexit.register(flush_pending)


# ============== 去重检索 ==============
def _year(v):
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


def find_existing_global(data, name, sub_url, rec_date=None, log=print):
    # 生成【去所有空格】的标准化名称
    def normalize_name(s):
        return s.replace(" ", "").strip() if s else ""

    norm_name = normalize_name(name)
    new_year = _year(rec_date)

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

    # 2. 按【去空格名称】全局检索（同名需年份接近，避免翻拍误合并）
    for group in ["Movie", "Drama", "Show", "Anime"]:
        for item in data.get(group, []):
            existing_raw_name = item.get("name", "")
            existing_norm_name = normalize_name(existing_raw_name)
            if existing_norm_name != norm_name:
                continue

            old_year = _year(item.get("date"))
            if old_year and new_year and abs(old_year - new_year) > 1:
                log(f"      [名称同名但年份不符] 「{existing_raw_name}」({old_year}) "
                    f"≠ 抓取「{name}」({new_year})，视为不同作品")
                continue

            log(f"      [名称去重（忽略空格）] 匹配成功：已有「{existing_raw_name}」 ↔ 抓取「{name}」")
            return group, item

    return None, None


# ============== 处理单个分类页 ==============
def process_list_page(data, list_url, group, page_name):
    print(f"\n[抓取] {page_name} -> {group}  ({list_url})")
    filter_regions = FILTER_REGIONS_OVERRIDE.get(list_url, FILTER_REGIONS)
    try:
        items = get_list(list_url)
    except Exception as e:
        print(f"  ✗ 列表抓取失败: {e}")
        return 0, 0, 0
    print(f"  共发现 {len(items)} 条")
    ok, fail, skipped = 0, 0, 0

    for idx, (name, info, url, img) in enumerate(items, 1):
        if name in BLACKLIST_NAMES:
            print(f"  ({idx}/{len(items)}) {name} [在黑名单中，跳过]")
            skipped += 1
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
                skipped += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # ===== AUTO 混合页：根据选集列表判定 电影/电视剧（本站未使用） =====
            current_group = group
            if group == "AUTO":
                current_group = detect_group_by_episodes(new_eps)
                buf.append(f"    [自动分类] 选集共 {len(new_eps)} 项，判定为「{current_group}」")

            # ===== 集数上限过滤：Drama / Anime 超过 20 集(期) 直接跳过 =====
            MAX_EPISODES = 20
            if current_group in ("Drama", "Anime") and len(new_eps) > MAX_EPISODES:
                flush()
                print(f"    - 跳过：「{real_name}」属于「{current_group}」，"
                      f"集数 {len(new_eps)} 超过 {MAX_EPISODES} 集(期) 上限 ")
                skipped += 1
                time.sleep(SLEEP_BETWEEN)
                continue

            # ===== 先跨分类按 URL 全局检索（再按名称+年份）=====
            matched_group, existing = find_existing_global(
                data, real_name, url, rec_date=rec.get("date"), log=buf.append
            )

            effective_group = matched_group if existing else current_group
            if existing and matched_group != current_group:
                buf.append(f"    * 该资源已存在于「{matched_group}」分类，"
                           f"将按「{matched_group}」规则处理（当前抓取分类为「{current_group}」）")

            # 白名单直接放行，不检查地区
            if real_name in WHITELIST_NAMES:
                buf.append(f"    白名单放行：{real_name}，跳过地区屏蔽")
            # 若 JSON 中已存在（同 URL 或同名），跳过地区限制，正常更新
            elif current_group in ("Anime", "Drama", "Movie") and existing:
                buf.append(f"    已存在记录，跳过地区屏蔽，继续更新：{real_name}")
            else:
                region = rec.get("地区", "")
                region_clean = region.strip()

                # 1) 常规：地区直接命中过滤列表
                if any(keyword == region_clean for keyword in filter_regions):
                    flush()
                    print(f"    - 跳过：地区为「{region}」，在过滤列表中")
                    skipped += 1
                    time.sleep(SLEEP_BETWEEN)
                    continue

                # 2) 地区未知（空或"未知"）时，回退到「类型」判断是否为国产内容
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
                        skipped += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

            if existing:
                new_max  = episode_progress(new_eps)
                now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # ① 先补全缺失字段
                fields_changed = merge_missing_fields(existing, rec, buf.append)

                # ①b 封面图缺失时补图
                if not existing.get("image") and rec.get("image"):
                    local = download_and_localize_image(rec["image"])
                    if local:
                        existing["image"] = local
                        fields_changed = True
                        buf.append(f"    [字段补全] image: {local}")

                playlist = existing.setdefault("playlist", [])
                gd_index = next(
                    (i for i, pl in enumerate(playlist) if pl.get("name") == PLAYLIST_NAME),
                    None
                )
                old_eps = playlist[gd_index].get("episodes", {}) if gd_index is not None else None

                # URL 是否需要补写（用于判定「有没有实际变更」）
                url_missing = not has_existing_site_url(existing, url)

                # ② 其它渠道（不含 gdefud 自己的旧数据）的最大集数
                existing_max = 0
                for pl in playlist:
                    if pl.get("name") == PLAYLIST_NAME:
                        continue
                    existing_max = max(existing_max,
                                       episode_progress(pl.get("episodes", {})))

                old_info = existing.get("info", "")

                if matched_group in ("Drama", "Anime", "Show"):
                    if new_max >= existing_max:
                        # 集数 >= 现有最大 -> 插入并置顶，同时刷新 info
                        new_info_text = build_progress_info(new_eps, old_info) or old_info

                        eps_changed  = (gd_index is None) or (old_eps != new_eps)
                        pos_changed  = (gd_index is not None and gd_index != 0)
                        info_changed = not same_progress_info(new_info_text, old_info)

                        if not (eps_changed or pos_changed or info_changed
                                or fields_changed or url_missing):
                            flush()
                            print(f"    - 无字段变更，跳过：{real_name}")
                            skipped += 1
                            time.sleep(SLEEP_BETWEEN)
                            continue

                        url_key, action = promote_gdefud_to_front(existing, new_eps, url)
                        if info_changed:
                            existing["info"] = new_info_text
                            buf.append(f"    [info更新] 「{old_info}」 -> 「{new_info_text}」")
                        existing["update"] = now_str
                        buf.append(f"    [{matched_group}] 新抓取集数 {new_max} >= 其它渠道最大 "
                                   f"{existing_max}，插入并置顶")
                        mark_dirty(data)
                        flush()
                        if action == "moved":
                            print(f"    ✅ 更新({matched_group})：gdefud 已更新并置顶到 playlist 首位"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        else:
                            print(f"    ✅ 更新({matched_group})：gdefud 作为新渠道写入 "
                                  f"{url_key or '(已有URL)'}，并置顶到 playlist 首位")
                        ok += 1
                    else:
                        # 集数不足 -> 插入但不置顶，info 不动
                        eps_changed = (gd_index is None) or (old_eps != new_eps)
                        if not (eps_changed or fields_changed or url_missing):
                            flush()
                            print(f"    - 无字段变更，跳过：{real_name}")
                            skipped += 1
                            time.sleep(SLEEP_BETWEEN)
                            continue

                        url_key, action = upsert_gdefud_channel(existing, new_eps, url)
                        existing["update"] = now_str
                        buf.append(f"    [{matched_group}] 新抓取集数 {new_max} < 其它渠道最大 "
                                   f"{existing_max}，插入但不置顶")
                        mark_dirty(data)
                        flush()
                        if action == "updated":
                            print(f"    ✅ 更新({matched_group})：gdefud 渠道已就地更新（位置不变）"
                                  f"{f'（补写 {url_key}）' if url_key else ''}")
                        else:
                            print(f"    ✅ 更新({matched_group})：gdefud 作为新渠道写入 "
                                  f"{url_key or '(已有URL)'}，追加到 playlist 末尾")
                        ok += 1

                else:
                    # ===== 电影：直接插入并置顶，info 仅在为空时补 =====
                    scraped_info = rec.get("info", "")
                    eps_changed  = (gd_index is None) or (old_eps != new_eps)
                    pos_changed  = (gd_index is not None and gd_index != 0)
                    info_changed = bool(scraped_info and not old_info)

                    if not (eps_changed or pos_changed or info_changed
                            or fields_changed or url_missing):
                        flush()
                        print(f"    - 无字段变更，跳过：{real_name}")
                        skipped += 1
                        time.sleep(SLEEP_BETWEEN)
                        continue

                    url_key, action = promote_gdefud_to_front(existing, new_eps, url)
                    if info_changed:
                        existing["info"] = scraped_info
                        buf.append(f"    [info补充] 「」 -> 「{scraped_info}」")
                    existing["update"] = now_str
                    mark_dirty(data)
                    flush()
                    if action == "moved":
                        print(f"    ✅ 更新(Movie)：gdefud 已更新并置顶到 playlist 首位"
                              f"{f'（补写 {url_key}）' if url_key else ''}")
                    else:
                        print(f"    ✅ 更新(Movie)：gdefud 作为新渠道写入 "
                              f"{url_key or '(已有URL)'}，并置顶到 playlist 首位")
                    ok += 1

            else:
                # 新增记录
                flush()
                rec["image"] = download_and_localize_image(rec.get("image", ""))
                data.setdefault(current_group, []).append(rec)
                print(f"    ✅ 新增 -> {current_group} (共 {len(new_eps)} 集) "
                      f"[真实名称: {real_name}] [URL: {rec['url']}]")
                mark_dirty(data)
                ok += 1

        except Exception as e:
            flush()
            print(f"    ✗ 抓取失败: {e}")
            fail += 1
        time.sleep(SLEEP_BETWEEN)

    # 本页处理完强制落盘一次
    mark_dirty(data, force=True)
    return ok, fail, skipped


# ============== 补全模式 ==============
def fetch_detail_data(url):
    """请求一个 gdefud 详情页，返回 (字段字典, 远程图片URL)"""
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
    print("\n[补全模式] 扫描已有 gdefud 记录中字段缺失的资源 ...")
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
                    and not item.get("intro")) or not item.get("image")
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
                    mark_dirty(data)
                    print(f"    ✅ 已补全 (导演:{item.get('导演')} 类型:{item.get('类型')} 地区:「{item.get('地区')}」)")
                else:
                    print("    - 未发现可补全内容")
            except Exception as e:
                print(f"    ✗ 失败: {e}")
            time.sleep(SLEEP_BETWEEN)

    mark_dirty(data, force=True)
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

    total_ok, total_fail, total_skip = 0, 0, 0
    for list_url, group, page_name in LIST_PAGES:
        ok, fail, skipped = process_list_page(data, list_url, group, page_name)
        total_ok   += ok
        total_fail += fail
        total_skip += skipped

    flush_pending()
    print("\n====================================")
    print(f"所有抓取任务完成! 成功 {total_ok} 条，跳过 {total_skip} 条，失败 {total_fail} 条。"
          f"数据已保存在 {JSON_PATH}")


if __name__ == "__main__":
    main()