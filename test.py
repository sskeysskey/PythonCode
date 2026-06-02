import json
import os

# 定义路径
videos_file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
mapping_file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"
output_file_path = "/Users/yanzhang/Downloads/a.txt"

def scan_and_filter_videos():
    # 1. 检查文件是否存在
    if not os.path.exists(videos_file_path) or not os.path.exists(mapping_file_path):
        print(f"错误: 找不到输入文件。请检查路径是否正确。")
        return

    try:
        # 2. 读取 mapping 文件，将所有 key 存入集合
        with open(mapping_file_path, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
            mapped_urls = set(mapping_data.keys())

        # 3. 读取 OVideos 文件
        with open(videos_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        results = []
        
        # 4. 遍历所有类别
        for category, items in data.items():
            if not isinstance(items, list):
                continue
                
            for item in items:
                name = item.get("name", "未知名称")
                playlist = item.get("playlist", [])
                
                # --- 排除逻辑 ---
                # 如果该项目的任何一个 episode URL 在 mapping 中，直接排除该项目
                is_excluded = False
                for channel in playlist:
                    for ep_url in channel.get("episodes", {}).values():
                        if ep_url in mapped_urls:
                            is_excluded = True
                            break
                    if is_excluded: break
                
                if is_excluded:
                    continue # 跳过此项目
                
                # --- 筛选逻辑 ---
                # 检查是否满足“某个频道集数 > 100”
                for channel in playlist:
                    count = len(channel.get("episodes", {}))
                    if count > 50:
                        channel_name = channel.get("name", "未知频道")
                        
                        # --- 提取所有 URL 相关字段 ---
                        # 查找所有以 "url" 开头的键 (例如 url, url1, url2...)
                        url_fields = {k: v for k, v in item.items() if k.startswith("url")}
                        url_str = " | ".join([f"{k}: {v}" for k, v in url_fields.items()])
                        
                        # 构建输出行
                        line = f"类别: {category} | 名称: {name} | 频道: {channel_name} | 集数: {count} | URLs: [{url_str}]"
                        results.append(line)
                        
                        # 只要有一个频道满足即可，无需继续检查该项目的其他频道
                        break 

        # 5. 写入结果
        with open(output_file_path, 'w', encoding='utf-8') as f:
            if results:
                f.write("\n".join(results))
                print(f"扫描完成！共找到 {len(results)} 个符合条件的条目。")
                print(f"结果已保存至: {output_file_path}")
            else:
                f.write("没有找到符合条件（集数 > 100 且未在映射表中）的项目。")
                print("扫描完成，未发现符合条件的项目。")

    except json.JSONDecodeError:
        print("错误: JSON 文件格式不正确，无法解析。")
    except Exception as e:
        print(f"发生未知错误: {e}")

if __name__ == "__main__":
    scan_and_filter_videos()