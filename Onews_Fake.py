import os
import json
import hashlib
from datetime import datetime

def compute_md5(path):
    """计算文件的 MD5 哈希值"""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def process_and_clean_news_files(local_dir):
    """
    遍历目录中所有的 onews_*.json 文件，
    清空 url 和 images 字段，并替换指定的源名称。
    """
    print("--- 开始处理和清理新闻 JSON 文件 ---")
    
    # 定义需要替换的文本对应关系
    replacements = {
        "华尔街日报": "新闻纵横",
        "伦敦金融时报": "时事评论",
        "布隆伯格金融": "热点News",
        "路透社": "环球速递",
        "经济学人": "国外摘要",
        "日经新闻": "酷评直击",
        "华盛顿邮报": "百姓民生",
        "纽约时报": "寰宇纵横",
        "麻省理工技术评论": "技术和创新"
    }
    
    # 遍历目录中的所有文件
    for filename in os.listdir(local_dir):
        # 只处理符合 onews_*.json 格式的文件
        if filename.startswith("onews_") and filename.endswith(".json"):
            file_path = os.path.join(local_dir, filename)
            print(f"正在处理文件: {filename}")
            
            try:
                # 1. 读取并加载 JSON 文件
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 2. 遍历 JSON 结构，清空 url 和 images
                for source, articles in data.items():
                    if isinstance(articles, list):
                        for article in articles:
                            if "url" in article:
                                article["url"] = ""
                            # if "images" in article:
                            #     article["images"] = []
                
                # 3. 将修改后的 Python 对象转换回格式化的 JSON 字符串
                # 使用 ensure_ascii=False 和 indent=4 来保持格式美观和中文正常显示
                json_string = json.dumps(data, ensure_ascii=False, indent=4)

                # 4. 在整个 JSON 字符串上执行文本替换
                for old_text, new_text in replacements.items():
                    json_string = json_string.replace(old_text, new_text)

                # 5. 将最终修改过的字符串写回文件
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(json_string)
                
                print(f"处理完成: {filename}")

            except json.JSONDecodeError:
                print(f"错误: 文件 {filename} 不是有效的 JSON 格式，已跳过。")
            except Exception as e:
                print(f"处理文件 {filename} 时发生未知错误: {e}")

    print("--- 所有新闻 JSON 文件处理完毕 ---\n")


def update_version_json_fake(local_dir, timestamp):
    """
    读取 local_dir/version.json，向 files 数组追加本次
    onews_*.json 和 news_images_* 记录，并为 json 文件计算 MD5，
    最后写回 version.json。
    """
    version_path = os.path.join(local_dir, "version.json")
    
    # 如果 version.json 不存在，则初始化一个空结构
    if not os.path.exists(version_path):
        data = {"version": "1.0", "files": []}
    else:
        with open(version_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    
    # 遍历已有条目，如果是 json，就重新计算 MD5 并更新
    # 这一步现在会自动处理被 process_and_clean_news_files 修改过的文件
    for item in data.get("files", []):
        if item.get("type") == "json":
            file_path = os.path.join(local_dir, item["name"])
            if os.path.isfile(file_path):
                new_md5 = compute_md5(file_path)
                if item.get("md5") != new_md5:
                    print(f"更新 MD5: {item['name']} {item.get('md5','')} -> {new_md5}")
                    item["md5"] = new_md5
    
    # 准备本次要追加的条目
    to_add = []
    # JSON 文件
    json_name = f"onews_{timestamp}.json"
    json_path = os.path.join(local_dir, json_name)
    if os.path.isfile(json_path):
        to_add.append({
            "name": json_name,
            "type": "json",
            "md5": compute_md5(json_path)
        })
    # 图片目录（这里我们不算 MD5，只用时间戳判断更新）
    img_name = f"news_images_{timestamp}"
    to_add.append({
        "name": img_name,
        "type": "images"
    })
    
    # 去重并追加
    existing_names = { item["name"] for item in data["files"] }
    for e in to_add:
        if e["name"] not in existing_names:
            data["files"].append(e)
            print(f"已添加到 version.json: {e['name']}")
        else:
            # 如果已经存在，但是 JSON，我们之前已经更新过 MD5
            if e["type"] == "json":
                print(f"跳过添加 (已存在): {e['name']}，但 MD5 已刷新")
            else:
                print(f"跳过添加 (已存在): {e['name']}")
    
    # 写回 version.json（格式化，保留缩进）
    with open(version_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"version.json 已更新: {version_path}")

# --- 主执行逻辑 ---
local_server_dir = "/Users/yanzhang/Coding/LocalServer/Resources/ONews"
timestamp = datetime.now().strftime("%y%m%d")

# 1. 首先，执行清理和替换操作，这将修改目录中所有的 onews_*.json 文件
# process_and_clean_news_files(local_server_dir)

# 2. 然后，执行原有的 version.json 更新逻辑
#    它会为所有 json 文件（包括刚刚被修改的）重新计算 MD5
# update_version_json_fake(local_server_dir, timestamp)