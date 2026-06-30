import json
import os
from urllib.parse import urlparse
from collections import defaultdict

# 定义输入和输出路径
input_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"
output_path = "/Users/yanzhang/Downloads/a.txt"

def analyze_mapping():
    # 1. 读取 JSON 文件
    if not os.path.exists(input_path):
        print(f"错误: 找不到输入文件 {input_path}")
        return
        
    with open(input_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"JSON 解析失败: {e}")
            return

    # 2. 按 value1 (视频播放链接) 进行第一步分组
    # 结构: { 视频链接: [(原始key_url, 路径, 视频标题), ...] }
    video_groups = defaultdict(list)
    
    for key_url, val in data.items():
        # 过滤掉空值或格式不正确的项
        if not val or not isinstance(val, list) or len(val) < 2:
            continue
            
        video_url = val[0]  # value1: 视频播放源 url
        title = val[1]      # value2: 视频标题
        
        # 解析 key 的 URL，提取路径 (path)
        try:
            parsed_key = urlparse(key_url)
            path = parsed_key.path  # 例如 "/py/492533-1-9.html"
            video_groups[video_url].append((key_url, path, title))
        except Exception:
            continue

    # 3. 筛选出：在同一个视频源下，存在“路径相同但完整 URL 不同（即域名不同）”的项目
    results = []
    
    for video_url, items in video_groups.items():
        # 按路径 (path) 进行细分分组
        # 结构: { 路径: [(原始key_url, 视频标题), ...] }
        path_groups = defaultdict(list)
        for key_url, path, title in items:
            path_groups[path].append((key_url, title))
            
        # 过滤出同一个路径有多个不同域名 key 的组
        for path, keys_info in path_groups.items():
            if len(keys_info) > 1:
                # 找到了域名不同、但路径和播放源都相同的组
                results.append({
                    "video_url": video_url,
                    "path": path,
                    "items": keys_info
                })

    # ===================== 修改点 =====================
    # 无匹配数据直接返回，不创建文件
    if not results:
        print("分析完成：未发现符合条件的分组，不生成输出文件。")
        return
    # ==================================================

    # 4. 写入到 a.txt
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as out_f:
        out_f.write(f"=== 共找到 {len(results)} 组仅域名差异的重复项目 ===\n\n")
        
        for idx, group in enumerate(results, 1):
            out_f.write(f"【分组 {idx}】\n")
            out_f.write(f"视频源 (Value1): {group['video_url']}\n")
            out_f.write(f"匹配路径: {group['path']}\n")
            out_f.write("冲突的 Key 列表:\n")
            for key_url, title in group['items']:
                out_f.write(f"  - Key: {key_url}  | 标题: {title}\n")
            out_f.write("-" * 60 + "\n\n")
            
    print(f"分析完成！结果已成功输出到: {output_path}")

if __name__ == "__main__":
    analyze_mapping()