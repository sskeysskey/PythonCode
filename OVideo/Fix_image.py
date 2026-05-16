import json
import os
import time
import re
from urllib.parse import urlparse, urljoin
import requests
import urllib3
from bs4 import BeautifulSoup
from curl_cffi import requests as c_requests
import ssl
from urllib3.util.ssl_ import create_urllib3_context

# ================= 配置区 =================
OUTPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
COVER_IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
REQUEST_TIMEOUT = 15
# ==========================================

# 保持与你原程序一致的网络环境配置
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class TLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try: ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        except: pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

_tls_session = requests.Session()
_tls_session.mount("https://", TLSAdapter())

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def extract_video_id(url, name):
    m = re.search(r"/(?:mv|vod|detail)/(\d+)", url)
    if m: return m.group(1)
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", name).strip("_") or "unknown"

# 核心下载逻辑 (复用你原有的)
def download_cover(img_url, video_id):
    if not img_url: return ""
    ensure_dir(COVER_IMAGE_DIR)
    ext = os.path.splitext(img_url.split("?")[0])[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}: ext = ".jpg"
    filename = f"{video_id}{ext}"
    filepath = os.path.join(COVER_IMAGE_DIR, filename)

    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return filename

    try:
        resp = c_requests.get(img_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, impersonate="chrome", verify=False)
        if resp.status_code == 200 and len(resp.content) > 100:
            with open(filepath, "wb") as f: f.write(resp.content)
            print(f"     [成功下载] {filename}")
            return filename
    except Exception as e:
        print(f"     [下载失败] {e}")
    return ""

def get_image_url_from_detail(url):
    """访问详情页并提取图片地址"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        pic_img = soup.select_one("div.vod-info .pic img")
        if pic_img:
            img_url = (pic_img.get("data-original") or pic_img.get("data-src") or pic_img.get("src") or "").strip()
            if img_url.startswith("//"): img_url = "https:" + img_url
            return img_url
    except Exception as e:
        print(f"  [访问详情页失败] {url}: {e}")
    return None

def main():
    if not os.path.exists(OUTPUT_FILE):
        print("错误: JSON 文件不存在")
        return

    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    changed = False
    for category, items in data.items():
        print(f"\n>>> 正在检查分类: {category}")
        for item in items:
            # 检查是否缺失图片
            if not item.get("image"):
                print(f"  [发现缺失] {item['name']} -> 正在修复...")
                
                # 1. 获取图片地址
                img_url = get_image_url_from_detail(item["url"])
                
                if img_url:
                    # 2. 下载图片
                    video_id = extract_video_id(item["url"], item["name"])
                    new_filename = download_cover(img_url, video_id)
                    
                    if new_filename:
                        item["image"] = new_filename
                        changed = True
                        print(f"  [已修复] {item['name']} -> {new_filename}")
                    else:
                        print(f"  [下载失败] 无法下载图片: {img_url}")
                else:
                    print(f"  [解析失败] 无法从页面提取图片")
                
                time.sleep(1.0) # 适当停顿，防止被封

    if changed:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("\n✅ 所有缺失图片已尝试修复并保存。")
    else:
        print("\n✅ 没有发现需要修复的图片。")

if __name__ == "__main__":
    main()