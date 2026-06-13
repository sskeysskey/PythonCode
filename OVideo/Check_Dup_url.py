import json
import os
from collections import defaultdict

file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'

def check_duplicate_urls(json_file_path):
    # 文件存在校验
    if not os.path.exists(json_file_path):
        print(f"错误：找不到文件 {json_file_path}")
        return

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("错误：JSON 文件格式不正确")
        return
    except Exception as e:
        print(f"读取解析文件异常：{e}")
        return

    url_tracker = defaultdict(list)

    for category, items in data.items():
        # 跳过非列表结构，防止遍历报错
        if not isinstance(items, list):
            continue

        for item in items:
            name = item.get('name', '未命名项目')
            # 提取所有以url开头、非空字符串的链接
            current_item_urls = []
            for key, val in item.items():
                if key.startswith("url") and isinstance(val, str):
                    clean_url = val.strip()
                    if clean_url:
                        current_item_urls.append(clean_url)

            # 逐条登记，同项目多条相同url也会重复录入，会被判定为重复
            for url in current_item_urls:
                url_tracker[url].append({
                    "category": category,
                    "name": name
                })

    # 筛选出现次数>=2的重复URL
    duplicates = {url: records for url, records in url_tracker.items() if len(records) > 1}

    if not duplicates:
        print("没有发现任何重复的 URL（包含同项目内、跨项目）。")
        return

    print(f"一共检测到 {len(duplicates)} 个重复URL：\n{'='*50}")
    for idx, (url, record_list) in enumerate(duplicates.items(), 1):
        print(f"【{idx}】重复URL：{url}")
        for rec in record_list:
            print(f"    分类：{rec['category']}，条目名称：{rec['name']}")
        print("-" * 50)

if __name__ == "__main__":
    check_duplicate_urls(file_path)