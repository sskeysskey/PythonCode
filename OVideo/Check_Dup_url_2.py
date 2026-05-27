import json
import os
from collections import defaultdict

# JSON 文件路径
json_file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"

def detect_duplicate_urls(file_path):
    if not os.path.exists(file_path):
        print(f"错误：找不到文件 {file_path}")
        return

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"解析 JSON 文件失败: {e}")
        return

    # 用于记录每个 URL 关联的项目
    # 格式：{ url_string: [ {"category": 分类, "name": 项目名}, ... ] }
    url_to_projects = defaultdict(list)

    # 遍历 JSON 中的所有分类和项目
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for item in items:
            project_name = item.get("name", "未命名项目")
            
            # 提取该项目所有以 "url" 开头的键的值
            project_urls = []
            for key, value in item.items():
                if key.startswith("url") and isinstance(value, str) and value.strip():
                    project_urls.append(value.strip())
            
            # 记录该项目拥有的所有 URL
            for url in project_urls:
                # 避免同一个项目内部重复记录（例如项目内 url 和 url1 相同，不属于跨项目重复）
                if not any(p["name"] == project_name and p["category"] == category for p in url_to_projects[url]):
                    url_to_projects[url].append({
                        "category": category,
                        "name": project_name
                    })

    # 筛选出在多个不同项目中出现的 URL
    duplicates = {url: projects for url, projects in url_to_projects.items() if len(projects) > 1}

    # 输出结果
    if not duplicates:
        print("恭喜！未检测到任何跨项目的重复 URL。")
    else:
        print(f"检测到 {len(duplicates)} 个重复的 URL，详情如下：\n" + "="*50)
        for idx, (url, projects) in enumerate(duplicates.items(), 1):
            print(f"【重复 {idx}】URL: {url}")
            print("关联的项目：")
            for p in projects:
                print(f"  - 分类: [{p['category']}] | 项目名: {p['name']}")
            print("-" * 50)

if __name__ == "__main__":
    detect_duplicate_urls(json_file_path)