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

# ===================== 配置（和你原代码完全一致） =====================
VERBOSE_LOG = False
PROTECTED_SOURCES = {"xb6v", "6vdy"}
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

# ===================== 封面下载（完全和原代码一致） =====================
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
    playlist = []
    online = soup.select_one("#url-content1")
    if not online:
        return []
    tabs = online.select(".playlist-tab li.swiper-slide")
    allowed = []
    excluded = []
    for tab in tabs:
        target = tab.get("data-target", "")
        name = ""
        for c in tab.contents:
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

def parse_detail_page(html, name, url, info=""):
    soup = BeautifulSoup(html, "html.parser")
    playlist = parse_playlist(soup)
    if not playlist:
        print("[警告] 无播放源")
        return None

    # ===================== 【修复：自动提取 name】 =====================
    h3_tag = soup.select_one(".vod-info .info h3 a")
    if h3_tag:
        name = clean_ws(h3_tag.get_text(strip=True))  # 提取：短途旅游

    # ===================== 【修复：自动提取 info（HD/TC/抢先等）】 =====================
    info = ""
    otherbox = soup.select_one(".vod-info .otherbox")
    if otherbox:
        em_tag = otherbox.find("em")
        if em_tag:
            info = clean_ws(em_tag.get_text(strip=True))  # 提取：HD

    # 最后更新时间
    update = ""
    em_list = otherbox.find_all("em") if otherbox else []
    if len(em_list) >= 2:
        update = clean_ws(em_list[1].get_text(strip=True))

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
            return json.load(f)
    except:
        return {}

def build_index(data):
    idx = {}
    for cat, lst in data.items():
        if isinstance(lst, list):
            for i, it in enumerate(lst):
                name = it.get("name", "")
                urls = [it[k] for k in it if k.startswith("url")]
                for u in urls:
                    p = get_url_path(u)
                    idx[(name, p)] = {"cat": cat, "idx": i, "item": it}
    return idx

def save_data(data):
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, OUTPUT_FILE)

# ===================== 主逻辑 =====================
def main():
    print("===== 单独详情页抓取工具 =====")
    url = input("请输入详情页URL：").strip()
    cat = input("请输入分类（Movie/Drama/Show/Anime）：").strip()

    if not url or not cat:
        print("输入不能为空")
        return

    data = load_existing(OUTPUT_FILE)
    idx = build_index(data)
    path = get_url_path(url)

    print(f"正在抓取：{url}")
    html = fetch(url)
    if not html:
        print("抓取失败")
        return

    # 这里修复了变量顺序错误！
    detail = parse_detail_page(html, "临时名称", url, info="")
    if not detail:
        return

    # 去重匹配
    match = None
    key = None
    for k, v in idx.items():
        # 只按URL路径去重，取消片名相等就匹配
        if k[1] == path:
            match = v
            key = k
            break

    if cat not in data:
        data[cat] = []

    if match:
        old = match["item"]
        detail["name"] = old["name"]
        detail["url"] = old["url"]
        for k in old:
            if k.startswith("url") and k != "url":
                detail[k] = old[k]

        # 保留受保护播放源
        old_pl = old.get("playlist", [])
        protect = [p for p in old_pl if p.get("name") in PROTECTED_SOURCES]
        new_pl = [p for p in detail["playlist"] if p.get("name") not in PROTECTED_SOURCES]
        final_pl = []
        vdy = next((x for x in protect if x["name"] == "6vdy"), None)
        if vdy:
            final_pl.append(vdy)
        for p in protect:
            if p != vdy:
                final_pl.append(p)
        final_pl += new_pl
        detail["playlist"] = final_pl

        # 字段合并规则
        detail["update"] = old.get("update", "")
        for f in ["导演", "编剧", "主演", "类型", "地区", "alias", "intro"]:
            if old.get(f) and not detail.get(f):
                detail[f] = old[f]
        if old.get("date") and len(old["date"]) >= len(detail.get("date", "")):
            detail["date"] = old["date"]
        for p in ["豆瓣", "IMDB"]:
            if old["评分"].get(p) and not detail["评分"].get(p):
                detail["评分"][p] = old["评分"][p]

        data[match["cat"]].pop(match["idx"])
        print(f"[更新] {detail['name']}")
    else:
        print(f"[新增] {detail['name']}")

    data[cat].append(detail)
    save_data(data)
    print(f"✅ 已写入 {cat} 分类 → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()