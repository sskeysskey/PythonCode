import os
import json
import glob
import sys
import re
import tkinter as tk
from tkinter import messagebox
from send2trash import send2trash

DOWNLOADS_DIR = '/Users/yanzhang/Downloads/'
MAPPING_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
BLACKLIST_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'
OVIDEOS_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'

# 【新增】记录"上一次写入"的状态文件，供 --blacklist-last 回滚使用
STATE_FILE = '/tmp/downie_last_write.json'

# 定义需要加入黑名单的关键字列表
BLACKLIST_KEYWORDS = ['TC', 'TS', '抢先', 'HC']

# 定义需要从文件名中过滤掉的字符串列表（严格包含空格，后续有新增直接在这里添加即可）
FILTER_STRINGS = ['- 正在播放 ', ' - 片库 - 片库网']


def show_warning(msg):
    """弹窗警告"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    messagebox.showwarning("警告", msg)
    root.destroy()


# ==========================================================
# 【新增】状态文件读写
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


# ==========================================================
# 公共工具
# ==========================================================
def fix_trailing_comma(lines):
    """删除某行后，修复 JSON 末尾多余的逗号"""
    for j in range(len(lines) - 1, -1, -1):
        if '}' in lines[j]:
            for k in range(j - 1, -1, -1):
                if lines[k].strip():
                    stripped_k = lines[k].rstrip('\n\r ')
                    if stripped_k.endswith(','):
                        lines[k] = stripped_k[:-1] + '\n'
                    break
            break
    return lines


def add_to_blacklist(mapping_url, name, real_url):
    """写入 blacklist_url.json"""
    blacklist_data = {}
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                blacklist_data = json.load(f)
        except json.JSONDecodeError:
            pass

    # 修复：url 放前面，name 放后面，与 url_mapping.json 的写入顺序保持一致
    blacklist_data[mapping_url] = [real_url, name]

    with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(blacklist_data, f, ensure_ascii=False, indent=4)
    print("✅ blacklist_url.json 写入成功！")


def check_info_has_blacklist_keyword(target_url, keywords):
    """
    修复版：在 OVideos.json 中查找 target_url 是否存在于 playlist 的 episodes 中
    """
    if not os.path.exists(OVIDEOS_FILE):
        print(f"⚠️  OVideos.json 文件不存在，跳过二次判断")
        return False, False

    try:
        with open(OVIDEOS_FILE, 'r', encoding='utf-8') as f:
            ovideos_data = json.load(f)
    except json.JSONDecodeError:
        return False, False

    # 遍历所有分类（Movie, Drama, 及未来可能新增的其他分类）
    for category, items in ovideos_data.items():
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            # --- 修复核心逻辑：检查 playlist ---
            playlist = item.get('playlist', [])
            found_in_episodes = False

            for source in playlist:
                episodes = source.get('episodes', {})
                # 修复：episodes 可能是字典（key=url形式）或列表（直接url形式）
                if isinstance(episodes, dict):
                    if target_url in episodes.values():
                        found_in_episodes = True
                        break
                elif isinstance(episodes, list):
                    if target_url in episodes:
                        found_in_episodes = True
                        break

            if found_in_episodes:
                info_value = item.get('info', '') or ''
                info_has_keyword = any(kw in info_value for kw in keywords)

                print(f"🔍 在 OVideos.json 中匹配到播放链接：{target_url}")
                print(f"   所属项目: {item.get('name')}")
                print(f"   该项目 info = \"{info_value}\"，是否含黑名单关键字：{info_has_keyword}")

                return True, info_has_keyword

    print(f"🔍 OVideos.json 中未匹配到 URL：{target_url}")
    return False, False


def write_normal_mapping(lines, empty_line_idx, url, json_name_no_ext):
    """正常写入 url_mapping.json 的公共逻辑（抽取出来便于两处调用）"""
    line = lines[empty_line_idx]
    idx = line.rfind('""')

    new_value = json.dumps([url, json_name_no_ext], ensure_ascii=False)
    new_line = line[:idx] + new_value + line[idx + 2:]
    lines[empty_line_idx] = new_line

    print(f"已在第 {empty_line_idx + 1} 行写入 URL 和 文件名")
    print(f"原内容: {line.rstrip()}")
    print(f"新内容: {new_line.rstrip()}")

    with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("✅ url_mapping.json 写入成功！")


# ==========================================================
# 【新增】回滚模式：把上一次写进 url_mapping 的记录改判为 blacklist
# 由 AppleScript 在 close 点击次数超阈值时调用：
#     python3 write.py --blacklist-last
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

    # 无论结果如何，这条状态只消费一次
    clear_state()

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

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    key_token = '"%s"' % mapping_url
    target_idx = -1
    for i, line in enumerate(lines):
        if line.lstrip().startswith(key_token):
            target_idx = i
            break
    if target_idx == -1:
        # 兜底：全行包含匹配
        for i, line in enumerate(lines):
            if key_token in line and ':' in line:
                target_idx = i
                break

    if target_idx == -1:
        print(f"⚠️  在 url_mapping.json 中未找到 key：{mapping_url}，跳过回滚。")
        return 0

    print(f"⚠️  关闭下载耗时异常，判定链接有问题，回滚第 {target_idx + 1} 行：")
    print(f"    {lines[target_idx].rstrip()}")

    del lines[target_idx]
    fix_trailing_comma(lines)

    with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"✅ 已从 url_mapping.json 删除整行，提取的 URL: {mapping_url}")

    add_to_blacklist(mapping_url, name, real_url)
    print("✅ 回滚完成，该链接已转入 blacklist_url.json")
    return 0


def main():
    # 【新增】每次正常运行先清掉上一条状态，避免误回滚历史记录
    clear_state()

    # 1. 查找 Downloads 目录下的 json 文件
    all_json_files = glob.glob(os.path.join(DOWNLOADS_DIR, '*.json'))

    # 过滤掉 kalshi_ 开头的文件
    json_files = [f for f in all_json_files if not os.path.basename(f).startswith('kalshi_')]

    if len(json_files) == 0:
        show_warning("Downloads 目录下没有找到有效的 json 文件（已排除 kalshi_ 相关文件）！")
        sys.exit(1)

    if len(json_files) > 1:
        files_list = "\n".join(os.path.basename(f) for f in json_files)
        show_warning(f"Downloads 目录下发现 {len(json_files)} 个有效 json 文件，程序终止：\n\n{files_list}")
        sys.exit(1)

    json_file = json_files[0]
    json_filename = os.path.basename(json_file)
    json_name_no_ext = os.path.splitext(json_filename)[0]  # 获取不带后缀的文件名

    # 过滤文件名中的特定字符串
    for f_str in FILTER_STRINGS:
        json_name_no_ext = json_name_no_ext.replace(f_str, "")

    print(f"找到 json 文件: {json_file}")
    print(f"过滤后的文件名: {json_name_no_ext}")

    # 2. 读取 json 并提取 url
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        show_warning(f"json 文件解析失败：{e}")
        sys.exit(1)

    url = data.get('url')
    if not url:
        show_warning(f"json 文件中没有找到 url 字段：{json_file}")
        sys.exit(1)

    print(f"提取到的 URL: {url}")

    # 3. 读取 url_mapping.json
    if not os.path.exists(MAPPING_FILE):
        show_warning(f"映射文件不存在：{MAPPING_FILE}")
        sys.exit(1)

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 4. 查找 value 为空的行
    empty_line_idx = -1
    extracted_mapping_url = ""

    for i, line in enumerate(lines):
        stripped = line.rstrip('\n').rstrip().rstrip(',').rstrip()
        if stripped.endswith('""'):
            empty_line_idx = i
            match = re.search(r'"([^"]+)"\s*:\s*""', line)
            if match:
                extracted_mapping_url = match.group(1)
            break

    if empty_line_idx == -1:
        show_warning("url_mapping.json 中没有找到值为空的行！")
        sys.exit(1)

    # --- 判断是否需要加入黑名单 ---
    is_blacklist_item = any(keyword in json_filename for keyword in BLACKLIST_KEYWORDS)

    # url_contains_blacklist_char = "//p.bvvvvv" in url or "%" in url
    url_contains_blacklist_char = "%" in url

    should_blacklist = False  # 统一控制是否走黑名单逻辑的开关

    if url_contains_blacklist_char:
        print("⚠️ 检测到 URL 包含黑名单特征 (%)，将直接加入黑名单...")
        should_blacklist = True
    elif is_blacklist_item:
        matched_keywords = [k for k in BLACKLIST_KEYWORDS if k in json_filename]
        print(f"检测到文件名包含黑名单关键字 ({matched_keywords})，准备执行二次判断...")

        is_matched, info_has_keyword = check_info_has_blacklist_keyword(
            extracted_mapping_url, BLACKLIST_KEYWORDS
        )

        if is_matched and info_has_keyword:
            print("✅ OVideos.json 中该项目 info 字段也含黑名单关键字，跳过 blacklist，走正常写入逻辑")
            should_blacklist = False
        else:
            print("⚠️ 未满足跳过条件，按原黑名单逻辑处理...")
            should_blacklist = True

    # --- 根据 should_blacklist 决定最终执行的逻辑 ---
    if should_blacklist:
        if not extracted_mapping_url:
            show_warning("无法从 url_mapping.json 的空行中提取出 URL 键！")
            sys.exit(1)

        # 从 lines 中删除该空行
        del lines[empty_line_idx]

        # 修复 JSON 格式：处理末尾多余逗号
        fix_trailing_comma(lines)

        # 写回 url_mapping.json
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"✅ 已从 url_mapping.json 删除整行，提取的 URL: {extracted_mapping_url}")

        # 写入 blacklist_url.json
        add_to_blacklist(extracted_mapping_url, json_name_no_ext, url)

        # 【新增】记录状态：已进黑名单，后续无需回滚
        save_state({
            "action": "blacklist",
            "mapping_url": extracted_mapping_url,
            "name": json_name_no_ext,
            "url": url
        })

    else:
        # 不包含黑名单关键字，且 URL 正常，走原有正常写入逻辑
        write_normal_mapping(lines, empty_line_idx, url, json_name_no_ext)

        # 【新增】记录状态：写进了 mapping，可能被 --blacklist-last 回滚
        save_state({
            "action": "normal",
            "mapping_url": extracted_mapping_url,
            "name": json_name_no_ext,
            "url": url
        })

    # 6. 删除 Downloads 目录下的源 json 文件
    try:
        send2trash(json_file)
        print(f"🗑️  已删除源文件: {json_file}")
    except OSError as e:
        show_warning(f"源 json 文件删除失败：{e}")
        sys.exit(1)

    print("✅ 全部任务完成！")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('--blacklist-last', '--revert-last'):
        sys.exit(blacklist_last())
    main()