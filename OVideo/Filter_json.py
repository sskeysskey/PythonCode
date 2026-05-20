import json
from collections import defaultdict
import os

def find_items_with_same_name_to_file(json_file_path, output_file_path):
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

    # 3. 使用字典按 name 分组
    grouped_items = defaultdict(list)
    for item in all_items:
        name = item.get('name')
        if name:
            grouped_items[name].append(item)

    # 4. 筛选出 name 出现次数大于 1 的项目
    duplicate_groups = {name: items for name, items in grouped_items.items() if len(items) > 1}
    
    # 5. 写入文件
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
    
    with open(output_file_path, 'w', encoding='utf-8') as f:
        f.write("# 重复项目报告\n\n")
        f.write(f"**共发现 {len(duplicate_groups)} 组重复项目。**\n\n")
        
        for name, items in duplicate_groups.items():
            f.write(f"## 名称: {name} (共找到 {len(items)} 个条目)\n\n")
            for i, item in enumerate(items, 1):
                category = item.pop('_category')
                f.write(f"### [{i}] 来源类别: {category}\n")
                f.write("```json\n")
                f.write(json.dumps(item, ensure_ascii=False, indent=4))
                f.write("\n```\n\n")
            f.write("---\n\n")
    
    # 6. 在终端输出统计结果
    print(f"处理完成！")
    print(f"一共找到了 {len(duplicate_groups)} 组重复项目。")
    print(f"详细报告已保存至: {output_file_path}")

# --- 配置路径 ---
input_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
output_path = '/Users/yanzhang/Downloads/a.md'

find_items_with_same_name_to_file(input_path, output_path)