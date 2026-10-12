import re
import os
import hashlib
import glob
import shutil
import json
import html
import random
import tempfile
import subprocess
import platform
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timedelta, time as dtime

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

# 5. 时间戳相关配置
TIMESTAMP_STATE_FILE = os.path.join(NEWS_DIRECTORY, "onews_timestamp.txt")  # 保存上次截止时间
TIMESTAMP_FIELD = "timestamp"                 # 写入项目的字段名
TIME_FMT = "%Y-%m-%d %H:%M:%S"
SLOT_LENGTH = timedelta(minutes=30)           # 每次运行的时间段长度
EVENING_FIRST_START = dtime(0, 1, 0)          # 晚间首次运行的起点：次日 00:01:00
MORNING_SESSION_START_HOUR = 5                # [05:00, 18:00) 视为早间
EVENING_SESSION_START_HOUR = 18               # [18:00, 次日05:00) 视为晚间

_rng = random.SystemRandom()


# ================= 通用工具 =================

def atomic_write_text(path, text):
    """先写同目录临时文件，再原子替换；保留原文件权限，新文件默认 644。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    existed = os.path.exists(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            if existed:
                shutil.copymode(path, tmp)
            else:
                os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=4))


def alert_and_exit(message):
    """
    跨平台弹窗提醒；若失败则退回到打印。随后立即退出程序。
    """
    try:
        if platform.system() == 'Darwin':  # macOS
            safe = message.replace('\\', '\\\\').replace('"', '\\"')
            subprocess.run([
                "osascript", "-e",
                f'display alert "缺少必要文件" message "{safe}" as critical'
            ], check=False)
        else:
            print("\n" + "!" * 50)
            print(f"CRITICAL ERROR: {message}")
            print("!" * 50 + "\n")
    except Exception:
        pass

    print(f"Alert: {message}")
    raise SystemExit(1)


# ================= 时段 / 时间戳逻辑 =================

def resolve_session(now):
    """
    返回 (session, news_date)
      - 05:00~17:59 -> ("morning", 当天)
      - 18:00~23:59 -> ("evening", 次日)
      - 00:00~04:59 -> ("evening", 当天)   # 属于前一晚的延续
    news_date 即时间戳所在日期，也是 onews_YYMMDD.json 等文件使用的日期。
    """
    if MORNING_SESSION_START_HOUR <= now.hour < EVENING_SESSION_START_HOUR:
        return "morning", now.date()
    if now.hour >= EVENING_SESSION_START_HOUR:
        return "evening", now.date() + timedelta(days=1)
    return "evening", now.date()


def in_expected_window(now):
    """是否处于常规运行窗口：07:00-12:30 或 22:30-次日01:30（仅用于提示）。"""
    t = now.time()
    return (dtime(7, 0) <= t <= dtime(12, 30)) or t >= dtime(22, 30) or t <= dtime(1, 30)


def read_timestamp_state(path=TIMESTAMP_STATE_FILE):
    """读取上次截止时间；不存在/为空/格式非法返回 None。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
    except OSError as e:
        print(f"[警告] 读取时间戳记录失败: {e}，按首次运行处理。")
        return None
    if not raw:
        return None
    try:
        return datetime.strptime(raw.splitlines()[0].strip(), TIME_FMT)
    except ValueError:
        print(f"[警告] 时间戳记录格式非法: {raw!r}，按首次运行处理。")
        return None


def write_timestamp_state(end_dt, path=TIMESTAMP_STATE_FILE):
    atomic_write_text(path, end_dt.strftime(TIME_FMT) + "\n")
    print(f"已将截止时间 {end_dt.strftime(TIME_FMT)} 写入: {path}")


def plan_timestamp_window(now, session, news_date, stored):
    """
    计算本次时间段 (start, end, mode)。
      早间首次: [now, now+30min]
      晚间首次: [news_date 00:01:00, 00:31:00]
      续接:     [stored+1s, stored+30min]
    """
    now = now.replace(microsecond=0)
    if stored is None:
        belongs = False
    elif session == "evening":
        # 晚间：记录日期 == 归属日期 即为本晚的续接（该日的早间尚未发生）
        belongs = stored.date() == news_date
    else:
        # 早间：记录日期 == 今天 且 >= 05:00（排除昨晚留下的 00:xx/01:xx 记录）
        belongs = stored.date() == news_date and stored.hour >= MORNING_SESSION_START_HOUR

    if belongs:
        return stored + timedelta(seconds=1), stored + SLOT_LENGTH, "续接"
    if session == "evening":
        start = datetime.combine(news_date, EVENING_FIRST_START)
    else:
        start = now
    return start, start + SLOT_LENGTH, "首次"


def _timestamps_in(data, field=TIMESTAMP_FIELD):
    used = set()
    if not isinstance(data, dict):
        return used
    for lst in data.values():
        if isinstance(lst, list):
            for it in lst:
                if isinstance(it, dict) and isinstance(it.get(field), str):
                    used.add(it[field])
    return used


def collect_used_timestamps(paths, field=TIMESTAMP_FIELD):
    """收集若干 JSON 文件中已使用的时间戳，避免重复。"""
    used = set()
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                used |= _timestamps_in(json.load(f), field)
        except (OSError, ValueError):
            continue
    return used


def assign_timestamps(data, start, end, used=None, field=TIMESTAMP_FIELD):
    """为 data 中每个项目在 [start, end] 内随机分配不重复的时间戳，返回分配数量。"""
    items = [it for lst in data.values() if isinstance(lst, list)
             for it in lst if isinstance(it, dict)]
    if not items:
        return 0
    used = used or set()
    total = int((end - start).total_seconds()) + 1
    all_secs = [start + timedelta(seconds=i) for i in range(total)]
    candidates = [s for s in all_secs if s.strftime(TIME_FMT) not in used]
    n = len(items)

    if len(candidates) >= n:
        picks = _rng.sample(candidates, n)
    else:
        print(f"[警告] 项目数 {n} 超过可用秒数 {len(candidates)}，将出现重复时间戳。")
        pool = candidates or all_secs
        picks = pool[:]
        _rng.shuffle(picks)
        while len(picks) < n:
            picks.append(_rng.choice(pool))
        picks = picks[:n]
        _rng.shuffle(picks)

    for it, ts in zip(items, picks):
        it[field] = ts.strftime(TIME_FMT)
    return n


# ================= 原有逻辑 =================

def find_today_cnh_html(today, news_directory):
    """
    查找 backup/backup 与 news_directory 根目录下的 TodayCNH_<today>*.html。
    顺序：备份在前、最新在后（后读取的会覆盖先读取的同 URL 信息）。
    """
    backup_dir = os.path.join(news_directory, "backup", "backup")
    ordered = []
    ordered += sorted(glob.glob(os.path.join(backup_dir, f"TodayCNH_{today}_*.html")))
    ordered += [p for p in [os.path.join(backup_dir, f"TodayCNH_{today}.html")] if os.path.exists(p)]
    ordered += sorted(glob.glob(os.path.join(news_directory, f"TodayCNH_{today}_*.html")))
    ordered += [p for p in [os.path.join(news_directory, f"TodayCNH_{today}.html")] if os.path.exists(p)]

    seen, result = set(), []
    for p in ordered:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def extract_site_name(url):
    try:
        url = re.sub(r'^https?://(www\.)?', '', url.lower())

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

        domain = url.split('/')[0]
        parts = domain.split('.')
        if len(parts) >= 2:
            site_name = parts[-2].upper()
        else:
            site_name = parts[0].upper()
        return site_name

    except Exception as e:
        print(f"提取网站名称时出错 ({url}): {str(e)}")
        return "Other"


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


def backup_news_assets(local_dir, timestamp):
    """timestamp 为新闻归属日期 YYMMDD（晚间运行时为次日）。"""
    os.makedirs(local_dir, exist_ok=True)

    src_img_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    src_json = os.path.join(NEWS_DIRECTORY, "onews.json")

    local_img_target = os.path.join(local_dir, f"news_images_{timestamp}")
    local_json_target = os.path.join(local_dir, f"onews_{timestamp}.json")

    backup_dir = os.path.join(DOWNLOADS_DIR, "backup")
    backup_file_dir = os.path.join(NEWS_DIRECTORY, "done")

    # 1) 合并图片目录
    if os.path.exists(src_img_dir):
        os.makedirs(local_img_target, exist_ok=True)
        shutil.copytree(src_img_dir, local_img_target, dirs_exist_ok=True)
        print(f"已将图片合并到: {local_img_target}")
        shutil.rmtree(src_img_dir)
        print(f"已删除原始图片目录: {src_img_dir}")
    else:
        print(f"未找到源图片目录: {src_img_dir}")

    # 1.1) 图片备份到 Downloads/backup（目标目录存在才备份）
    if os.path.isdir(local_img_target):
        os.makedirs(backup_dir, exist_ok=True)
        backup_img_target = os.path.join(backup_dir, f"news_images_{timestamp}")
        if os.path.exists(backup_img_target):
            shutil.rmtree(backup_img_target)
        shutil.copytree(local_img_target, backup_img_target)
        print(f"图片目录已备份到: {backup_img_target}")
    else:
        print(f"不存在 {local_img_target}，跳过图片备份。")

    # 2) 合并 JSON 文件
    if os.path.exists(src_json):
        if os.path.exists(local_json_target):
            merge_json_groupwise(local_json_target, src_json)
            print(f"已将新内容合并到: {local_json_target}")
        else:
            tmp_json = os.path.join(local_dir, f".onews_{timestamp}_new.json")
            shutil.copy2(src_json, tmp_json)
            os.replace(tmp_json, local_json_target)
            print(f"已备份 JSON 到: {local_json_target}")
        os.remove(src_json)
        print(f"已删除原始JSON文件: {src_json}")
    else:
        print(f"未找到源 JSON 文件: {src_json}")

    # 2.1) 备份到 Coding/News/done
    if os.path.isfile(local_json_target):
        os.makedirs(backup_file_dir, exist_ok=True)
        backup_file_target = os.path.join(backup_file_dir, f"onews_{timestamp}.json")
        shutil.copy2(local_json_target, backup_file_target)
        print(f"JSON文件已备份到: {backup_file_target}")
    else:
        print(f"不存在 {local_json_target}，跳过 done 备份。")

    update_version_json(local_dir, timestamp)


def update_version_json(local_dir, timestamp):
    version_path = os.path.join(local_dir, "version.json")
    data = None
    if os.path.exists(version_path):
        try:
            with open(version_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            bad = version_path + f".corrupt_{datetime.now():%Y%m%d%H%M%S}"
            print(f"[警告] version.json 解析失败({e})，已另存为 {bad} 并重建。")
            os.replace(version_path, bad)
            data = None
    if not isinstance(data, dict):
        data = {"version": "1.0", "files": [], "update_time": ""}
    if not isinstance(data.get("files"), list):
        data["files"] = []

    # 1. 更新现有文件的 MD5
    for item in data["files"]:
        if item.get("type") == "json":
            file_path = os.path.join(local_dir, item.get("name", ""))
            if os.path.isfile(file_path):
                new_md5 = compute_md5(file_path)
                if item.get("md5") != new_md5:
                    item["md5"] = new_md5

    # 2. 准备添加新文件（仅登记真实存在的）
    to_add = []
    json_name = f"onews_{timestamp}.json"
    json_path = os.path.join(local_dir, json_name)
    if os.path.isfile(json_path):
        to_add.append({"name": json_name, "type": "json", "md5": compute_md5(json_path)})
    img_name = f"news_images_{timestamp}"
    if os.path.isdir(os.path.join(local_dir, img_name)):
        to_add.append({"name": img_name, "type": "images"})

    # 3. 检查重复并添加
    existing_names = {item.get("name") for item in data["files"]}
    for e in to_add:
        if e["name"] not in existing_names:
            data["files"].append(e)
            print(f"已添加到 version.json: {e['name']}")

    # 4. 更新 update_time
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    data["update_time"] = current_time_str
    print(f"已更新 version.json 的 update_time 为: {current_time_str}")

    atomic_write_json(version_path, data)
    print("version.json 已更新")


def prune_old_assets(local_dir, days_to_keep):
    version_path = os.path.join(local_dir, "version.json")
    if not os.path.exists(version_path):
        return
    print(f"\n开始清理超过 {days_to_keep} 天的旧资产...")
    try:
        with open(version_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"读取 version.json 失败，跳过清理: {e}")
        return
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
        atomic_write_json(version_path, data)


def merge_groupwise_data(data_old, data_new):
    """按分组合并两个 dict，按 (topic, url, article) 去重，旧项优先（保留旧时间戳）。"""
    merged = {}
    groups = list(data_old.keys()) + [g for g in data_new.keys() if g not in data_old]
    for group in groups:
        a = data_old.get(group, [])
        b = data_new.get(group, [])
        combined = (a if isinstance(a, list) else []) + (b if isinstance(b, list) else [])
        seen = set()
        deduped = []
        for item in combined:
            if not isinstance(item, dict):
                continue
            key = (item.get("topic", ""), item.get("url", ""), item.get("article", ""))
            if key not in seen:
                seen.add(key)
                if "hot" not in item:
                    item["hot"] = 0
                deduped.append(item)
        merged[group] = deduped
    return merged


def merge_json_groupwise(existing_path, new_path):
    with open(existing_path, 'r', encoding='utf-8') as f:
        data_old = json.load(f)
    with open(new_path, 'r', encoding='utf-8') as f:
        data_new = json.load(f)
    atomic_write_json(existing_path, merge_groupwise_data(data_old, data_new))


def find_all_news_files(directory):
    pattern = os.path.join(directory, "News_*.txt")
    return sorted(glob.glob(pattern))


def move_cnh_file(source_dir):
    try:
        cnh_pattern = os.path.join(source_dir, "TodayCNH_*.html")
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

    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"警告: article_copier 文件未找到: {file_path}")
        return {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('http'):
            current_url = line
            url_images.setdefault(current_url, [])
        elif any(line.lower().endswith(ext) for ext in valid_extensions) and current_url:
            url_images[current_url].append(line)

    print("解析到的URL和图片映射:")
    for url, images in url_images.items():
        print(f"URL: {url}")
        print(f"Images: {images}")

    return url_images


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


def move_article_copier_files(source_dir, backup_parent_dir):
    backup_dir = os.path.join(backup_parent_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)

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

        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(target_path):
            new_filename = f"{base}_copy_{counter}{ext}"
            target_path = os.path.join(backup_dir, new_filename)
            print(f"警告: 文件 {filename} 已存在于备份目录，尝试重命名为 {new_filename}")
            counter += 1

        try:
            shutil.move(source_path, target_path)
            print(f"成功移动: {filename} -> {os.path.basename(target_path)}")
            moved_count += 1
        except Exception as e:
            print(f"移动文件 {filename} 时出错: {str(e)}")

    print(f"--- 完成移动 article_copier 文件，共移动 {moved_count} 个文件 ---")


def normalize_url(u):
    """去掉 query 和 fragment，末尾去掉 '/'"""
    parts = urlsplit(u)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))


def split_zh_en(text):
    """将文章内容拆分为中文部分和英文部分。"""
    lines = text.strip().split('\n')
    split_index = -1

    for i, line in enumerate(lines):
        line_strip = line.strip()
        if not line_strip:
            continue

        has_zh = bool(re.search(r'[\u4e00-\u9fff]', line_strip))
        has_en = bool(re.search(r'[a-zA-Z]', line_strip))

        if not has_zh and has_en:
            prev_is_empty = (i == 0) or (not lines[i - 1].strip())
            if prev_is_empty:
                en_count = len(re.findall(r'[a-zA-Z]', line_strip))
                if en_count > 3:
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
                        if checked_lines >= 2:
                            break
                    if is_english_block:
                        split_index = i
                        break

    if split_index != -1:
        zh_part = '\n'.join(lines[:split_index]).strip()
        en_part = '\n'.join(lines[split_index:]).strip()
        return zh_part, en_part

    return text.strip(), ""


def generate_news_json(news_directory, today, cnh_html_paths=None,
                       ts_start=None, ts_end=None, extra_used_paths=None):
    """
    扫描 News_*.txt、TodayCNH_*.html、article_copier_{today}.txt，生成 onews.json。
    - 为本次新生成的每个项目在 [ts_start, ts_end] 内随机分配 timestamp。
    - 若上次运行遗留未归档的 onews.json，则与之合并而不是覆盖。
    - 没有 News_*.txt 时不生成、不覆盖。
    返回本次新生成的项目数。
    """
    out_path = os.path.join(news_directory, "onews.json")
    txt_files = sorted(glob.glob(os.path.join(news_directory, "News_*.txt")))
    if not txt_files:
        print("未找到任何 News_*.txt，跳过生成（不会覆盖已有的 onews.json）。")
        return 0

    # 1. 解析 TodayCNH_*.html
    cnh_map = {}
    if cnh_html_paths is None:
        html_files = glob.glob(os.path.join(news_directory, "TodayCNH_*.html"))
    else:
        html_files = cnh_html_paths

    for html_path in html_files:
        with open(html_path, 'r', encoding='utf-8') as f:
            text = f.read()

        for tr_match in re.finditer(r"<tr>(.*?)</tr>", text, re.S):
            tr_content = tr_match.group(1)
            basic_match = re.search(
                r"<td>\s*([^<]+)\s*</td>.*?<a\s+href=\"([^\"]+)\"[^>]*>([^<]+)</a>",
                tr_content, re.S
            )
            if basic_match:
                site = basic_match.group(1).strip()
                original_url = basic_match.group(2).strip()
                title_raw = basic_match.group(3).strip()

                topic_eng = ""
                eng_match = re.search(r"<td\s+class=\"title-eng\">\s*(.*?)\s*</td>", tr_content, re.S)
                if eng_match:
                    raw_eng = html.unescape(eng_match.group(1).strip())
                    topic_eng = re.sub(r'^[→\s]+', '', raw_eng).strip()
                    topic_eng = re.sub(r'\s+', ' ', topic_eng)

                nu = normalize_url(original_url)
                title_decoded = html.unescape(title_raw)
                title_decoded = re.sub(r'\s+', '', title_decoded)
                topic = re.sub(r'^[0-9０-９]+[、,，.]\s*', '', title_decoded)
                cnh_map[nu] = (site, topic, original_url, topic_eng)

    # 2. 解析 article_copier_{today}.txt
    copier_path = os.path.join(news_directory, f"article_copier_{today}.txt")
    url_images_raw = {}
    if os.path.exists(copier_path):
        url_images_raw = parse_article_copier(copier_path)
    url_images = {normalize_url(u): imgs for u, imgs in url_images_raw.items()}

    # 3. 组装 data
    data = {}
    for txt_path in txt_files:
        with open(txt_path, 'r', encoding='utf-8-sig') as f:
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
                    buf.append(raw)

        if current_url is not None:
            entries.append((current_url, "\n".join(buf).strip()))

        for url, article_text in entries:
            nu = normalize_url(url)
            topic_eng = ""

            if nu in cnh_map:
                site_code, topic, original_url_from_map, topic_eng = cnh_map[nu]
                imgs = url_images.get(nu, [])
                display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)
            else:
                site_code = extract_site_name(url)
                first_line = article_text.split('\n')[0].strip() if article_text else ""
                topic = first_line[:100] + "..." if len(first_line) > 100 else first_line
                if not topic:
                    topic = "未知主题"
                original_url_from_map = url
                imgs = url_images.get(nu, [])
                display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)
                print(f"注意：URL {url} 未在 HTML 中找到，使用推断信息: 站点={site_code}, 主题={topic[:50]}...")

            article_zh, article_eng = split_zh_en(article_text)
            source_id = REVERSE_SITE_MAPPING.get(display_site, "unknown")

            data.setdefault(display_site, []).append({
                "source_id": source_id,
                "topic":   topic,
                "topic_eng": topic_eng,
                "url":     original_url_from_map,
                "article": article_zh,
                "article_eng": article_eng,
                "images":  imgs,
                "hot": 0
            })

    new_count = sum(len(v) for v in data.values())

    # 4. 读取上次遗留的 onews.json（若有）
    pending = {}
    if os.path.isfile(out_path):
        try:
            with open(out_path, 'r', encoding='utf-8') as f:
                pending = json.load(f)
            if not isinstance(pending, dict):
                raise ValueError("顶层不是对象")
            print("[提示] 发现上次未归档的 onews.json，将与本次结果合并。")
        except (OSError, ValueError) as e:
            bad = out_path + f".corrupt_{datetime.now():%Y%m%d%H%M%S}"
            os.replace(out_path, bad)
            print(f"[警告] 遗留 onews.json 无法解析({e})，已另存为 {bad}")
            pending = {}

    # 5. 分配时间戳（排除已用时间，保证同一天内不重复）
    if ts_start is not None and ts_end is not None and new_count:
        used = _timestamps_in(pending) | collect_used_timestamps(extra_used_paths or [])
        assign_timestamps(data, ts_start, ts_end, used)
        print(f"已为 {new_count} 个项目分配时间戳，区间 "
              f"{ts_start.strftime(TIME_FMT)} ~ {ts_end.strftime(TIME_FMT)}")

    # 6. 写入
    merged = merge_groupwise_data(pending, data) if pending else data
    atomic_write_json(out_path, merged)
    print(f"\n已生成 JSON 文件: {out_path}")
    return new_count


# ================= 预运行检查 =================

def consolidate_dated_txt(directory, prefix, pattern, date_fmt, news_date):
    """
    将所有日期 < news_date 的同类 txt 按日期顺序合并进 news_date 的文件（旧内容在前），
    然后删除旧文件。取代原先“直接 rename 可能覆盖”的逻辑。
    """
    regex = re.compile(pattern)
    target_name = f"{prefix}{news_date.strftime(date_fmt)}.txt"
    target_path = os.path.join(directory, target_name)

    olds = []
    for fn in os.listdir(directory):
        m = regex.match(fn)
        if not m or fn == target_name:
            continue
        try:
            d = datetime.strptime(m.group(1), date_fmt).date()
        except ValueError:
            print(f"[警告] 文件名日期非法，已忽略: {fn}")
            continue
        if d < news_date:
            olds.append((d, fn))
    if not olds:
        return

    olds.sort()
    parts = []
    for _, fn in olds:
        with open(os.path.join(directory, fn), 'r', encoding='utf-8-sig') as f:
            c = f.read().strip('\n')
        if c.strip():
            parts.append(c)
    if os.path.isfile(target_path):
        with open(target_path, 'r', encoding='utf-8-sig') as f:
            c = f.read().strip('\n')
        if c.strip():
            parts.append(c)

    merged = "\n\n".join(parts)
    if merged:
        merged += "\n"
    atomic_write_text(target_path, merged)

    for _, fn in olds:
        os.remove(os.path.join(directory, fn))
    print(f"[合并] {', '.join(fn for _, fn in olds)} -> {target_name}")


def relocate_old_cnh_html(directory, news_date):
    """日期 < news_date 的 TodayCNH_YYMMDD.html 改名到当天；若已存在则用 _N 后缀，绝不覆盖。"""
    regex = re.compile(r'^TodayCNH_(\d{6})\.html$')
    today = news_date.strftime("%y%m%d")
    for fn in sorted(os.listdir(directory)):
        m = regex.match(fn)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%y%m%d").date()
        except ValueError:
            print(f"[警告] 文件名日期非法，已忽略: {fn}")
            continue
        if d >= news_date:
            continue
        target = os.path.join(directory, f"TodayCNH_{today}.html")
        counter = 1
        while os.path.exists(target):
            target = os.path.join(directory, f"TodayCNH_{today}_{counter}.html")
            counter += 1
        os.rename(os.path.join(directory, fn), target)
        print(f"[重命名] {fn} -> {os.path.basename(target)}")


def pre_run_checks(news_directory, now, session, news_date):
    label = "早间" if session == "morning" else "晚间"
    print(f"\n[提示] 当前时间 {now.strftime(TIME_FMT)}，判定为【{label}】时段，"
          f"新闻归属日期 {news_date.isoformat()}。")
    if not in_expected_window(now):
        print("[警告] 当前不在常规运行窗口（07:00-12:30 / 22:30-次日01:30），仍将继续执行。")

    print(f"[提示] 正在检查 {news_directory} 目录下的文件...")
    consolidate_dated_txt(news_directory, "article_copier_",
                          r'^article_copier_(\d{6})\.txt$', "%y%m%d", news_date)
    consolidate_dated_txt(news_directory, "News_",
                          r'^News_(\d{2}_\d{2}_\d{2})\.txt$', "%y_%m_%d", news_date)
    relocate_old_cnh_html(news_directory, news_date)
    print("[提示] 文件日期检查完毕。\n")


# ================= 主流程 =================

if __name__ == "__main__":
    run_now = datetime.now()
    session, news_date = resolve_session(run_now)

    pre_run_checks(NEWS_DIRECTORY, run_now, session, news_date)

    today = news_date.strftime("%y%m%d")   # 新闻归属日期（晚间为次日）
    news_directory = NEWS_DIRECTORY
    downloads_path = DOWNLOADS_DIR
    local_server_dir = LOCAL_SERVER_DIR

    # 计算本次时间戳区间
    stored = read_timestamp_state()
    ts_start, ts_end, mode = plan_timestamp_window(run_now, session, news_date, stored)
    print(f"[时间戳] 上次记录: {stored.strftime(TIME_FMT) if stored else '无'}；"
          f"本次为{mode}，区间 {ts_start.strftime(TIME_FMT)} ~ {ts_end.strftime(TIME_FMT)}")

    # 0. 查找当天的 TodayCNH_<today>.html
    cnh_html_paths = find_today_cnh_html(today, news_directory)
    if not cnh_html_paths:
        alert_and_exit(
            f"未找到当天的 TodayCNH_{today}.html。\n"
            f"请检查以下路径：\n"
            f"1) {os.path.join(news_directory, 'backup', 'backup')}\n"
            f"2) {news_directory}\n"
            f"找到后再重试。"
        )

    # 1. 生成 JSON 汇总 + 分配时间戳
    print("\n" + "=" * 10 + " 1. 开始生成 JSON 汇总 " + "=" * 10)
    new_count = generate_news_json(
        news_directory, today, cnh_html_paths=cnh_html_paths,
        ts_start=ts_start, ts_end=ts_end,
        extra_used_paths=[os.path.join(local_server_dir, f"onews_{today}.json")],
    )
    if new_count > 0:
        write_timestamp_state(ts_end)
    else:
        print("本次没有新项目，时间戳记录保持不变。")
    print("=" * 10 + " 完成生成 JSON 汇总 " + "=" * 10)

    # 2. 移动 TodayCNH 文件
    print("\n" + "=" * 10 + " 2. 开始移动 TodayCNH 文件 " + "=" * 10)
    move_cnh_file(news_directory)
    print("=" * 10 + " 完成移动 TodayCNH 文件 " + "=" * 10)

    # 3. 清理 Downloads 目录下的 .html 文件
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

    # 4. 移动 article_copier 文件到 backup
    print("\n" + "=" * 10 + " 4. 开始移动 article_copier 文件 " + "=" * 10)
    move_article_copier_files(news_directory, news_directory)
    print("=" * 10 + " 完成移动 article_copier 文件 " + "=" * 10)

    # 5. 清理已处理的 TXT 文件
    print("\n" + "=" * 10 + " 5. 开始清理已处理的 TXT 文件 " + "=" * 10)
    trash_processed_txt_files(news_directory)
    print("=" * 10 + " 完成清理已处理的 TXT 文件 " + "=" * 10)

    # 6. 备份 news_images 与 onews.json 并更新 version.json
    print("\n" + "=" * 10 + " 6. 开始备份核心资产 " + "=" * 10)
    backup_news_assets(local_server_dir, today)
    print("=" * 10 + " 完成备份核心资产 " + "=" * 10)

    # 7. 清理超过10天的旧文件和目录
    print("\n" + "=" * 10 + " 7. 开始清理旧资产 " + "=" * 10)
    prune_old_assets(local_server_dir, days_to_keep=10)
    print("=" * 10 + " 完成清理旧资产 " + "=" * 10)

    # 8. 最终再同步一次 version.json（重新计算全部 MD5）
    update_version_json(local_server_dir, today)