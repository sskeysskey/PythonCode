import json
from collections import defaultdict

# 1. 设置文件路径
file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'

def check_duplicate_urls(json_file_path):
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误：找不到文件 {json_file_path}")
        return
    except json.JSONDecodeError:
        print("错误：JSON 文件格式不正确")
        return

    # url_tracker 结构: { "url_string": [ {"category": "...", "name": "..."}, ... ] }
    url_tracker = defaultdict(list)

    # 2. 遍历所有分类
    for category, items in data.items():
        for item in items:
            url = item.get('url')
            name = item.get('name')
            if url:
                url_tracker[url].append({
                    "category": category,
                    "name": name
                })

    # 3. 筛选出重复的 URL
    duplicates = {url: info for url, info in url_tracker.items() if len(info) > 1}

    # 4. 输出结果
    if not duplicates:
        print("没有发现重复的 URL。")
    else:
        print(f"发现 {len(duplicates)} 个重复的 URL:\n")
        for url, info_list in duplicates.items():
            print(f"URL: {url}")
            for info in info_list:
                print(f"  - 分类: {info['category']}, 名称: {info['name']}")
            print("-" * 30)

if __name__ == "__main__":
    check_duplicate_urls(file_path)