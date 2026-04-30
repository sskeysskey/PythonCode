import re
import os
import sys
import hashlib
import glob
import shutil
import json
import html
import subprocess
import platform
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timedelta

# ================= 配置区域 =================

# 1. 动态获取当前用户的主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义 Coding 根目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 定义 Downloads 目录
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 4. 定义 News 相关目录
NEWS_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
LOCAL_SERVER_DIR = os.path.join(BASE_CODING_DIR, "LocalServer", "Resources", "ONews")

def alert_and_exit(message):
    """
    跨平台弹窗提醒；若失败则退回到打印。随后立即退出程序。
    """
    try:
        # <--- 修改：区分操作系统
        if platform.system() == 'Darwin':  # macOS
            subprocess.run([
                "osascript", "-e",
                f'display alert "缺少必要文件" message "{message}" as critical'
            ], check=False)
        else:
            # Windows/Linux 可以打印醒目日志，或者使用 ctypes (可选)
            print("\n" + "!" * 50)
            print(f"CRITICAL ERROR: {message}")
            print("!" * 50 + "\n")
    except Exception:
        pass
    
    # 无论如何都要打印并退出
    print(f"Alert: {message}")
    raise SystemExit(1)

def find_today_cnh_html(today, news_directory):
    """
    查找 backup/backup 目录 和 news_directory 根目录下的 TodayCNH_<today>.html。
    返回所有找到的文件路径列表。
    """
    paths = []
    
    # 1. 检查备份目录：News/backup/backup
    backup_dir = os.path.join(news_directory, "backup", "backup")
    candidate1 = os.path.join(backup_dir, f"TodayCNH_{today}.html")
    # 如果备份目录里有（可能是之前运行产生的），加上它
    if os.path.exists(candidate1):
        paths.append(candidate1)
    
    # 2. 检查根目录：News/ (这是当前最新的)
    candidate2 = os.path.join(news_directory, f"TodayCNH_{today}.html")
    # <--- 修改点：这里把 elif 改成了 if，确保即便备份存在，也会去读新的文件
    if os.path.exists(candidate2):
        paths.append(candidate2)
        
    # 额外：如果备份目录下有重命名过的文件（如 TodayCNH_260131_1.html），也可以尝试读取
    # 这样能保证一天内多次运行的所有元数据都被加载
    extra_backups = glob.glob(os.path.join(backup_dir, f"TodayCNH_{today}_*.html"))
    paths.extend(extra_backups)
    
    # 去重（防止路径重复）
    return list(set(paths))
    
def extract_site_name(url):
    try:
        # 移除 http:// 或 https:// 前缀
        url = re.sub(r'^https?://(www\.)?', '', url.lower())
        
        # 常见新闻网站的特殊处理
        if 'ft.com' in url:
            return 'FT'
        elif 'wsj.com' in url:
            return 'WSJ'
        elif 'rfi.fr' in url:
            return 'RFI'
        elif 'dw.com' in url:
            return 'DW'
        elif 'bloomberg.com' in url:
            return 'BLOOMBERG'
        elif 'reuters.com' in url:
            return 'REUTERS'
        elif 'nytimes.com' in url:
            return 'NYTIMES'
        elif 'washingtonpost.com' in url:
            return 'WASHINGTONPOST'
        elif 'economist.com' in url:
            return 'ECONOMIST'
        elif 'technologyreview.com' in url:
            return 'TECHNOLOGYREVIEW'
        elif 'bbc.com' in url:
            return 'BBC'
        
        # 对于其他网站，提取域名主体
        domain = url.split('/')[0]
        # 提取主域名
        parts = domain.split('.')
        if len(parts) >= 2:
            # 查找主域名（通常是倒数第二个部分）
            main_domain = parts[-2]
            site_name = main_domain.upper()
        else:
            # 否则只使用主域名
            site_name = parts[0].upper()
            
        return site_name
        
    except Exception as e:
        print(f"提取网站名称时出错 ({url}): {str(e)}")
        return "Other" # 出错时返回 Other

# ---- 站点显示名称映射（不区分大小写） ----
SITE_DISPLAY_MAP = {
    'ft':             '伦敦金融时报',
    'nytimes':        '纽约时报',
    'washingtonpost': '华盛顿邮报',
    'economist':      '经济学人',
    'technologyreview': '麻省理工技术评论',
    'techreview':       '麻省理工技术评论',
    'wsj':            '华尔街日报',
    'rfi':            '法广头条',
    'dw':            '德国之声',
    'wsjcn':          '华尔街日报中文网',
    'reuters':        '路透社',
    'bloomberg':      '布隆伯格金融',
    'nikkeiasia':     '日经新闻亚洲版',
    'bbc':            '英国广播公司',
}

# ---- 反向映射，用于生成 source_id ----
REVERSE_SITE_MAPPING = {
    "华尔街日报": "wsj",
    "华尔街日报中文网": "wsjcn",
    "伦敦金融时报": "ft",
    "法广头条": "rfi",
    "德国之声": "dw",
    "布隆伯格金融": "bloomberg",
    "路透社": "reuters",
    "经济学人": "economist",
    "日经新闻亚洲版": "nikkei",
    "华盛顿邮报": "washpost",
    "纽约时报": "nytimes",
    "麻省理工技术评论": "mittr",
    "英国广播公司": "bbc"
}

def compute_md5(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# --- 重要修改：backup_news_assets ---
def backup_news_assets(local_dir):
    timestamp = datetime.now().strftime("%y%m%d")
    
    src_img_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    src_json = os.path.join(NEWS_DIRECTORY, "onews.json")
    
    # 目标位置
    local_img_target = os.path.join(local_dir, f"news_images_{timestamp}")
    local_json_target = os.path.join(local_dir, f"onews_{timestamp}.json")
    
    # 备份目录位置
    backup_dir = os.path.join(DOWNLOADS_DIR, "backup")
    backup_file_dir = os.path.join(NEWS_DIRECTORY, "done")
    
    # 1) 合并图片目录
    if os.path.exists(src_img_dir):
        os.makedirs(local_img_target, exist_ok=True)
        # Python 3.8+ 支持 dirs_exist_ok
        shutil.copytree(src_img_dir, local_img_target, dirs_exist_ok=True)
        print(f"已将图片合并到: {local_img_target}")
        # 3) 删除原目录
        shutil.rmtree(src_img_dir)
        print(f"已删除原始图片目录: {src_img_dir}")
    else:
        print(f"未找到源图片目录: {src_img_dir}")
        
    # 1) 备份到 Downloads/backup
    backup_img_target = os.path.join(backup_dir, f"news_images_{timestamp}")
    if os.path.exists(backup_img_target):
        shutil.rmtree(backup_img_target)
    shutil.copytree(local_img_target, backup_img_target)
    print(f"图片目录已备份到: {backup_img_target}")
    
    # 2) 合并 JSON 文件
    if os.path.exists(src_json):
        tmp_json = os.path.join(local_dir, f"onews_{timestamp}_new.json")
        shutil.copy2(src_json, tmp_json)
        if os.path.exists(local_json_target):
            merge_json_groupwise(local_json_target, tmp_json)
            os.remove(tmp_json)
        else:
            os.rename(tmp_json, local_json_target)
            print(f"已备份 JSON 到: {local_json_target}")
        os.remove(src_json)
        print(f"已删除原始JSON文件: {src_json}")
    else:
        print(f"未找到源 JSON 文件: {src_json}")
        
    # 1) 备份到 Coding/News/done
    backup_file_target = os.path.join(backup_file_dir, f"onews_{timestamp}.json")
    os.makedirs(backup_file_dir, exist_ok=True) # 确保done目录存在
    shutil.copy2(local_json_target, backup_file_target)
    print(f"JSON文件已备份到: {backup_file_target}")
    
    update_version_json(local_dir, timestamp)

def update_version_json(local_dir, timestamp):
    version_path = os.path.join(local_dir, "version.json")
    if not os.path.exists(version_path):
        # 如果文件不存在，初始化一个基础结构，包含 update_time
        data = {
            "version": "1.0", 
            "files": [],
            "update_time": "" 
        }
    else:
        with open(version_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
    # 1. 更新现有文件的 MD5
    for item in data.get("files", []):
        if item.get("type") == "json":
            file_path = os.path.join(local_dir, item["name"])
            if os.path.isfile(file_path):
                new_md5 = compute_md5(file_path)
                if item.get("md5") != new_md5:
                    item["md5"] = new_md5
                    
    # 2. 准备添加新文件
    to_add = []
    json_name = f"onews_{timestamp}.json"
    json_path = os.path.join(local_dir, json_name)
    if os.path.isfile(json_path):
        to_add.append({
            "name": json_name,
            "type": "json",
            "md5": compute_md5(json_path)
        })
    img_name = f"news_images_{timestamp}"
    to_add.append({
        "name": img_name,
        "type": "images"
    })
    
    # 3. 确保 files 列表存在（兼容性处理）
    if "files" not in data:
        data["files"] = []

    # 4. 检查重复并添加
    existing_names = { item["name"] for item in data.get("files", []) }
    for e in to_add:
        if e["name"] not in existing_names:
            data["files"].append(e)
            print(f"已添加到 version.json: {e['name']}")

    # 5. 更新 update_time 为当前系统时间
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    data["update_time"] = current_time_str
    print(f"已更新 version.json 的 update_time 为: {current_time_str}")
            
    # 6. 保存文件
    with open(version_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"version.json 已更新")

def prune_old_assets(local_dir, days_to_keep):
    # 逻辑保持不变，路径拼接已在调用端处理
    version_path = os.path.join(local_dir, "version.json")
    if not os.path.exists(version_path): return
    print(f"\n开始清理超过 {days_to_keep} 天的旧资产...")
    with open(version_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    files_to_keep = []
    files_deleted_count = 0
    date_pattern = re.compile(r'_(\d{6})')
    for item in data.get("files", []):
        item_name = item.get("name", "")
        match = date_pattern.search(item_name)
        if not match:
            files_to_keep.append(item)
            continue
        try:
            file_date = datetime.strptime(match.group(1), "%y%m%d")
        except ValueError:
            files_to_keep.append(item)
            continue
            
        if file_date < cutoff_date:
            path_to_delete = os.path.join(local_dir, item_name)
            try:
                if item.get("type") == "json" and os.path.isfile(path_to_delete):
                    os.remove(path_to_delete)
                    files_deleted_count += 1
                    print(f"已删除: {item_name}")
                elif item.get("type") == "images" and os.path.isdir(path_to_delete):
                    shutil.rmtree(path_to_delete)
                    files_deleted_count += 1
                    print(f"已删除: {item_name}")
            except Exception as e:
                print(f"删除失败 {item_name}: {e}")
        else:
            files_to_keep.append(item)
            
    if files_deleted_count > 0:
        data["files"] = files_to_keep
        with open(version_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

def merge_json_groupwise(existing_path, new_path):
    with open(existing_path, 'r', encoding='utf-8') as f: data_old = json.load(f)
    with open(new_path, 'r', encoding='utf-8') as f: data_new = json.load(f)
    merged = {}
    for group, lst in {**data_old, **data_new}.items():
        a = data_old.get(group, [])
        b = data_new.get(group, [])
        combined = a + b
        seen = set()
        deduped = []
        for item in combined:
            key = (item.get("topic",""), item.get("url",""), item.get("article",""))
            if key not in seen:
                seen.add(key)
                
                # [新增] 检查并追加 hot 字段，保证合并时旧数据也拥有此字段
                if "hot" not in item:
                    item["hot"] = 0
                    
                deduped.append(item)
        merged[group] = deduped
    with open(existing_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)

def find_all_news_files(directory):
    pattern = os.path.join(directory, "News_*.txt")
    return sorted(glob.glob(pattern))
    
def move_cnh_file(source_dir):
    try:
        # 只查找根目录下的文件
        cnh_pattern = os.path.join(source_dir, "TodayCNH_*.html")
        # 排除掉 backup 子目录（glob 有时会递归，虽然这里写法不会，但为了保险）
        cnh_files = [f for f in glob.glob(cnh_pattern) if os.path.dirname(f) == source_dir]
        
        if not cnh_files:
            print("没有找到需要移动的 TodayCNH_ 开头的文件")
            return False
            
        backup_dir = os.path.join(source_dir, "backup", "backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        moved_count = 0
        for source_file in cnh_files:
            filename = os.path.basename(source_file)
            target_file = os.path.join(backup_dir, filename)
            
            # <--- 修改点：如果目标存在，进行重命名，防止覆盖旧的备份 --->
            if os.path.exists(target_file):
                print(f"警告: 备份目录已存在 {filename}，正在重命名...")
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(target_file):
                    target_file = os.path.join(backup_dir, f"{base}_{counter}{ext}")
                    counter += 1
            
            os.rename(source_file, target_file)
            print(f"成功移动文件: {filename} -> {os.path.basename(target_file)}")
            moved_count += 1
            
        return moved_count > 0
        
    except Exception as e:
        print(f"移动文件时出错: {str(e)}")
        return False

def parse_article_copier(file_path):
    url_images = {}
    current_url = None
    valid_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')
    
    try: # 增加错误处理，防止文件不存在
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"警告: article_copier 文件未找到: {file_path}")
        return {} # 返回空字典
        
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('http'):
            current_url = line
            url_images[current_url] = []
        elif any(line.lower().endswith(ext) for ext in valid_extensions) and current_url:
            url_images[current_url].append(line)
    
    print("解析到的URL和图片映射:")
    for url, images in url_images.items():
        print(f"URL: {url}")
        print(f"Images: {images}")
        
    return url_images

# --- 修改：将移动到 done 目录改为移动到系统垃圾箱 ---
def trash_processed_txt_files(directory):
    """
    将所有 News_*.txt 文件移动到系统垃圾箱。
    如果未安装 send2trash 库，则退化为永久删除。
    """
    try:
        from send2trash import send2trash
        trash_func = send2trash
        is_permanent = False
    except ImportError:
        print("警告: 未安装 send2trash 库，无法移动到垃圾箱。将执行永久删除。")
        print("如需移动到垃圾箱，请执行: pip install send2trash")
        trash_func = os.remove
        is_permanent = True

    txt_files_to_trash = find_all_news_files(directory)
    if not txt_files_to_trash:
        print(f"在 {directory} 目录中没有找到需要删除的 News_*.txt 文件。")
        return
    
    action_name = "永久删除" if is_permanent else "移动到垃圾箱"
    print(f"准备将 {len(txt_files_to_trash)} 个 TXT 文件{action_name}...")
    
    trashed_count = 0
    for source_path in txt_files_to_trash:
        if not os.path.exists(source_path):
            continue
        
        original_basename = os.path.basename(source_path)
        
        try:
            trash_func(source_path)
            print(f"已{action_name}: {original_basename}")
            trashed_count += 1
        except Exception as e:
            print(f"处理文件 {original_basename} 时出错: {e}")
            
    print(f"清理完成，共成功处理 {trashed_count} 个文件。")

# --- 新增功能 1: 移动 article_copier 文件 ---
def move_article_copier_files(source_dir, backup_parent_dir):
    """
    将 source_dir 下所有 article_copier_*.txt 文件移动到 backup_parent_dir/backup 目录下。
    如果目标文件已存在，则重命名以避免覆盖。
    """
    backup_dir = os.path.join(backup_parent_dir, "backup") # 目标是 News/backup
    os.makedirs(backup_dir, exist_ok=True) # 确保 backup 目录存在
    
    pattern = os.path.join(source_dir, "article_copier_*.txt")
    files_to_move = glob.glob(pattern)
    
    if not files_to_move:
        print(f"在 {source_dir} 未找到 article_copier_*.txt 文件。")
        return
        
    print(f"\n--- 开始移动 article_copier 文件到 {backup_dir} ---")
    moved_count = 0
    for source_path in files_to_move:
        filename = os.path.basename(source_path)
        target_path = os.path.join(backup_dir, filename)
        
        # 检查重名冲突
        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(target_path):
            new_filename = f"{base}_copy_{counter}{ext}"
            target_path = os.path.join(backup_dir, new_filename)
            print(f"警告: 文件 {filename} 已存在于备份目录，尝试重命名为 {new_filename}")
            counter += 1
            
        # 移动文件
        try:
            shutil.move(source_path, target_path)
            print(f"成功移动: {filename} -> {os.path.basename(target_path)}")
            moved_count += 1
        except Exception as e:
            print(f"移动文件 {filename} 时出错: {str(e)}")
            
    print(f"--- 完成移动 article_copier 文件，共移动 {moved_count} 个文件 ---")

def normalize_url(u):
    """
    去掉 query 和 fragment，末尾去掉 '/'
    """
    parts = urlsplit(u)
    new = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
    return new

def split_zh_en(text):
    """
    将文章内容拆分为中文部分和英文部分。
    """
    lines = text.strip().split('\n')
    split_index = -1
    
    for i, line in enumerate(lines):
        line_strip = line.strip()
        if not line_strip:
            continue
            
        # Check language characteristics
        has_zh = bool(re.search(r'[\u4e00-\u9fff]', line_strip))
        has_en = bool(re.search(r'[a-zA-Z]', line_strip))
        
        # Candidate for start of English section:
        # - Has English
        # - Has NO Chinese
        if not has_zh and has_en:
            # Check 1: Preceded by empty line (or start of text)
            prev_is_empty = (i == 0) or (not lines[i-1].strip())
            
            if prev_is_empty:
                # Check 2: Check length to avoid bullet points like "1." 
                # (though "1." usually has no En chars if just numbers, but "FT" might)
                en_count = len(re.findall(r'[a-zA-Z]', line_strip))
                if en_count > 3:
                    # Check 3 (Lookahead): Ensure the next few lines are also not Chinese
                    # This prevents splitting on an isolated English sentence inside Chinese text.
                    is_english_block = True
                    checked_lines = 0
                    for k in range(i + 1, len(lines)):
                        next_line = lines[k].strip()
                        if not next_line:
                            continue
                        
                        if re.search(r'[\u4e00-\u9fff]', next_line):
                            is_english_block = False
                            break
                        
                        checked_lines += 1
                        if checked_lines >= 2: # Check next 2 non-empty lines is sufficient
                            break
                    
                    if is_english_block:
                        split_index = i
                        break
    
    if split_index != -1:
        # Found the split point
        zh_part = '\n'.join(lines[:split_index]).strip()
        en_part = '\n'.join(lines[split_index:]).strip()
        return zh_part, en_part
    
    # If no split found (e.g. WSJCN), return all as first part
    return text.strip(), ""

def generate_news_json(news_directory, today, cnh_html_paths=None):
    """
    扫描 News_*.txt、TodayCNH_*.html、article_copier_{today}.txt，

    新增: 若 cnh_html_paths 提供，则仅使用这些 HTML（通常是当天的唯一文件）。
    """
    # 1. 解析 TodayCNH_*.html -> { norm_url: (site, topic, original_url, topic_eng) }
    #    **改动**: 增加 parsing 逻辑以支持提取 title-eng
    cnh_map = {}
    if cnh_html_paths is None:
        # 兼容旧逻辑：遍历目录中所有 TodayCNH_*.html
        html_files = glob.glob(os.path.join(news_directory, f"TodayCNH_*.html"))
    else:
        # 只使用传入的（已确认存在的）路径
        html_files = cnh_html_paths
        
    for html_path in html_files:
        with open(html_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        # 使用更稳健的方式遍历表格行
        for tr_match in re.finditer(r"<tr>(.*?)</tr>", text, re.S):
            tr_content = tr_match.group(1)
            
            # 提取基础信息：站点和标题链接
            # 匹配 <td>SITE</td>...<a href="URL">TITLE</a>
            basic_match = re.search(
                r"<td>\s*([^<]+)\s*</td>.*?<a\s+href=\"([^\"]+)\"[^>]*>([^<]+)</a>", 
                tr_content, re.S
            )
            
            if basic_match:
                site = basic_match.group(1).strip()
                original_url = basic_match.group(2).strip()
                title_raw = basic_match.group(3).strip()
                
                # 尝试提取英文标题 (class="title-eng")
                topic_eng = ""
                eng_match = re.search(r"<td\s+class=\"title-eng\">\s*(.*?)\s*</td>", tr_content, re.S)
                if eng_match:
                    raw_eng = html.unescape(eng_match.group(1).strip())
                    # 清理标题：移除开头的箭头和多余空白
                    # 比如 "→\n Day two..." -> "Day two..."
                    topic_eng = re.sub(r'^[→\s]+', '', raw_eng).strip()
                    # 将内部的换行符替换为空格
                    topic_eng = re.sub(r'\s+', ' ', topic_eng)
                
                # 数据清洗
                nu = normalize_url(original_url)
                title_decoded = html.unescape(title_raw)
                
                # --- 修改点：移除 title_decoded 中间的所有换行和空格 ---
                title_decoded = re.sub(r'\s+', '', title_decoded)
                
                # 移除开头的数字序号
                topic = re.sub(r'^[0-9０-９]+[、,，.]\s*', '', title_decoded)
                
                # 存入 map
                cnh_map[nu] = (site, topic, original_url, topic_eng)

    # 2. 解析 article_copier_{today}.txt -> { norm_url: [img1, img2, ...] }
    copier_path = os.path.join(news_directory, f"article_copier_{today}.txt")
    url_images_raw = {}
    if os.path.exists(copier_path):
        url_images_raw = parse_article_copier(copier_path)
    # 归一化键
    url_images = {
        normalize_url(u): imgs
        for u, imgs in url_images_raw.items()
    }

    # 3. 组装 data
    data = {}
    for txt_path in glob.glob(os.path.join(news_directory, "News_*.txt")):
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        entries = []
        current_url = None
        buf = []

        for line in content.splitlines():
            raw = line.strip().lstrip('\ufeff')
            if raw.startswith("http"):
                if current_url is not None:
                    entries.append((current_url, "\n".join(buf).strip()))
                current_url = raw
                buf = []
            else:
                if current_url:
                    # 修改：保留所有行（即使是空行），以保留段落结构和中英文间的分隔
                    buf.append(raw)
                    
        if current_url is not None:
            entries.append((current_url, "\n".join(buf).strip()))

        for url, article_text in entries:
            nu = normalize_url(url)
            
            # 默认值
            topic_eng = ""
            article_eng = ""
            
            # 修改：优先使用 cnh_map 中的信息
            if nu in cnh_map:
                site_code, topic, original_url_from_map, topic_eng = cnh_map[nu]
                imgs = url_images.get(nu, [])
                display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)
            else:
                # 如果在 HTML 中找不到，尝试从 URL 推断站点信息
                site_code = extract_site_name(url)
                # 尝试从文章内容的第一行提取标题作为主题
                first_line = article_text.split('\n')[0].strip() if article_text else ""
                # 如果第一行太长，截取前100个字符
                topic = first_line[:100] + "..." if len(first_line) > 100 else first_line
                if not topic:
                    topic = "未知主题"
                
                original_url_from_map = url
                imgs = url_images.get(nu, [])
                display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)
                
                print(f"注意：URL {url} 未在 HTML 中找到，使用推断信息: 站点={site_code}, 主题={topic[:50]}...")
            
            # --- 分割中英文内容 ---
            article_zh, article_eng = split_zh_en(article_text)
            
            # --- 获取 source_id ---
            source_id = REVERSE_SITE_MAPPING.get(display_site, "unknown")
            
            data.setdefault(display_site, []).append({
                "source_id": source_id,
                "topic":   topic,
                "topic_eng": topic_eng,
                "url":     original_url_from_map,
                "article": article_zh,
                "article_eng": article_eng,
                "images":  imgs,
                "hot": 0  # [新增] 默认写入 hot 字段为 0
            })
            
    out_path = os.path.join(news_directory, f"onews.json")
    with open(out_path, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=4)
    print(f"\n已生成 JSON 文件: {out_path}")

# ================= 新增：预运行检查函数 =================
def pre_run_checks(news_directory):
    """
    1. 检查运行时间是否在 00:00 - 11:59 之间。
    2. 检查特定文件的日期后缀：
       - 如果同时存在昨天和今天的文件（针对 article_copier 和 News_），则合并内容。
       - 如果日期超前（未来），重命名为当前日期。
       - 如果日期滞后（过去），也重命名为当前日期（强制更新为今天）。
    """
    now = datetime.now()
    
    # 1. 判断运行时间是否是午夜12点到下午18点之间 (0 <= hour < 18)
    if not (0 <= now.hour < 18):
        print(f"\n[提示] 当前时间是 {now.strftime('%H:%M')}，不在允许运行的时间段（00:00 - 18:00）内。程序将退出。\n")
        sys.exit(0)
        
    print(f"\n[提示] 时间检查通过，当前时间 {now.strftime('%H:%M')} 处于 00:00 到 18:00 之间。")
    
    # 获取今天和昨天的日期字符串
    yesterday = now - timedelta(days=1)
    
    current_date_yymmdd = now.strftime("%y%m%d")      # 格式: 260420
    current_date_yy_mm_dd = now.strftime("%y_%m_%d")  # 格式: 26_04_20
    
    yesterday_yymmdd = yesterday.strftime("%y%m%d")
    yesterday_yy_mm_dd = yesterday.strftime("%y_%m_%d")

    print(f"[提示] 正在检查 {news_directory} 目录下的文件...")

    # ==========================================
    # 新增逻辑：合并昨天和今天同时存在的文件
    # ==========================================
    def merge_files_if_both_exist(prefix, date_format_today, date_format_yesterday):
        file_today = os.path.join(news_directory, f"{prefix}{date_format_today}.txt")
        file_yest = os.path.join(news_directory, f"{prefix}{date_format_yesterday}.txt")
        
        if os.path.isfile(file_today) and os.path.isfile(file_yest):
            print(f"[合并] 发现 {prefix} 同时存在昨天和今天的文件，正在合并...")
            
            # 读取昨天的内容并去除首尾多余的换行符
            with open(file_yest, 'r', encoding='utf-8') as f_yest:
                content_yest = f_yest.read().strip('\n')
                
            # 读取今天的内容并去除首尾多余的换行符
            with open(file_today, 'r', encoding='utf-8') as f_today:
                content_today = f_today.read().strip('\n')
                
            # 合并规则：昨天内容 + 1个空行(即两个换行符) + 今天内容
            # 如果某一天文件完全为空，则避免多出空行
            if content_yest and content_today:
                merged_content = content_yest + "\n\n" + content_today
            else:
                merged_content = content_yest + content_today
                
            # 写入今天的文件
            with open(file_today, 'w', encoding='utf-8') as f_out:
                f_out.write(merged_content)
                
            # 删除昨天的文件，避免后续被重命名逻辑再次处理
            os.remove(file_yest)
            print(f"[合并] 合并完成，已删除昨天的文件: {os.path.basename(file_yest)}")

    # 检查并合并 article_copier
    merge_files_if_both_exist("article_copier_", current_date_yymmdd, yesterday_yymmdd)
    # 检查并合并 News_
    merge_files_if_both_exist("News_", current_date_yy_mm_dd, yesterday_yy_mm_dd)

    # ==========================================
    # 原有逻辑：检查并重命名日期不等于今天的文件
    # ==========================================
    for filename in os.listdir(news_directory):
        filepath = os.path.join(news_directory, filename)
        if not os.path.isfile(filepath):
            continue
            
        # 检查 article_copier_YYMMDD.txt
        match_copier = re.match(r'^article_copier_(\d{6})\.txt$', filename)
        if match_copier:
            file_date_str = match_copier.group(1)
            file_date = datetime.strptime(file_date_str, "%y%m%d")
            if file_date.date() < now.date():
                new_filename = f"article_copier_{current_date_yymmdd}.txt"
                new_filepath = os.path.join(news_directory, new_filename)
                os.rename(filepath, new_filepath)
                print(f"[重命名] 发现超前日期文件: {filename} -> {new_filename}")
                
        # 检查 TodayCNH_YYMMDD.html
        match_cnh = re.match(r'^TodayCNH_(\d{6})\.html$', filename)
        if match_cnh:
            file_date_str = match_cnh.group(1)
            file_date = datetime.strptime(file_date_str, "%y%m%d")
            if file_date.date() < now.date():
                new_filename = f"TodayCNH_{current_date_yymmdd}.html"
                new_filepath = os.path.join(news_directory, new_filename)
                os.rename(filepath, new_filepath)
                print(f"[重命名] 发现超前日期文件: {filename} -> {new_filename}")
                
        # 检查 News_YY_MM_DD.txt
        match_news = re.match(r'^News_(\d{2}_\d{2}_\d{2})\.txt$', filename)
        if match_news:
            file_date_str = match_news.group(1)
            file_date = datetime.strptime(file_date_str, "%y_%m_%d")
            if file_date.date() < now.date():
                new_filename = f"News_{current_date_yy_mm_dd}.txt"
                new_filepath = os.path.join(news_directory, new_filename)
                os.rename(filepath, new_filepath)
                print(f"[重命名] 发现超前日期文件: {filename} -> {new_filename}")
    print("[提示] 文件日期检查完毕。\n")

if __name__ == "__main__":
    pre_run_checks(NEWS_DIRECTORY)

    today = datetime.now().strftime("%y%m%d")
    
    # <--- 使用前面定义的动态路径常量
    news_directory = NEWS_DIRECTORY
    article_copier_path = os.path.join(NEWS_DIRECTORY, f"article_copier_{today}.txt")
    image_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    downloads_path = DOWNLOADS_DIR
    local_server_dir = LOCAL_SERVER_DIR
    
    # 0. 先查找当天的 TodayCNH_<today>.html
    cnh_html_paths = find_today_cnh_html(today, news_directory)

    if not cnh_html_paths:
        # 两处都找不到 -> 弹窗并终止
        alert_and_exit(
            f"未找到当天的 TodayCNH_{today}.html。\n"
            f"请检查以下路径：\n"
            f"1) {os.path.join(news_directory, 'backup', 'backup')}\n"
            f"2) {news_directory}\n"
            f"找到后再重试。"
        )

    # 1. 生成 JSON 汇总（使用已确认存在的当天 TodayCNH HTML 文件）
    print("\n" + "=" * 10 + " 1. 开始生成 JSON 汇总 " + "=" * 10)
    generate_news_json(news_directory, today, cnh_html_paths=cnh_html_paths)
    print("=" * 10 + " 完成生成 JSON 汇总 " + "=" * 10)

    # 3. 移动 TodayCNH 文件 (如果需要)
    print("\n" + "=" * 10 + " 2. 开始移动 TodayCNH 文件 " + "=" * 10)
    move_cnh_file(news_directory)
    print("=" * 10 + " 完成移动 TodayCNH 文件 " + "=" * 10)

    # 4. 清理 Downloads 目录下的 .html 文件
    print("\n" + "=" * 10 + " 3. 开始清理 Downloads 中的 HTML 文件 " + "=" * 10)
    html_files = [f for f in os.listdir(downloads_path) if f.endswith('.html')]

    if html_files:
        for file in html_files:
            file_path = os.path.join(downloads_path, file)

            try:
                os.remove(file_path)
                print(f'成功删除 HTML 文件: {file}')
            except OSError as e:
                print(f'删除 HTML 文件失败 {file}: {e}')
    else:
        print("Downloads 目录下没有找到 .html 文件。")

    print("=" * 10 + " 完成清理 Downloads 中的 HTML 文件 " + "=" * 10)

    # 5. 移动 article_copier 文件到 backup
    print("\n" + "=" * 10 + " 4. 开始移动 article_copier 文件 " + "=" * 10)
    move_article_copier_files(news_directory, news_directory)
    print("=" * 10 + " 完成移动 article_copier 文件 " + "=" * 10)

    # 修改调用：从移动到 done 改为移动到垃圾箱
    print("\n" + "=" * 10 + " 5. 开始清理已处理的 TXT 文件 " + "=" * 10)
    trash_processed_txt_files(news_directory)
    print("=" * 10 + " 完成清理已处理的 TXT 文件 " + "=" * 10)

    # 7. 将news_images和onews.json备份到相应目录下并更新version.json
    print("\n" + "=" * 10 + " 6. 开始备份核心资产 " + "=" * 10)
    backup_news_assets(local_server_dir)
    print("=" * 10 + " 完成备份核心资产 " + "=" * 10)

    # 8. 清理超过10天的旧文件和目录
    print("\n" + "=" * 10 + " 7. 开始清理旧资产 " + "=" * 10)
    prune_old_assets(local_server_dir, days_to_keep=10)
    print("=" * 10 + " 完成清理旧资产 " + "=" * 10)

    timestamp = datetime.now().strftime("%y%m%d")

    # 2. 然后，执行原有的 version.json 更新逻辑
    #    它会为所有 json 文件（包括刚刚被修改的）重新计算 MD5
    update_version_json(local_server_dir, timestamp)