import json
import re
from collections import defaultdict
from datetime import datetime

# ========== 配置 ==========
INPUT_FILE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"
OUTPUT_FILE = "/Users/yanzhang/Downloads/a.txt"

# ========== 读取数据 ==========
with open(INPUT_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

# ========== 分析逻辑 ==========
# 按系列分组：提取key中的系列前缀（去掉最后的集数部分）
# 例如 "https://www.pys2.com/py/492533-1-10.html" -> 系列前缀 "492533-1-"
series_groups = defaultdict(list)  # 系列前缀 -> [(完整key, 视频URL, 标题)]

for key, value in data.items():
    # 跳过空值或无效值
    if not value or not isinstance(value, list) or len(value) < 2:
        continue
    
    video_url = value[0]  # 视频URL
    title = value[1]      # 标题
    
    # 从key中提取系列前缀
    # 模式: .../py/数字-数字-数字.html
    match = re.search(r'/py/(\d+-\d+)-\d+\.html$', key)
    if not match:
        continue
    
    series_prefix = match.group(1)  # 例如 "492533-1"
    series_groups[series_prefix].append((key, video_url, title))

# ========== 检测错误 ==========
errors = []

for series_prefix, episodes in series_groups.items():
    # 只检查有多个集数的系列
    if len(episodes) < 2:
        continue
    
    # 按集数排序
    episodes_sorted = sorted(episodes, key=lambda x: x[0])
    
    # 检查是否有重复的视频URL
    url_to_episodes = defaultdict(list)
    for key, video_url, title in episodes_sorted:
        url_to_episodes[video_url].append((key, title))
    
    for video_url, ep_list in url_to_episodes.items():
        if len(ep_list) > 1:
            # 同一个视频URL被多个集数使用 → 错误
            error_info = {
                'series_prefix': series_prefix,
                'video_url': video_url,
                'episodes': ep_list
            }
            errors.append(error_info)

# ========== 输出结果 ==========
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(f"URL映射错误检测报告\n")
    f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"扫描文件: {INPUT_FILE}\n")
    f.write(f"总记录数: {len(data)}\n")
    f.write(f"发现错误系列数: {len(errors)}\n")
    f.write("=" * 80 + "\n\n")
    
    if not errors:
        f.write("✅ 未发现错误！所有系列的不同集数都对应不同的视频URL。\n")
    else:
        for i, err in enumerate(errors, 1):
            f.write(f"【错误 #{i}】系列前缀: {err['series_prefix']}\n")
            f.write(f"  重复的视频URL: {err['video_url']}\n")
            f.write(f"  涉及以下 {len(err['episodes'])} 个集数:\n")
            for key, title in err['episodes']:
                f.write(f"    - {key}\n")
                f.write(f"      标题: {title}\n")
            f.write("\n")

print(f"检测完成！结果已保存到: {OUTPUT_FILE}")
if errors:
    print(f"发现 {len(errors)} 处错误，请查看文件详情。")
else:
    print("未发现错误！")