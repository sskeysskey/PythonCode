import json
import os

# 定义文件路径
base_dir = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo"
source_file = os.path.join(base_dir, "OVideos.json")
export_file = os.path.join(base_dir, "chnland_playlist.json")

# 1. 读取原 JSON 文件
with open(source_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# 存储提取出来的 chnland 播放列表数据
exported_chnland = []

# 2. 遍历所有分类 (Movie, Drama, Show, Anime 等)
for category, items in data.items():
    if isinstance(items, list):
        for item in items:
            playlists = item.get("playlist", [])
            remaining_playlists = []
            
            for pl in playlists:
                if pl.get("name") == "chnland":
                    # 记录提取出的 chnland 信息（附带作品名称和分类，方便后续追溯）
                    exported_chnland.append({
                        "category": category,
                        "name": item.get("name"),
                        "chnland_playlist": pl
                    })
                else:
                    # 保留非 chnland 的播放列表
                    remaining_playlists.append(pl)
            
            # 更新原条目的 playlist
            item["playlist"] = remaining_playlists

# 3. 将导出的 chnland 数据写入 chnland_playlist.json
with open(export_file, "w", encoding="utf-8") as f:
    json.dump(exported_chnland, f, ensure_ascii=False, indent=4)

# 4. 将清理后的数据覆盖保存回 OVideos.json
with open(source_file, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print("处理完成！")
print(f"1. 已移除 chnland 并更新原文件: {source_file}")
print(f"2. 已导出 chnland 列表到: {export_file}")