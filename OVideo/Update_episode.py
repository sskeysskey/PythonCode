import json
import re
import os

# 定义文件路径
file_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"

# 1. 读取 JSON 文件
if not os.path.exists(file_path):
    print(f"错误：文件不存在 {file_path}")
    exit()

with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 正则表达式：匹配 "更新至XX集" 或 "更新至第XX集"
# (\d+) 用于捕获数字，(第)? 用于可选地捕获“第”字
pattern = re.compile(r"更新至(第)?(\d+)集")

modified_count = 0

# 2. 遍历所有分类 (Movie, Drama, Show, Anime)
for category, items in data.items():
    if not isinstance(items, list):
        continue
    
    for item in items:
        name = item.get("name", "未知名称")
        playlist = item.get("playlist", [])
        
        # 3. 检查第一个渠道的 episode 数量是否 >= 3
        if not playlist:
            continue
        
        first_channel = playlist[0]
        episodes = first_channel.get("episodes", {})
        actual_count = len(episodes)
        
        if actual_count >= 3:
            info = item.get("info", "")
            match = pattern.search(info)
            
            # 4. 判断 info 是否符合指定的两种写法
            if match:
                has_di = match.group(1)  # 如果有“第”字，这里是“第”，否则是 None
                num_str = match.group(2)  # 匹配到的数字字符串（例如 "02" 或 "28"）
                info_num = int(num_str)   # 转为整数
                
                # 5. 如果实际数量大于 info 中的数量，进行更新
                if actual_count > info_num:
                    # 保持原有的数字位数格式（例如：如果是 "02" 且实际是 5，则更新为 "05"；如果是 "28" 且实际是 30，则更新为 "30"）
                    format_width = len(num_str)
                    new_num_str = f"{actual_count:0{format_width}d}"
                    
                    # 拼接新的 info 字符串
                    di_str = "第" if has_di else ""
                    new_info = pattern.sub(f"更新至{di_str}{new_num_str}集", info)
                    
                    # 更新数据
                    item["info"] = new_info
                    modified_count += 1
                    print(f"【更新】[{category}]《{name}》: '{info}' -> '{new_info}' (实际URL数: {actual_count})")

# 6. 保存回原 JSON 文件
if modified_count > 0:
    with open(file_path, 'w', encoding='utf-8') as f:
        # ensure_ascii=False 保证中文不被编码为 \uXXXX，indent=4 保持美观缩进
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"\n处理完成！共更新了 {modified_count} 个项目的 info 字段。")
else:
    print("\n没有需要更新的项目。")