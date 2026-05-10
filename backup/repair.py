import json
import os

# 配置路径
BLACKLIST_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'
OVIDEOS_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
BLACKLIST_KEYWORDS = ['TC', 'TS', '抢先', 'HC']

def check_info_has_blacklist_keyword(target_url, keywords):
    """
    检查 OVideos.json 中的 playlist，返回 (是否找到, info是否包含违禁词)
    """
    if not os.path.exists(OVIDEOS_FILE):
        return False, False
    try:
        with open(OVIDEOS_FILE, 'r', encoding='utf-8') as f:
            ovideos_data = json.load(f)
    except:
        return False, False

    for category, items in ovideos_data.items():
        if not isinstance(items, list): continue
        for item in items:
            if not isinstance(item, dict): continue
            playlist = item.get('playlist', [])
            for source in playlist:
                if target_url in source.get('episodes', []):
                    info_value = item.get('info', '') or ''
                    info_has_keyword = any(kw in info_value for kw in keywords)
                    return True, info_has_keyword, item.get('name', '未知名称')
    return False, False, None

def scan_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        print(f"❌ 文件不存在: {BLACKLIST_FILE}")
        return

    with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
        blacklist_data = json.load(f)

    print(f"🔍 开始扫描黑名单，共 {len(blacklist_data)} 个条目...\n")
    found_count = 0

    for url, details in blacklist_data.items():
        # details 结构通常是 [json_name, original_url]
        is_matched, info_has_keyword, video_name = check_info_has_blacklist_keyword(url, BLACKLIST_KEYWORDS)

        # 逻辑：如果在 OVideos 里找到了，且 info 包含违禁词，说明它是“误判”
        if is_matched and info_has_keyword:
            print("--------------------------------------------------")
            print(f"⚠️  发现误判条目 (建议移回 Mapping):")
            print(f"   视频名称: {video_name}")
            print(f"   URL: {url}")
            print(f"   黑名单数据: {details}")
            found_count += 1

    if found_count == 0:
        print("✅ 扫描完成，未发现误判条目。")
    else:
        print(f"\n--------------------------------------------------")
        print(f"🎉 扫描完成，共发现 {found_count} 个潜在误判条目，请手动核对。")

if __name__ == '__main__':
    scan_blacklist()