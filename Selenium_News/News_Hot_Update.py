import os
import glob
import json
import hashlib
from send2trash import send2trash
from datetime import datetime, timedelta

# --- 路径定义区 ---
USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")
NEWS_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
LOCAL_SERVER_DIR = os.path.join(BASE_CODING_DIR, "LocalServer", "Resources", "ONews")
ERROR_FILE_PATH = os.path.join(NEWS_DIRECTORY, "error.txt")

def compute_md5(path):
    """计算文件的 MD5 值"""
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def update_version_json(local_dir, timestamp):
    """更新 version.json 文件"""
    version_path = os.path.join(local_dir, "version.json")
    
    if not os.path.exists(version_path):
        data = {"version": "1.0", "files": [], "update_time": ""}
    else:
        with open(version_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
    # 1. 更新现有文件的 MD5 (过滤掉不存在的文件，防止报错)
    if "files" not in data:
        data["files"] = []
        
    for item in data.get("files", []):
        if item.get("type") == "json":
            file_path = os.path.join(local_dir, item["name"])
            if os.path.isfile(file_path):
                new_md5 = compute_md5(file_path)
                item["md5"] = new_md5
    
    # 2. 准备添加新文件
    json_name = f"onews_{timestamp}.json"
    json_path = os.path.join(local_dir, json_name)
    
    if os.path.isfile(json_path):
        # 检查是否已存在，不存在则添加
        if not any(f["name"] == json_name for f in data["files"]):
            data["files"].append({
                "name": json_name,
                "type": "json",
                "md5": compute_md5(json_path)
            })
            print(f"已添加到 version.json: {json_name}")

    # 3. 更新 update_time
    data["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            
    with open(version_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"version.json 已更新")

def process_news_files():
    # 确保错误日志的目录存在
    os.makedirs(os.path.dirname(ERROR_FILE_PATH), exist_ok=True)

    # 获取今天和昨天的日期字符串，格式为 YYMMDD (例如 260427)
    now = datetime.now()
    today_str = now.strftime("%y%m%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%y%m%d")

    # 构建今天和昨天的预期文件路径
    today_file_path = os.path.join(DOWNLOADS_DIR, f"TodayCNH_{today_str}.json")
    yesterday_file_path = os.path.join(DOWNLOADS_DIR, f"TodayCNH_{yesterday_str}.json")

    file_to_process = None
    
    # 核心逻辑：昨天今天都有，只处理今天；只有昨天，当今天处理；只有今天，正常处理。
    if os.path.exists(today_file_path):
        file_to_process = today_file_path
        print(f"发现今天的文件: {os.path.basename(file_to_process)}，准备处理。")
    elif os.path.exists(yesterday_file_path):
        file_to_process = yesterday_file_path
        print(f"未发现今天的文件，但发现昨天的文件: {os.path.basename(file_to_process)}，将作为今天的数据处理。")
    else:
        print("未在 Downloads 目录下找到今天或昨天的 TodayCNH_*.json 文件，程序结束。")
        return

    # 目标 onews 文件始终使用“今天”的时间戳
    target_timestamp = today_str
    onews_filename = f"onews_{target_timestamp}.json"
    onews_file = os.path.join(LOCAL_SERVER_DIR, onews_filename)
    
    filename = os.path.basename(file_to_process)
    
    if not os.path.exists(onews_file):
        print(f"警告: 准备处理 {filename}，但未找到对应的目标文件 {onews_filename}，程序结束。")
        return
        
    # 读取两个 JSON 文件
    try:
        with open(file_to_process, 'r', encoding='utf-8') as f:
            today_data = json.load(f)
        with open(onews_file, 'r', encoding='utf-8') as f:
            onews_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}")
        return

    # 遍历 today_data 进行 URL 匹配
    for today_item in today_data:
        target_url = today_item.get("url")
        if not target_url:
            continue
            
        match_found = False
        
        # 遍历 onews_data 中的各个新闻板块
        for category, articles in onews_data.items():
            for article in articles:
                if article.get("url") == target_url:
                    # 匹配成功，将 hot 字段设为 1
                    article["hot"] = 1
                    match_found = True
                    break # 跳出当前板块的循环
            if match_found:
                break # 跳出所有板块的循环
        
        # 如果没找到匹配的 URL，写入 error.txt
        if not match_found:
            with open(ERROR_FILE_PATH, 'a', encoding='utf-8') as err_f:
                err_f.write(json.dumps(today_item, ensure_ascii=False) + "\n")
    
    # 将修改后的数据写回 onews 文件
    with open(onews_file, 'w', encoding='utf-8') as f:
        json.dump(onews_data, f, ensure_ascii=False, indent=4)
        
    print(f"成功日志: 已成功处理并将数据更新至 {onews_filename}。")
    
    # 更新 version.json (传入今天的时间戳)
    update_version_json(LOCAL_SERVER_DIR, target_timestamp)
    
    # 将处理完的 TodayCNH 文件移动到废纸篓
    try:
        send2trash(file_to_process)
        print(f"成功日志: 已将 {filename} 移动到废纸篓。")
    except Exception as e:
        print(f"移动 {filename} 到废纸篓时出错: {e}")

if __name__ == "__main__":
    process_news_files()