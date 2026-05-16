import json
import os

# 定义文件路径
mapping_file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
blacklist_file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'

def process_migration():
    # 1. 加载数据
    try:
        with open(mapping_file_path, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
        with open(blacklist_file_path, 'r', encoding='utf-8') as f:
            blacklist_data = json.load(f)
    except Exception as e:
        print(f"读取文件失败: {e}")
        return

    moved_items = []
    keys_to_delete = []

    # 2. 遍历 blacklist 进行筛选
    for key, value in blacklist_data.items():
        # 确保 value 是列表且有内容
        if isinstance(value, list) and len(value) > 0:
            url = value[0]
            
            # 条件判断：包含 "/p.bvvvvv" 且 不包含 "%"
            if "/p.bvvvvv" in url and "%" not in url:
                # 3. 标记为移动
                mapping_data[key] = value
                keys_to_delete.append(key)
                moved_items.append({
                    "key": key,
                    "url": url,
                    "title": value[1] if len(value) > 1 else "无标题"
                })

    # 4. 执行删除操作
    for key in keys_to_delete:
        del blacklist_data[key]

    # 5. 输出日志
    print("--- 迁移日志 ---")
    if not moved_items:
        print("没有找到符合条件的条目进行迁移。")
    else:
        for item in moved_items:
            print(f"已迁移: {item['title']}")
            print(f"  Key: {item['key']}")
            print(f"  URL: {item['url']}")
            print("-" * 20)
    print(f"共迁移 {len(moved_items)} 条数据。")

    # 6. 保存回文件
    with open(mapping_file_path, 'w', encoding='utf-8') as f:
        json.dump(mapping_data, f, ensure_ascii=False, indent=4)
    
    with open(blacklist_file_path, 'w', encoding='utf-8') as f:
        json.dump(blacklist_data, f, ensure_ascii=False, indent=4)
    
    print("\n文件已更新并保存。")

if __name__ == "__main__":
    process_migration()