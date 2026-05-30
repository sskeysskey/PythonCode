import json
import os

def check_urls_in_blacklist():
    # 定义文件路径
    mapping_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
    blacklist_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'

    # 检查文件是否存在
    if not os.path.exists(mapping_path) or not os.path.exists(blacklist_path):
        print("错误：找不到指定的 JSON 文件，请检查路径。")
        return

    try:
        # 读取 JSON 数据
        with open(mapping_path, 'r', encoding='utf-8') as f_map:
            mapping_data = json.load(f_map)
        
        with open(blacklist_path, 'r', encoding='utf-8') as f_black:
            blacklist_data = json.load(f_black)

        # 获取所有的 key
        mapping_keys = set(mapping_data.keys())
        blacklist_keys = set(blacklist_data.keys())

        # 找出交集（即同时存在于两个文件中的 URL）
        conflicts = mapping_keys.intersection(blacklist_keys)

        # 输出结果
        if conflicts:
            print(f"发现 {len(conflicts)} 个冲突项：")
            for url in conflicts:
                print(f"[冲突] {url}")
        else:
            print("检查完成：没有发现 URL 冲突。")

    except json.JSONDecodeError:
        print("错误：JSON 文件格式不正确，请检查文件内容。")
    except Exception as e:
        print(f"发生未知错误: {e}")

if __name__ == "__main__":
    check_urls_in_blacklist()