import json
import os
import shutil

mapping_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json"
blacklist_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json"
filter_keyword = "www.chnland.com/vodplay"

# 备份
shutil.copyfile(mapping_path, mapping_path + ".bak")
if os.path.exists(blacklist_path):
    shutil.copyfile(blacklist_path, blacklist_path + ".bak")

# 读取 mapping
with open(mapping_path, "r", encoding="utf-8") as f:
    mapping = json.load(f)

# 读取 blacklist
blacklist = {}
if os.path.exists(blacklist_path) and os.path.getsize(blacklist_path) > 0:
    with open(blacklist_path, "r", encoding="utf-8") as f:
        blacklist = json.load(f)

# 移动包含关键字的 key
keys_to_move = [k for k in mapping if filter_keyword in k]
for k in keys_to_move:
    blacklist[k] = mapping.pop(k)

# 写入
with open(mapping_path, "w", encoding="utf-8") as f:
    json.dump(mapping, f, ensure_ascii=False, indent=4)

with open(blacklist_path, "w", encoding="utf-8") as f:
    json.dump(blacklist, f, ensure_ascii=False, indent=4)

print(f"成功移动了 {len(keys_to_move)} 条数据到 blacklist_url.json！")