import json
from collections import defaultdict
import os

def get_match_key(item):
    """
    获取用于匹配的备选特征字段。
    优先级：导演 -> 编剧 -> 主演 -> 地区 -> 上映日期
    注意：请根据你 JSON 实际的键名（如 'director', 'year' 等）修改下面元组中的第一个值
    """
    # 格式为 (JSON中的键名, 中文描述)
    fields_to_check = [
        ('director', '导演'),
        ('writer', '编剧'),
        ('actor', '主演'),
        ('region', '地区'),
        ('date', '上映日期')  # 如果你的JSON里叫 'release_date' 或 'year'，请在这里修改
    ]
    
    for key, name in fields_to_check:
        val = item.get(key)
        if val:
            # 找到第一个有值的字段，返回 (中文描述, 具体的值)
            return (name, str(val).strip())
            
    return ('无备选字段', 'None')

def find_items_with_same_name_to_file(json_file_path, output_file_path_a, output_file_path_b):
    # 1. 读取 JSON 文件
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误：找不到输入文件 {json_file_path}")
        return
    except json.JSONDecodeError:
        print("错误：无法解析 JSON 文件，请检查格式。")
        return

    # 2. 将所有类别的项目合并到一个列表中
    all_items = []
    for category in ["Movie", "Drama", "Show", "Anime"]:
        if category in data:
            for item in data[category]:
                item_with_category = item.copy()
                item_with_category['_category'] = category
                all_items.append(item_with_category)

    # 3. 使用字典按 (name, match_key) 联合分组
    grouped_items = defaultdict(list)
    for item in all_items:
        name = item.get('name')
        if name:
            # 获取该项目的匹配特征
            match_key = get_match_key(item)
            # 使用 (名字, 特征) 作为字典的键
            grouped_items[(name, match_key)].append(item)

    # 4. 筛选出符合条件的项目：数量 > 1 且 url 不完全相同
    duplicate_groups = {}
    for (name, match_key), items in grouped_items.items():
        if len(items) > 1:
            # 提取该组内所有不同的 URL
            urls = set(str(item.get('url', '')) for item in items)
            
            # 只有当存在不同的 URL 时，才认为是我们要找的重复项
            if len(urls) > 1:
                # 构造一个新的展示名称，方便在 Markdown 中查看匹配依据
                display_name = f"{name} [相同{match_key[0]}: {match_key[1]}]"
                duplicate_groups[display_name] = items
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_file_path_a), exist_ok=True)
    
    # 5. 写入 a.md (详细报告)
    with open(output_file_path_a, 'w', encoding='utf-8') as f:
        f.write("# 重复项目报告\n\n")
        f.write(f"**共发现 {len(duplicate_groups)} 组符合条件的重复项目。**\n\n")
        
        for display_name, items in duplicate_groups.items():
            f.write(f"## 名称: {display_name} (共找到 {len(items)} 个条目)\n\n")
            for i, item in enumerate(items, 1):
                category = item.get('_category', 'Unknown')
                f.write(f"### [{i}] 来源类别: {category}\n")
                f.write("```json\n")
                temp_item = item.copy()
                if '_category' in temp_item: del temp_item['_category']
                f.write(json.dumps(temp_item, ensure_ascii=False, indent=4))
                f.write("\n```\n\n")
            f.write("---\n\n")

    # 6. 写入 b.md (仅名称列表，增加 6vdy 标记)
    with open(output_file_path_b, 'w', encoding='utf-8') as f:
        f.write("# 重复项目名称列表\n\n")
        f.write("注：带有 `[6vdy]` 标记的表示该组重复项中至少包含一个含有 '6vdy' 的 URL。\n\n")
        
        for display_name in sorted(duplicate_groups.keys()):
            items = duplicate_groups[display_name]
            
            # 判断该组内是否至少有一个项目的 url 包含 '6vdy'
            has_6vdy = any('6vdy' in str(item.get('url', '')) for item in items)
            
            tag = " [6vdy]" if has_6vdy else ""
            f.write(f"- {display_name}{tag}\n")
    
    # 7. 在终端输出统计结果
    print(f"处理完成！")
    print(f"一共找到了 {len(duplicate_groups)} 组符合条件的重复项目。")
    print(f"详细报告已保存至: {output_file_path_a}")
    print(f"名称列表已保存至: {output_file_path_b}")

# --- 配置路径 ---
input_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
output_path_a = '/Users/yanzhang/Downloads/a.md'
output_path_b = '/Users/yanzhang/Downloads/b.md'

find_items_with_same_name_to_file(input_path, output_path_a, output_path_b)