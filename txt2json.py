from datetime import datetime, timedelta # <--- 新增导入
import re
import os
import hashlib
import glob
import shutil
import json
from urllib.parse import urlsplit, urlunsplit

# ---- 站点显示名称映射（不区分大小写） ----测试
SITE_DISPLAY_MAP = {
    'ft':             '伦敦金融时报',
    'nytimes':        '纽约时报',
    'washingtonpost': '华盛顿邮报',
    'economist':      '经济学人',
    'technologyreview': '麻省理工技术评论',
    'techreview':       '麻省理工技术评论',   # 以防 HTML 里写的是 TechReview
    'wsj':            '华尔街日报',
    'wsjcn':          '华尔街日报中文网',
    'reuters':        '路透社',
    'bloomberg':      '布隆伯格金融',
    'nikkeiasia':     '日经新闻亚洲版',
}

def compute_md5(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def find_all_news_files(directory):
    pattern = os.path.join(directory, "News_*.txt")
    return sorted(glob.glob(pattern))

def move_cnh_file(source_dir):
    try:
        cnh_pattern = os.path.join(source_dir, "TodayCNH_*.html")
        cnh_files = glob.glob(cnh_pattern)
        
        if not cnh_files:
            print("没有找到TodayCNH_开头的文件")
            return False
            
        source_file = cnh_files[0]
        backup_dir = os.path.join(source_dir, "backup", "backup")
        os.makedirs(backup_dir, exist_ok=True)
        target_file = os.path.join(backup_dir, os.path.basename(source_file))
        os.rename(source_file, target_file)
        print(f"成功移动文件: {os.path.basename(source_file)} -> {backup_dir}")
        return True
        
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

def move_processed_txt_files(directory):
    """
    将所有 News_*.txt 文件移动到 'done' 子目录中。
    如果目标文件已存在，则重命名以避免覆盖。
    """
    done_dir = os.path.join(directory, "done")
    os.makedirs(done_dir, exist_ok=True)

    txt_files_to_move = find_all_news_files(directory)

    if not txt_files_to_move:
        print(f"在 {directory} 目录中没有找到需要移动的 News_*.txt 文件。")
        return
    
    print(f"准备移动 {len(txt_files_to_move)} 个 TXT 文件到 '{done_dir}' 目录...")
    moved_count = 0
    for source_path in txt_files_to_move:
        # 再次确认文件存在，以防万一
        if not os.path.exists(source_path):
            continue
        
        original_basename = os.path.basename(source_path)
        target_path = os.path.join(done_dir, original_basename)

        # 检查目标文件是否存在，如果存在则重命名
        if os.path.exists(target_path):
            print(f"警告: 文件 '{original_basename}' 已存在于 'done' 目录中。将重命名后移动。")
            base, ext = os.path.splitext(original_basename)
            counter = 1
            # 循环查找一个不重复的文件名
            while os.path.exists(target_path):
                new_basename = f"{base}_{counter}{ext}"
                target_path = os.path.join(done_dir, new_basename)
                counter += 1
        
        # 移动文件到最终确定的路径
        try:
            shutil.move(source_path, target_path)
            print(f"已移动: {original_basename} -> {os.path.basename(target_path)}")
            moved_count += 1
        except Exception as e:
            print(f"移动文件 {original_basename} 时出错: {e}")
            
    print(f"移动完成，共成功移动 {moved_count} 个文件。")


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

def generate_news_json(news_directory, today):
    """
    扫描 News_*.txt、TodayCNH_*.html、article_copier_{today}.txt，
    生成分组的 JSON 并写入 news_<timestamp>.json。
    """
    # 1. 解析 TodayCNH_*.html -> { norm_url: (site, topic, original_url) }
    #    **改动**: cnh_map 中增加存储原始 URL
    cnh_map = {}
    for html_path in glob.glob(os.path.join(news_directory, f"TodayCNH_*.html")):
        with open(html_path, 'r', encoding='utf-8') as f:
            text = f.read()
        # 匹配 <tr>…<td>SITE</td>…<a href="URL">TITLE</a>
        for site, url, title in re.findall(
            r"<tr>.*?<td>\s*([^<]+)\s*</td>.*?<a\s+href=\"([^\"]+)\"[^>]*>([^<]+)</a>",
            text, re.S):
            original_url = url.strip()
            nu = normalize_url(original_url)
            site = site.strip()
            # 这里把全/半角数字+逗号都去掉
            topic = re.sub(r'^[0-9０-９]+[、,，]\s*', '', title.strip())
            cnh_map[nu] = (site, topic, original_url) # 保存站点、主题和原始URL

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
                # 碰到新 URL，先把上一个 append
                if current_url is not None:
                    entries.append((current_url, "\n".join(buf).strip()))
                current_url = raw
                buf = []
            else:
                if current_url and raw:
                    buf.append(raw)
        # 最后一条
        if current_url is not None:
            entries.append((current_url, "\n".join(buf).strip()))

        # 每条 entry 去匹配 site/topic/images
        for url, article_text in entries:
            nu = normalize_url(url)
            if nu not in cnh_map:
                continue

            site_code, topic, original_url_from_map = cnh_map[nu]
            imgs = url_images.get(nu, [])

            # 查表，取映射后的显示名称，默认回退到原 site_code
            display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)

            data.setdefault(display_site, []).append({
                "topic":   topic,
                "url":     original_url_from_map,
                "article": article_text,
                "images":  imgs
            })

    # 4. 写 JSON
    out_path = os.path.join(news_directory, f"onews.json")
    with open(out_path, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=4)
    print(f"\n已生成 JSON 文件: {out_path}")

def backup_news_assets(local_dir):
    timestamp = datetime.now().strftime("%y%m%d")
    # 原始资源位置
    src_img_dir = "/Users/yanzhang/Downloads/news_images"
    src_json = "/Users/yanzhang/Coding/News/onews.json"
    
    # 目标位置
    local_img_target = os.path.join(local_dir, f"news_images_{timestamp}")
    local_json_target = os.path.join(local_dir, f"onews_{timestamp}.json")

    # 备份目录位置
    backup_dir = "/Users/yanzhang/Downloads/backup"
    backup_file_dir = "/Users/yanzhang/Coding/News/done"

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
        # 先把最新的 JSON 拷贝到一个临时文件
        tmp_json = os.path.join(local_dir, f"onews_{timestamp}_new.json")
        shutil.copy2(src_json, tmp_json)
        if os.path.exists(local_json_target):
            # 如果已有同名文件，则合并
            merge_json_groupwise(local_json_target, tmp_json)
            os.remove(tmp_json)
        else:
            # 第一次备份，直接重命名
            os.rename(tmp_json, local_json_target)
            print(f"已备份 JSON 到: {local_json_target}")
        
        # 3) 删除原文件
        os.remove(src_json)
        print(f"已删除原始JSON文件: {src_json}")
    else:
        print(f"未找到源 JSON 文件: {src_json}")

    # 1) 备份到 Coding/News/done
    backup_file_target = os.path.join(backup_file_dir, f"onews_{timestamp}.json")
    shutil.copy2(local_json_target, backup_file_target)
    print(f"JSON文件已备份到: {backup_file_target}")

    # 3) 更新 version.json（保持原有逻辑不变）
    update_version_json(local_dir, timestamp)


def update_version_json(local_dir, timestamp):
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
    
    # 2) 先遍历已有条目，如果是 json，就重新计算 MD5 并更新
    for item in data.get("files", []):
        if item.get("type") == "json":
            file_path = os.path.join(local_dir, item["name"])
            if os.path.isfile(file_path):
                new_md5 = compute_md5(file_path)
                if item.get("md5") != new_md5:
                    print(f"更新 MD5: {item['name']} {item.get('md5','')} -> {new_md5}")
                    item["md5"] = new_md5
    
    # 3) 准备本次要追加的条目
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
    
    # 4) 去重并追加
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

# --- 新增功能：清理旧的资产 ---
def prune_old_assets(local_dir, days_to_keep):
    """
    清理 version.json 和本地目录中超过指定天数的旧文件和目录。

    Args:
        local_dir (str): 资产所在的目录 (例如 /Users/yanzhang/Coding/LocalServer/Resources/ONews)。
        days_to_keep (int): 文件和目录保留的天数。
    """
    version_path = os.path.join(local_dir, "version.json")
    if not os.path.exists(version_path):
        print(f"未找到 version.json，跳过清理。")
        return

    print(f"\n开始清理超过 {days_to_keep} 天的旧资产...")

    try:
        with open(version_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"读取 version.json 时出错: {e}。无法进行清理。")
        return

    # 计算截止日期
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    files_to_keep = []
    files_deleted_count = 0
    
    # 正则表达式用于从文件名中提取 YYMMDD 日期
    date_pattern = re.compile(r'_(\d{6})')

    for item in data.get("files", []):
        item_name = item.get("name", "")
        match = date_pattern.search(item_name)
        
        if not match:
            # 如果文件名不符合 'name_YYMMDD' 格式，默认保留
            print(f"警告: '{item_name}' 不含标准日期戳，将予以保留。")
            files_to_keep.append(item)
            continue
            
        date_str = match.group(1)
        try:
            file_date = datetime.strptime(date_str, "%y%m%d")
        except ValueError:
            # 日期格式错误，保留并警告
            print(f"警告: '{item_name}' 中的日期 '{date_str}' 格式错误，将予以保留。")
            files_to_keep.append(item)
            continue

        if file_date < cutoff_date:
            # 此文件/目录已过期，需要删除
            print(f"发现过期资产: {item_name} (日期: {file_date.strftime('%Y-%m-%d')})")
            path_to_delete = os.path.join(local_dir, item_name)
            
            try:
                if item.get("type") == "json" and os.path.isfile(path_to_delete):
                    os.remove(path_to_delete)
                    print(f"  - 已删除文件: {path_to_delete}")
                    files_deleted_count += 1
                elif item.get("type") == "images" and os.path.isdir(path_to_delete):
                    shutil.rmtree(path_to_delete)
                    print(f"  - 已删除目录: {path_to_delete}")
                    files_deleted_count += 1
                elif not os.path.exists(path_to_delete):
                    print(f"  - 警告: 资产已不存在于磁盘，仅从 version.json 中移除。")
                else:
                    print(f"  - 警告: 类型未知或路径类型不匹配，跳过删除磁盘文件。")

            except OSError as e:
                print(f"  - 错误: 删除 '{path_to_delete}' 时失败: {e}")
        else:
            # 文件/目录未过期，保留
            files_to_keep.append(item)

    if files_deleted_count > 0 or len(files_to_keep) != len(data.get("files", [])):
        # 如果有任何变动，则更新 version.json
        data["files"] = files_to_keep
        try:
            with open(version_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"\nversion.json 已更新，移除了过期的条目。")
        except IOError as e:
            print(f"错误: 无法写回更新后的 version.json: {e}")
    else:
        print("\n没有找到需要清理的过期资产。")

def merge_json_groupwise(existing_path, new_path):
    """
    将 new_path 中的 JSON 内容按 top-level key（组名）合并到 existing_path。
    去重逻辑：如果同一组下出现完全相同的条目（topic+url+article），只保留一份。
    """
    def load(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    data_old = load(existing_path)
    data_new = load(new_path)
    merged = {}

    for group, lst in {**data_old, **data_new}.items():
        # 合并两个 dict 下同名 group 的列表
        a = data_old.get(group, [])
        b = data_new.get(group, [])
        combined = a + b
        # 去重：根据 topic + url + article 字段去重
        seen = set()
        deduped = []
        for item in combined:
            key = (
                item.get("topic",""),
                item.get("url",""),
                item.get("article","")
            )
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        merged[group] = deduped

    # 写回 existing_path
    with open(existing_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)
    print(f"合并并更新 JSON: {existing_path}")

if __name__ == "__main__":
    today = datetime.now().strftime("%y%m%d")
    news_directory = "/Users/yanzhang/Coding/News/"
    article_copier_path = f"/Users/yanzhang/Coding/News/article_copier_{today}.txt"
    image_dir = f"/Users/yanzhang/Downloads/news_images"
    downloads_path = '/Users/yanzhang/Downloads'
    # 定义本地服务器资源目录，方便复用
    local_server_dir = "/Users/yanzhang/Coding/LocalServer/Resources/ONews"

    # 2. 生成 JSON 汇总
    print("\n" + "="*10 + " 2. 开始生成 JSON 汇总 " + "="*10)
    generate_news_json(news_directory, today)
    print("="*10 + " 完成生成 JSON 汇总 " + "="*10)

    # 3. 移动 TodayCNH 文件 (如果需要)
    print("\n" + "="*10 + " 3. 开始移动 TodayCNH 文件 " + "="*10)
    move_cnh_file(news_directory)
    print("="*10 + " 完成移动 TodayCNH 文件 " + "="*10)

    # 4. 清理 Downloads 目录下的 .html 文件
    print("\n" + "="*10 + " 4. 开始清理 Downloads 中的 HTML 文件 " + "="*10)
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
    print("="*10 + " 完成清理 Downloads 中的 HTML 文件 " + "="*10)

    # 5. 移动 article_copier 文件到 backup
    print("\n" + "="*10 + " 5. 开始移动 article_copier 文件 " + "="*10)
    move_article_copier_files(news_directory, news_directory)
    print("="*10 + " 完成移动 article_copier 文件 " + "="*10)

    # 6. 将所有处理过的 TXT 文件移动到 done 目录
    print("\n" + "="*10 + " 6. 开始移动已处理的 TXT 文件 " + "="*10)
    move_processed_txt_files(news_directory)
    print("="*10 + " 完成移动已处理的 TXT 文件 " + "="*10)

    # 7. 将news_images和onews.json备份到相应目录下并更新version.json
    print("\n" + "="*10 + " 7. 开始备份核心资产 " + "="*10)
    backup_news_assets(local_server_dir)
    print("="*10 + " 完成备份核心资产 " + "="*10)

    # 8. 新增：清理超过3天的旧文件和目录
    print("\n" + "="*10 + " 8. 开始清理旧资产 " + "="*10)
    prune_old_assets(local_server_dir, days_to_keep=3)
    print("="*10 + " 完成清理旧资产 " + "="*10)