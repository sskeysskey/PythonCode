import os
import sys
import re
import json
import glob
import stat
import argparse
import tempfile
import tkinter as tk
from tkinter import messagebox
from send2trash import send2trash

DOWNLOADS_DIR = '/Users/yanzhang/Downloads/'
MAPPING_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
BLACKLIST_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'
OVIDEOS_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'

# 记录"上一次写入"的状态文件，供 --blacklist-last 回滚使用
STATE_FILE = '/tmp/downie_last_write.json'

# 【新增】read.py 写入的"本轮正在处理的 mapping key"，用于精确定位要写入的条目
CURRENT_URL_FILE = '/tmp/downie_current_url.txt'

# 需要加入黑名单的关键字列表
BLACKLIST_KEYWORDS = ['TC', 'TS', '抢先', 'HC']

# 需要从文件名中过滤掉的字符串列表（严格包含空格）
FILTER_STRINGS = ['- 正在播放 ', ' - 片库 - 片库网']

# 【新增】直写模式（Chrome 提取 pys）额外过滤的标题片段，按需追加
DIRECT_TITLE_FILTER_STRINGS = []

# 【新增】直写模式下替换文件名非法字符，与 Downie 生成的文件名风格保持一致
DIRECT_NAME_CHAR_MAP = {'/': '-', ':': '-'}

DIRECT_URL_RE = re.compile(r'^https?://\S+$', re.IGNORECASE)


# ==========================================================
# 提示 / 退出
# ==========================================================
def show_warning(msg):
    """弹窗警告（同时输出到 stderr，便于 AppleScript 日志记录）"""
    print(f"⚠️  {msg}", file=sys.stderr)
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showwarning("警告", msg)
        root.destroy()
    except Exception:
        pass


def die(msg, code=1):
    show_warning(msg)
    sys.exit(code)


# ==========================================================
# JSON 读写（原子写入 + 保留权限）
# ==========================================================
def load_json_strict(path, desc):
    if not os.path.exists(path):
        die(f"{desc}不存在：{path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        die(f"{desc}不是有效 JSON（{e}），为防止覆盖损坏数据已终止：{path}")


def atomic_write_json(path, data):
    dir_name = os.path.dirname(path) or '.'
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ==========================================================
# 状态文件
# ==========================================================
def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"📝 已记录本次写入状态: {state.get('action')}")
    except OSError as e:
        print(f"⚠️  状态文件写入失败（不影响主流程）：{e}")


def clear_state():
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    except OSError:
        pass


def read_current_url():
    try:
        with open(CURRENT_URL_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def clear_current_url():
    try:
        if os.path.exists(CURRENT_URL_FILE):
            os.remove(CURRENT_URL_FILE)
    except OSError:
        pass


# ==========================================================
# 业务工具
# ==========================================================
def add_to_blacklist(mapping_url, name, real_url):
    """写入 blacklist_url.json（文件损坏时终止，绝不覆盖）"""
    if os.path.exists(BLACKLIST_FILE):
        blacklist_data = load_json_strict(BLACKLIST_FILE, "黑名单文件")
        if not isinstance(blacklist_data, dict):
            die(f"黑名单文件结构异常（非对象），已终止：{BLACKLIST_FILE}")
    else:
        blacklist_data = {}

    # url 放前面，name 放后面，与 url_mapping.json 保持一致
    blacklist_data[mapping_url] = [real_url, name]
    atomic_write_json(BLACKLIST_FILE, blacklist_data)
    print("✅ blacklist_url.json 写入成功！")


def _iter_ovideos_items():
    if not os.path.exists(OVIDEOS_FILE):
        return
    try:
        with open(OVIDEOS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                yield category, item


def check_info_has_blacklist_keyword(target_url, keywords):
    """在 OVideos.json 中查找 target_url 是否存在于 playlist 的 episodes 中"""
    if not os.path.exists(OVIDEOS_FILE):
        print("⚠️  OVideos.json 文件不存在，跳过二次判断")
        return False, False

    for _category, item in _iter_ovideos_items():
        found = False
        for source in item.get('playlist', []) or []:
            episodes = source.get('episodes', {}) or {}
            if isinstance(episodes, dict) and target_url in episodes.values():
                found = True
                break
            if isinstance(episodes, list) and target_url in episodes:
                found = True
                break

        if found:
            info_value = item.get('info', '') or ''
            info_has_keyword = any(kw in info_value for kw in keywords)
            print(f"🔍 在 OVideos.json 中匹配到播放链接：{target_url}")
            print(f"   所属项目: {item.get('name')}")
            print(f"   该项目 info = \"{info_value}\"，是否含黑名单关键字：{info_has_keyword}")
            return True, info_has_keyword

    print(f"🔍 OVideos.json 中未匹配到 URL：{target_url}")
    return False, False


def lookup_episode_label(target_url):
    """根据播放页 URL 在 OVideos.json 中查出「项目名 集名」，用作标题兜底"""
    for _category, item in _iter_ovideos_items():
        item_name = item.get('name') or item.get('title') or ''
        for source in item.get('playlist', []) or []:
            episodes = source.get('episodes', {}) or {}
            if isinstance(episodes, dict):
                for ep_name, ep_url in episodes.items():
                    if ep_url == target_url:
                        return f"{item_name} {ep_name}".strip()
    return ''


def clean_name(name, direct=False):
    name = str(name or '')
    for f_str in FILTER_STRINGS:
        name = name.replace(f_str, "")
    if direct:
        for f_str in DIRECT_TITLE_FILTER_STRINGS:
            name = name.replace(f_str, "")
        for src, dst in DIRECT_NAME_CHAR_MAP.items():
            name = name.replace(src, dst)
        name = re.sub(r'\s+', ' ', name)
    return name.strip()


def resolve_target_key(mapping, explicit_key=''):
    """
    确定本次要写入的 mapping key：
      1) 显式传入的 --key（严格：必须存在且值为空）
      2) read.py 记录的当前 URL（值为空才采用）
      3) 兜底：第一个值为空的条目（旧行为）
    """
    if explicit_key:
        if explicit_key not in mapping:
            die(f"url_mapping.json 中不存在指定的 key：{explicit_key}")
        if mapping[explicit_key] != "":
            die(f"指定的 key 已有映射值，拒绝覆盖：{explicit_key}")
        return explicit_key

    cur = read_current_url()
    if cur:
        if mapping.get(cur) == "":
            return cur
        print(f"⚠️  read.py 记录的当前 URL 不是待填写状态，回退为第一个空值条目：{cur}")

    for k, v in mapping.items():
        if v == "":
            return k
    return None


def decide_blacklist(url, raw_name, mapping_key):
    """沿用原有黑名单判定规则"""
    if "%" in url:
        print("⚠️ 检测到 URL 包含黑名单特征 (%)，将直接加入黑名单...")
        return True

    matched_keywords = [k for k in BLACKLIST_KEYWORDS if k in raw_name]
    if matched_keywords:
        print(f"检测到文件名包含黑名单关键字 ({matched_keywords})，准备执行二次判断...")
        is_matched, info_has_keyword = check_info_has_blacklist_keyword(mapping_key, BLACKLIST_KEYWORDS)
        if is_matched and info_has_keyword:
            print("✅ OVideos.json 中该项目 info 字段也含黑名单关键字，跳过 blacklist，走正常写入逻辑")
            return False
        print("⚠️ 未满足跳过条件，按原黑名单逻辑处理...")
        return True

    return False


def commit(mapping, key, url, name, raw_name):
    """写入 mapping 或 blacklist，并记录状态"""
    if decide_blacklist(url, raw_name, key):
        # 先写黑名单再删 mapping，任何一步中断都不会丢数据
        add_to_blacklist(key, name, url)
        mapping.pop(key, None)
        atomic_write_json(MAPPING_FILE, mapping)
        print(f"✅ 已从 url_mapping.json 删除条目：{key}")
        save_state({"action": "blacklist", "mapping_url": key, "name": name, "url": url})
    else:
        mapping[key] = [url, name]
        atomic_write_json(MAPPING_FILE, mapping)
        print(f"✅ url_mapping.json 写入成功！\n   key  : {key}\n   value: {json.dumps([url, name], ensure_ascii=False)}")
        save_state({"action": "normal", "mapping_url": key, "name": name, "url": url})

    clear_current_url()


# ==========================================================
# 模式 1：原流程（读取 Downloads 中 Downie 导出的 json）
# ==========================================================
def main_from_downloads():
    clear_state()

    all_json_files = glob.glob(os.path.join(DOWNLOADS_DIR, '*.json'))
    json_files = [f for f in all_json_files if not os.path.basename(f).startswith('kalshi_')]

    if len(json_files) == 0:
        die("Downloads 目录下没有找到有效的 json 文件（已排除 kalshi_ 相关文件）！")
    if len(json_files) > 1:
        files_list = "\n".join(os.path.basename(f) for f in json_files)
        die(f"Downloads 目录下发现 {len(json_files)} 个有效 json 文件，程序终止：\n\n{files_list}")

    json_file = json_files[0]
    json_filename = os.path.basename(json_file)
    name = clean_name(os.path.splitext(json_filename)[0])

    print(f"找到 json 文件: {json_file}")
    print(f"过滤后的文件名: {name}")

    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        die(f"json 文件解析失败：{e}")

    url = (data.get('url') or '').strip() if isinstance(data, dict) else ''
    if not url:
        die(f"json 文件中没有找到 url 字段：{json_file}")
    print(f"提取到的 URL: {url}")

    mapping = load_json_strict(MAPPING_FILE, "映射文件")
    key = resolve_target_key(mapping)
    if not key:
        die("url_mapping.json 中没有找到值为空的条目！")
    print(f"目标 mapping key: {key}")

    commit(mapping, key, url, name, raw_name=json_filename)

    try:
        send2trash(json_file)
        print(f"🗑️  已删除源文件: {json_file}")
    except OSError as e:
        die(f"源 json 文件删除失败：{e}")

    print("✅ 全部任务完成！")
    return 0


# ==========================================================
# 模式 2：直写（pys 新流程：Chrome 提取到的地址）
#   python3 write.py --direct-url <m4u> --name <页面标题> --key <播放页URL>
# ==========================================================
def main_direct(direct_url, raw_title, key):
    clear_state()

    url = (direct_url or '').strip()
    if not DIRECT_URL_RE.match(url):
        die(f"--direct-url 不是合法的 http(s) 地址：{url}")

    mapping = load_json_strict(MAPPING_FILE, "映射文件")
    target_key = resolve_target_key(mapping, explicit_key=(key or '').strip())
    if not target_key:
        die("url_mapping.json 中没有找到值为空的条目！")

    name = clean_name(raw_title, direct=True)
    if not name:
        name = lookup_episode_label(target_key) or target_key
        print(f"ℹ️  页面标题为空，使用兜底名称：{name}")

    print(f"[直写模式] 目标 key: {target_key}")
    print(f"[直写模式] 媒体地址: {url}")
    print(f"[直写模式] 名称    : {name}")

    commit(mapping, target_key, url, name, raw_name=raw_title or name)
    print("✅ 全部任务完成！")
    return 0


# ==========================================================
# 模式 3：按 key 拉黑（pys 提取失败时使用）
#   python3 write.py --blacklist-key <播放页URL> [--name 标题] [--reason 原因]
# ==========================================================
def blacklist_key_mode(key, raw_title, reason):
    key = (key or '').strip()
    mapping = load_json_strict(MAPPING_FILE, "映射文件")

    if key not in mapping:
        print(f"ℹ️  url_mapping.json 中不存在该 key，无需拉黑：{key}")
        return 0
    if mapping[key] != "":
        print(f"ℹ️  该 key 已有映射值，不予拉黑（防误删）：{key}")
        return 0

    name = clean_name(raw_title, direct=True) or lookup_episode_label(key) or ''
    print(f"⚠️  拉黑原因：{reason or '未说明'}")
    add_to_blacklist(key, name, "")
    del mapping[key]
    atomic_write_json(MAPPING_FILE, mapping)
    print(f"✅ 已从 url_mapping.json 删除并转入 blacklist：{key}")

    clear_state()
    clear_current_url()
    return 0


# ==========================================================
# 模式 4：回滚上一次 normal 写入为 blacklist
# ==========================================================
def blacklist_last():
    if not os.path.exists(STATE_FILE):
        print("ℹ️  未找到上一次写入的状态文件，无需处理。")
        return 0

    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  状态文件读取失败：{e}")
        clear_state()
        return 0

    clear_state()  # 只消费一次

    action = state.get('action')
    if action != 'normal':
        print(f"ℹ️  上一条记录 action = {action}，本来就没写进 url_mapping，无需回滚。")
        return 0

    mapping_url = state.get('mapping_url') or ''
    name = state.get('name') or ''
    real_url = state.get('url') or ''

    if not mapping_url:
        print("⚠️  状态文件中没有 mapping_url，无法回滚。")
        return 0
    if not os.path.exists(MAPPING_FILE):
        print(f"⚠️  映射文件不存在：{MAPPING_FILE}")
        return 0

    mapping = load_json_strict(MAPPING_FILE, "映射文件")
    if mapping_url not in mapping:
        print(f"⚠️  在 url_mapping.json 中未找到 key：{mapping_url}，跳过回滚。")
        return 0

    print(f"⚠️  关闭下载耗时异常，判定链接有问题，回滚：{mapping_url} -> {mapping[mapping_url]}")
    add_to_blacklist(mapping_url, name, real_url)
    del mapping[mapping_url]
    atomic_write_json(MAPPING_FILE, mapping)
    print("✅ 回滚完成，该链接已从 url_mapping.json 删除并转入 blacklist_url.json")
    return 0


def parse_args():
    p = argparse.ArgumentParser(description='写入 url_mapping / blacklist')
    p.add_argument('--blacklist-last', '--revert-last', dest='blacklist_last', action='store_true',
                   help='把上一次 normal 写入回滚为 blacklist')
    p.add_argument('--direct-url', default='', help='直写模式：直接给出媒体地址（不读 Downloads）')
    p.add_argument('--name', default='', help='直写/拉黑模式：页面标题')
    p.add_argument('--key', default='', help='直写模式：目标 mapping key（播放页 URL）')
    p.add_argument('--blacklist-key', default='', help='按 key 拉黑（值必须为空）')
    p.add_argument('--reason', default='', help='拉黑原因（仅日志）')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.blacklist_last:
        sys.exit(blacklist_last())
    if args.blacklist_key:
        sys.exit(blacklist_key_mode(args.blacklist_key, args.name, args.reason))
    if args.direct_url:
        sys.exit(main_direct(args.direct_url, args.name, args.key))
    sys.exit(main_from_downloads())