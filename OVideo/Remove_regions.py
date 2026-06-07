import json

# 路径配置
input_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
txt_output = "/Users/yanzhang/Downloads/a.txt"
json_output = "/Users/yanzhang/Downloads/removed.json"  # 新生成的 JSON 路径

# 读取原始 JSON
with open(input_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# 匹配地区集合
target_regions = {"大陆", "中国", "内地", "中国大陆", "中国内地"}

# 用于存放被移除的数据（保持原分类格式）
removed_data = {}
removed_items_for_txt = []

for category in ["Drama", "Anime"]:
    if category not in data:
        continue
    
    remaining = []      # 保留在原 JSON 中的项目
    removed = []        # 被移除的项目
    
    for item in data[category]:
        region = item.get("地区", "")
        if region in target_regions:
            removed.append(item)
            removed_items_for_txt.append({
                "name": item.get("name", ""),
                "url": item.get("url", "")
            })
        else:
            remaining.append(item)
    
    # 更新原数据
    data[category] = remaining
    
    # 如果有被移除的项目，放入 removed_data（保持分类结构）
    if removed:
        removed_data[category] = removed

# 1. 输出 name 和 url 到 a.txt
with open(txt_output, "w", encoding="utf-8") as f:
    for item in removed_items_for_txt:
        f.write(f"{item['name']}\t{item['url']}\n")

# 2. 输出被移除的内容为新的 JSON（格式和原文件一致）
with open(json_output, "w", encoding="utf-8") as f:
    json.dump(removed_data, f, ensure_ascii=False, indent=4)

# 3. 写回修改后的原 JSON（建议先备份原文件）
with open(input_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print(f"共移除 {len(removed_items_for_txt)} 个项目")
print(f"文本列表已保存到: {txt_output}")
print(f"移除数据 JSON 已保存到: {json_output}")
print(f"原文件已更新: {input_path}")