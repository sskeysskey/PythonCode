import json
import os
import time
import re
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup
from curl_cffi import requests as c_requests
import ssl
from urllib3.util.ssl_ import create_urllib3_context
from urllib.parse import urljoin, urlparse

# ===================== 配置（和原代码一致） =====================
VERBOSE_LOG = False
PROTECTED_SOURCES = {"xb6v", "6vdy", "chnland"}  # 从 pdy0.py 引入 chnland
EXCLUDED_SOURCES = {"非凡", "牛牛", "无尽", "奇异", "猫眼", "ikun"}
DETAIL_BASE_URL = "https://www.pys2.com"
OUTPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_REQUESTS = 1.0
RETRY_TIMES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

IMAGE_PROXY_TEMPLATES = [
    "https://images.weserv.nl/?url={host_and_path}",
    "https://wsrv.nl/?url={host_and_path}",
]

_std_session = requests.Session()
_tls_session = requests.Session()

class TLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        except:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

_tls_session.mount("https://", TLSAdapter())
http_session = c_requests.Session(impersonate="chrome", http_version=1)

# ===================== 工具函数 =====================
def log(message: str, force: bool = False):
    if force or VERBOSE_LOG:
        print(message)

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def clean_ws(s):
    return re.sub(r"\s+", " ", s).strip()

def format_date_str(date_str: str) -> str:
    if not date_str:
        return date_str
    if '/' in date_str or '／' in date_str:
        parts = re.split(r'[/／]', date_str)
        date_str = parts[-1].strip()
    try:
        parts = re.findall(r'\d+', date_str)
        if len(parts) >= 3:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        elif len(parts) == 2:
            return f"{parts[0]}-{parts[1].zfill(2)}"
        elif len(parts) == 1:
            return parts[0]
    except:
        pass
    return date_str

def get_url_path(url: str) -> str:
    try:
        return urlparse(url).path
    except:
        return url

def extract_video_id(url: str, name: str) -> str:
    m = re.search(r"/(?:mv|vod|detail)/(\d+)", url)
    if m:
        return m.group(1)
    safe = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", name).strip("_")
    return safe or "unknown"

def fetch(url: str) -> str | None:
    for i in range(RETRY_TIMES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text
            print(f"[HTTP {resp.status_code}] {url}")
        except Exception as e:
            print(f"[Error {i+1}] {url} -> {e}")
            time.sleep(2)
    return None

def get_all_url_keys(item: dict) -> list[str]:
    """返回条目中所有 url 相关的 key，按 url, url1, url2... 顺序排列。"""
    keys = [k for k in item.keys()
            if k == "url" or (k.startswith("url") and k[3:].isdigit())]

    def _sort_key(k):
        return -1 if k == "url" else int(k[3:])

    return sorted(keys, key=_sort_key)

def is_all_urls_protected(item: dict) -> bool:
    """
    判断一个条目的所有 url（url/url1/url2...）是否仅来自受保护域名
    （chnland.com 或 6vdy.org）。
      - 至少要有一个有效（非空）url
      - 任意一个 url 不属于受保护域名，则返回 False
    """
    PROTECTED_URL_DOMAINS = ("chnland.com", "6vdy.org")
    url_keys = get_all_url_keys(item)
    if not url_keys:
        return False
    has_valid = False
    for k in url_keys:
        val = item.get(k, "")
        if not val:
            continue
        has_valid = True
        if not any(dom in val for dom in PROTECTED_URL_DOMAINS):
            return False
    return has_valid

# ===================== 封面下载（和原代码一致） =====================
def download_cover(img_url: str, video_id: str) -> str:
    if not img_url:
        return ""
    ensure_dir(COVER_IMAGE_DIR)
    base = img_url.split("?")[0].split("#")[0]
    ext = os.path.splitext(base)[1].lower()
    if ext not in ALLOWED_IMG_EXT:
        ext = ".jpg"
    filename = f"{video_id}{ext}"
    filepath = os.path.join(COVER_IMAGE_DIR, filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return filename

    headers = dict(HEADERS)
    headers["Referer"] = DETAIL_BASE_URL
    headers["Connection"] = "close"
    url_candidates = [img_url]
    if img_url.startswith("https://"):
        url_candidates.append("http://" + img_url[8:])
    elif img_url.startswith("http://"):
        url_candidates.append("https://" + img_url[7:])

    def _save(content):
        if not content or len(content) < 200:
            return False
        with open(filepath, "wb") as f:
            f.write(content)
        return os.path.getsize(filepath) > 0

    for url in url_candidates:
        try:
            resp = c_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, impersonate="chrome", verify=False)
            if resp.status_code == 200 and _save(resp.content):
                print(f"[封面] {filename}")
                return filename
        except:
            pass

    parsed = urlparse(img_url)
    hp = parsed.netloc + parsed.path + (f"?{parsed.query}" if parsed.query else "")
    for proxy in IMAGE_PROXY_TEMPLATES:
        purl = proxy.format(host_and_path=hp)
        try:
            resp = c_requests.get(purl, headers=headers, timeout=REQUEST_TIMEOUT*2, impersonate="chrome", verify=False)
            if resp.status_code == 200 and _save(resp.content):
                print(f"[封面(代理)] {filename}")
                return filename
        except:
            pass

    for url in url_candidates:
        try:
            resp = _tls_session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, verify=False)
            if resp.status_code == 200 and _save(resp.content):
                return filename
        except:
            pass
    return ""

# ===================== 播放列表解析 =====================
def parse_playlist(soup):
    # 兼容多种页面结构：
    #   旧结构：使用 #url-content1（"在线观看"区块）作为容器
    #   新结构：无"在线观看"字段，直接使用 .playlist-box（"播放列表"）
    online = (soup.select_one("#url-content1")
              or soup.select_one(".playlist-box")
              or soup)

    tabs = online.select(".playlist-tab li.swiper-slide")
    if not tabs:
        return []

    allowed = []
    excluded = []
    for tab in tabs:
        target = tab.get("data-target", "")
        if not target:                 # 跳过没有 data-target 的占位 slide
            continue
        name = ""
        for c in tab.contents:         # 取直接文本节点，避免混入 badge 角标数字
            if isinstance(c, str) and c.strip():
                name = c.strip()
                break
        if not name:
            name = tab.get_text(strip=True)
        name = name.replace('"', "").replace("“", "").replace("”", "").strip()

        ul = online.find("ul", id=target.lstrip("#"))
        eps = {}
        if ul:
            for a in ul.select("li a"):
                h = a.get("href")
                t = a.get_text(strip=True)
                if h and t:
                    eps[t] = urljoin(DETAIL_BASE_URL, h)
        if eps:
            item = {"name": name, "episodes": eps}
            if name in EXCLUDED_SOURCES:
                excluded.append(item)
            else:
                allowed.append(item)
    return allowed if allowed else excluded

# ===================== 详情页解析 =====================
def _split_by_slash(span):
    return [a.get_text(strip=True) for a in span.find_all("a") if a.get_text(strip=True) != "[展开...]"]

def _find_span_by_label(block, label):
    for s in block.find_all("span"):
        if s.get_text(" ", strip=True).startswith(label):
            return s
    return None

def parse_detail_page(html, url, name="", info=""):
    soup = BeautifulSoup(html, "html.parser")
    playlist = parse_playlist(soup)
    if not playlist:
        print("[警告] 无播放源")
        return None

    # ===================== 自动提取 name =====================
    h3_tag = soup.select_one(".vod-info .info h3 a")
    if h3_tag:
        name = clean_ws(h3_tag.get_text(strip=True))

    # ===================== 自动提取 info（HD/TC/抢先等） =====================
    info = ""
    otherbox = soup.select_one(".vod-info .otherbox") or soup.select_one(".otherbox")
    if otherbox:
        em_tag = otherbox.find("em")
        if em_tag:
            info = clean_ws(em_tag.get_text(strip=True))

    # ===================== 最后更新时间（对齐主程序逻辑） =====================
    update = ""
    if otherbox:
        ems = otherbox.find_all("em")
        if ems:
            last_text = clean_ws(ems[-1].get_text(strip=True))
            if re.search(r"\d{4}-\d{2}-\d{2}", last_text):
                update = last_text
            elif len(ems) >= 2:
                update = clean_ws(ems[-1].get_text(strip=True))

    data = {
        "name": name, "url": url, "info": info,
        "update": update, "update_pk": update, "image": "",
        "导演": "", "编剧": [], "主演": [], "类型": [], "地区": "",
        "date": "", "alias": "", "intro": "",
        "评分": {"豆瓣": "", "IMDB": ""}, "playlist": playlist
    }

    img = soup.select_one(".pic img")
    if img:
        img_url = img.get("data-original") or img.get("data-src") or img.get("src") or ""
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        if img_url:
            data["image"] = download_cover(img_url, extract_video_id(url, name))
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    info_block = soup.select_one(".vod-info .info") or soup
    span = _find_span_by_label(info_block, "导演：")
    if span:
        d = _split_by_slash(span)
        data["导演"] = d[0] if d else ""

    span = _find_span_by_label(info_block, "编剧：")
    if span:
        data["编剧"] = _split_by_slash(span)
    span = info_block.select_one(".zksq-actor") or _find_span_by_label(info_block, "主演：")
    if span:
        data["主演"] = _split_by_slash(span)
    span = _find_span_by_label(info_block, "类型：")
    if span:
        data["类型"] = _split_by_slash(span)
    span = _find_span_by_label(info_block, "地区：")
    if span:
        r = _split_by_slash(span)
        data["地区"] = r[0] if r else ""

    for s in info_block.find_all("span"):
        t = s.get_text(" ", strip=True)
        if t.startswith("上映："):
            d = clean_ws(t).replace("上映：", "")
            d = re.sub(r"\((.*?)网络\)", r"(\1)", d)
            data["date"] = format_date_str(d)
        elif t.startswith("又名："):
            data["alias"] = clean_ws(t.replace("又名：", ""))

    span = _find_span_by_label(info_block, "评分：")
    if span:
        full = clean_ws(span.get_text())
        matched = False
        for s in span.find_all("span"):
            t = clean_ws(s.get_text())
            m = re.search(r"(豆瓣|IMDB)\s*([0-9.]+|--)", t, re.I)
            if m:
                p = m.group(1)
                if p.upper() == "IMDB":
                    p = "IMDB"
                sc = m.group(2)
                if sc != "--":
                    data["评分"][p] = sc
                    matched = True
        if not matched:
            m = re.search(r"评分：\s*([0-9.]+)", full)
            if m:
                data["评分"]["豆瓣"] = m.group(1)

    intro = soup.select_one(".more-box.zksq-content")
    if intro:
        for a in intro.find_all("a"):
            a.decompose()
        txt = re.sub(r"^剧情介绍[:：]", "", intro.get_text(" ", strip=True))
        data["intro"] = re.sub(r"\s+", "", txt)
    return data

# ===================== JSON 保存/去重/合并 =====================
def load_existing(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[警告] 读取已有 JSON 失败：{e}")
    return {}

def build_index(existing: dict) -> dict:
    """
    构建跨分类全局索引（与主程序一致）。
    结构: {(name, path): {"info","update","image","real_name","real_path","category","list_idx"}}
    """
    idx = {}
    for cat, items in existing.items():
        if isinstance(items, list):
            for list_idx, it in enumerate(items):
                name = it.get("name", "")
                info = it.get("info", "")
                update = it.get("update", "")
                image = it.get("image", "")
                if name:
                    url_keys = [k for k in it.keys() if k == "url" or (k.startswith("url") and k[3:].isdigit())]
                    for key_name in url_keys:
                        url_val = it.get(key_name, "")
                        if url_val:
                            path = get_url_path(url_val)
                            idx[(name, path)] = {
                                "info": info,
                                "update": update,
                                "image": image,
                                "real_name": name,
                                "real_path": path,
                                "category": cat,
                                "list_idx": list_idx
                            }
    return idx

def save_data(data):
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, OUTPUT_FILE)

# ===================== 主逻辑（移植主程序完整更新规则） =====================
def main():
    print("===== 单独详情页抓取工具 =====")
    url = input("请输入详情页URL：").strip()
    cat_name = input("请输入分类（Movie/Drama/Show/Anime）：").strip()

    if not url or not cat_name:
        print("输入不能为空")
        return

    all_data = load_existing(OUTPUT_FILE)
    global_index = build_index(all_data)

    print(f"正在抓取：{url}")
    detail_html = fetch(url)
    if not detail_html:
        print("抓取失败")
        return

    detail = parse_detail_page(detail_html, url)
    if not detail:
        return

    item_name = detail["name"]
    item_info = detail["info"]
    item_path = get_url_path(url)

    # =============================================================
    # 跨分类多维度去重判定（移植自主程序 process_item）
    # 注意：single 是手动强制抓取，不做"跳过/过滤"判定
    # =============================================================
    key = (item_name, item_path)
    old_data = global_index.get(key)
    matched_by_path_only = False
    is_special_6vdy_update = False
    special_update_target = None

    # 1. 跨分类全局 path 查找
    if old_data is None:
        for idx_key, idx_val in global_index.items():
            if idx_val.get("real_path") == item_path:
                old_data = idx_val
                key = idx_key
                matched_by_path_only = True
                break

    # 2. 跨分类同名特殊占位更新规则（6vdy / chnland）
    if old_data is None:
        for cat, existing_list in all_data.items():
            if not isinstance(existing_list, list):
                continue
            for list_idx, existing_item in enumerate(existing_list):
                if existing_item.get("name") == item_name:
                    # 使用 pdy0.py 中的逻辑：判断是否所有 URL 都是受保护域名
                    if is_all_urls_protected(existing_item):
                        is_special_6vdy_update = True
                        old_url_keys = get_all_url_keys(existing_item)
                        first_url_val = existing_item.get(old_url_keys[0], "")
                        old_data = {
                            "info": existing_item.get("info", ""),
                            "update": existing_item.get("update", ""),
                            "image": existing_item.get("image", ""),
                            "real_name": existing_item.get("name"),
                            "real_path": get_url_path(first_url_val),
                            "category": cat,
                            "list_idx": list_idx
                        }
                        key = (existing_item.get("name"), get_url_path(first_url_val))
                        break
            if is_special_6vdy_update:
                break

    is_update = (old_data is not None) or is_special_6vdy_update

    # tag 判定
    if is_update:
        if is_special_6vdy_update:
            tag = f"[特殊占位更新→受保护源]"
        elif matched_by_path_only:
            tag = "[更名更新]"
        elif old_data.get("info") != item_info:
            tag = "[Info更新]"
        elif not old_data.get("update"):
            tag = "[补update]"
        elif not old_data.get("image"):
            tag = "[补图]"
        else:
            tag = "[更新]"
    else:
        tag = "[新增]"

    print(f"{tag} {item_name}  {url}  info={item_info}")

    # ===== 任何更新 name 不要改 =====
    if is_update:
        detail["name"] = key[0]

    # 获取旧分类和旧条目
    old_entry = None
    old_category = None
    target_list_idx = None
    if is_update:
        old_category = old_data.get("category")
        target_list_idx = old_data.get("list_idx")
        if old_category and old_category in all_data:
            existing_list = all_data[old_category]
            if target_list_idx is not None and target_list_idx < len(existing_list):
                old_entry = existing_list[target_list_idx]

    # 合并受保护源
    if old_entry:
        old_playlist = old_entry.get("playlist", [])
        protected_in_old = [p for p in old_playlist if p.get("name") in PROTECTED_SOURCES]
        if protected_in_old:
            new_playlist = [p for p in detail.get("playlist", []) if p.get("name") not in PROTECTED_SOURCES]
            final_playlist = []
            vdy_source = next((p for p in protected_in_old if p.get("name") == "6vdy"), None)
            if vdy_source:
                final_playlist.append(vdy_source)
            for p in protected_in_old:
                if p.get("name") != "6vdy":
                    final_playlist.append(p)
            final_playlist.extend(new_playlist)
            detail["playlist"] = final_playlist
            kept_names = [p.get("name") for p in protected_in_old]
            print(f"     [保留受保护源] {kept_names} (已置顶 6vdy和chnland)")

            # 根据 pdy0.py 逻辑，比较受保护源与新源的集数
            protected_max_ep = max(
                (len(p.get("episodes", {})) for p in protected_in_old),
                default=0
            )
            own_max_ep = max(
                (len(p.get("episodes", {})) for p in new_playlist),
                default=0
            )
            old_info_val = old_entry.get("info", "")
            if own_max_ep <= protected_max_ep:
                if detail.get("info") != old_info_val:
                    print(f"     [Info保持] 自己渠道集数({own_max_ep}) <= 受保护渠道集数({protected_max_ep})，"
                          f"保留旧info '{old_info_val}'，本次仅更新内容不更新info")
                detail["info"] = old_info_val
            else:
                print(f"     [Info可更新] 自己渠道集数({own_max_ep}) > 受保护渠道集数({protected_max_ep})，正常更新 info")

        if matched_by_path_only:
            print(f"     [更名同步] {key[0]} -> {item_name} (已强行保留旧名 {key[0]})")

    # 细粒度字段合并与更新
    if is_update and old_entry:
        detail["update"] = old_entry.get("update", "")

        for field in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]:
            old_val = old_entry.get(field)
            new_val = detail.get(field)
            if not old_val and new_val:
                print(f"     [补全字段] {field}: (空) -> {new_val}")
            else:
                detail[field] = old_val

        old_date = old_entry.get("date", "")
        new_date = detail.get("date", "")
        if new_date and (not old_date or len(new_date) > len(old_date)):
            print(f"     [更新日期] date: {old_date or '(空)'} -> {new_date}")
        else:
            detail["date"] = old_date

        old_rating = old_entry.get("评分", {})
        if not isinstance(old_rating, dict):
            old_rating = {"豆瓣": "", "IMDB": ""}
        new_rating = detail.get("评分", {})
        final_rating = {}
        for platform in ["豆瓣", "IMDB"]:
            old_score = old_rating.get(platform, "")
            new_score = new_rating.get(platform, "")
            if not old_score and new_score:
                final_rating[platform] = new_score
                print(f"     [补全评分] {platform}: (空) -> {new_score}")
            else:
                final_rating[platform] = old_score
        detail["评分"] = final_rating

    # ===== 字段排序重构 =====
    ordered_detail = {}
    ordered_detail["name"] = detail["name"]

    if is_update and old_entry:
        ordered_detail["url"] = old_entry.get("url", "")
    else:
        ordered_detail["url"] = detail["url"]

    if is_special_6vdy_update and old_entry:
        # 先保留旧条目里已有的附加 url 字段（如 url1），再把新 URL 写入目标槽位
        old_url_keys = get_all_url_keys(old_entry)
        existing_url_vals = []
        max_idx = 0
        for k in old_url_keys:
            v = old_entry.get(k, "")
            existing_url_vals.append(v)
            if k != "url":  # "url" 已在上面写入
                ordered_detail[k] = v
                max_idx = max(max_idx, int(k[3:]))
        new_url = detail["url"]
        if new_url and new_url not in existing_url_vals:
            next_key = f"url{max_idx + 1}"
            ordered_detail[next_key] = new_url
            print(f"     [特殊占位合并] 已将新抓取的 URL 写入为 {next_key}: {new_url}")
        else:
            print(f"     [特殊占位合并] 新 URL 已存在于旧条目，跳过追加")
    elif old_entry:
        for k, v in old_entry.items():
            if k.startswith("url") and k != "url":
                ordered_detail[k] = v

    if "info" in detail:
        ordered_detail["info"] = detail["info"]
    if "update" in detail:
        ordered_detail["update"] = detail["update"]
    ordered_detail["update_pk"] = detail.get("update_pk", "")

    for k, v in detail.items():
        if k not in ordered_detail:
            ordered_detail[k] = v
    detail = ordered_detail

    # update_pk 变化提示
    if is_update and old_entry:
        old_upk = old_entry.get("update_pk", "")
        new_upk = detail.get("update_pk", "")
        if old_upk != new_upk:
            if not old_upk:
                print(f"     [新增 update_pk 并更新] -> {new_upk}")
            else:
                print(f"     [update_pk 变化] {old_upk} → {new_upk}")

    # =============================================================
    # 跨分类数据写入
    # =============================================================
    if is_update:
        if old_category != cat_name:
            print(f"     [跨分类移动] 检测到分类漂移: {old_category} ➔ {cat_name}")
            if old_category in all_data and target_list_idx is not None:
                if target_list_idx < len(all_data[old_category]):
                    all_data[old_category].pop(target_list_idx)
            if cat_name not in all_data:
                all_data[cat_name] = []
            all_data[cat_name].append(detail)
        else:
            if target_list_idx is not None and target_list_idx < len(all_data[cat_name]):
                all_data[cat_name][target_list_idx] = detail
            else:
                replaced = False
                for i, old in enumerate(all_data[cat_name]):
                    old_path = get_url_path(old.get("url", ""))
                    if (old.get("name") == key[0] and old_path == item_path) or (old_path == item_path):
                        all_data[cat_name][i] = detail
                        replaced = True
                        break
                if not replaced:
                    all_data[cat_name].append(detail)
        print(f"[更新完成] {detail['name']}")
    else:
        if cat_name not in all_data:
            all_data[cat_name] = []
        all_data[cat_name].append(detail)
        print(f"[新增完成] {detail['name']}")

    save_data(all_data)
    print(f"✅ 已写入 {cat_name} 分类 → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
