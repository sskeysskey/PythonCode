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


def check_info_has_blacklist_keyword(target_url, keywords):
    """
    修改版：在 OVideos.json 中查找 target_url 是否存在于 playlist 的 episodes 中
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
        if not isinstance(items, list): continue
        
        for item in items:
            if not isinstance(item, dict): continue
            
            # --- 核心修改：检查 playlist ---
            playlist = item.get('playlist', [])
            found_in_episodes = False
            
            for source in playlist:
                episodes = source.get('episodes', [])
                if target_url in episodes:
                    found_in_episodes = True
                    break
            
            if found_in_episodes:
                # 找到了链接，现在检查 info
                info_value = item.get('info', '') or ''
                # info 字段中是否包含任一黑名单关键字
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


def main():
    # 1. 查找 Downloads 目录下的 json 文件
    json_files = glob.glob(os.path.join(DOWNLOADS_DIR, '*.json'))

    if len(json_files) == 0:
        show_warning("Downloads 目录下没有找到 json 文件！")
        sys.exit(1)

    if len(json_files) > 1:
        files_list = "\n".join(os.path.basename(f) for f in json_files)
        show_warning(f"Downloads 目录下发现 {len(json_files)} 个 json 文件，程序终止：\n\n{files_list}")
        sys.exit(1)

    json_file = json_files[0]
    json_filename = os.path.basename(json_file)
    json_name_no_ext = os.path.splitext(json_filename)[0]  # 获取不带后缀的文件名
    
    # --- 新增：过滤文件名中的特定字符串 ---
    for f_str in FILTER_STRINGS:
        json_name_no_ext = json_name_no_ext.replace(f_str, "")

    print(f"找到 json 文件: {json_file}")
    print(f"过滤后的文件名: {json_name_no_ext}")

    # 2. 读取 json 并提取 url（json.load 会自动处理 \/ 转义）
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
        # 去除尾部换行/逗号/空格后判断是否以 "" 结尾（即值为空）
        stripped = line.rstrip('\n').rstrip().rstrip(',').rstrip()
        if stripped.endswith('""'):
            empty_line_idx = i
            # 利用正则提取冒号左边的 URL
            match = re.search(r'"([^"]+)"\s*:\s*""', line)
            if match:
                extracted_mapping_url = match.group(1)
            break

    if empty_line_idx == -1:
        show_warning("url_mapping.json 中没有找到值为空的行！")
        sys.exit(1)

    # --- 修改部分：判断是否需要加入黑名单 ---
    is_blacklist_item = any(keyword in json_filename for keyword in BLACKLIST_KEYWORDS)
    
    # 新增逻辑：如果 URL 包含 "//p.bvvvvv" 或者包含 "%"，则标记为需要黑名单
    # url_contains_blacklist_char = "//p.bvvvvv" in url or "%" in url
    url_contains_blacklist_char = "%" in url

    should_blacklist = False  # 统一控制是否走黑名单逻辑的开关

    if url_contains_blacklist_char:
        print("⚠️ 检测到 URL 包含黑名单特征 (%)，将直接加入黑名单...")
        should_blacklist = True
    elif is_blacklist_item:
        matched_keywords = [k for k in BLACKLIST_KEYWORDS if k in json_filename]
        print(f"检测到文件名包含黑名单关键字 ({matched_keywords})，准备执行二次判断...")

        # --- 二次判断 ---
        # 用 url_mapping 冒号左边的 URL 去 OVideos.json 里匹配
        is_matched, info_has_keyword = check_info_has_blacklist_keyword(
            extracted_mapping_url, BLACKLIST_KEYWORDS
        )

        if is_matched and info_has_keyword:
            # 命中 OVideos.json 且 info 字段也含黑名单关键字 → 说明片源本身就是 TC/TS 等版本
            # 不写入 blacklist，走正常写入逻辑
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
        for j in range(len(lines) - 1, -1, -1):
            if '}' in lines[j]:
                for k in range(j - 1, -1, -1):
                    if lines[k].strip():
                        stripped_k = lines[k].rstrip('\n\r ')
                        if stripped_k.endswith(','):
                            lines[k] = stripped_k[:-1] + '\n'
                        break
                break

        # 写回 url_mapping.json
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"✅ 已从 url_mapping.json 删除整行，提取的 URL: {extracted_mapping_url}")

        # 写入 blacklist_url.json
        blacklist_data = {}
        if os.path.exists(BLACKLIST_FILE):
            try:
                with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                    blacklist_data = json.load(f)
            except json.JSONDecodeError:
                pass

        blacklist_data[extracted_mapping_url] = [json_name_no_ext, url]

        with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(blacklist_data, f, ensure_ascii=False, indent=4)
        print("✅ blacklist_url.json 写入成功！")

    else:
        # 不包含黑名单关键字，且 URL 正常，走原有正常写入逻辑
        write_normal_mapping(lines, empty_line_idx, url, json_name_no_ext)

    # 6. 删除 Downloads 目录下的源 json 文件
    try:
        send2trash(json_file)
        print(f"🗑️  已删除源文件: {json_file}")
    except OSError as e:
        show_warning(f"源 json 文件删除失败：{e}")
        sys.exit(1)

    print("✅ 全部任务完成！")


if __name__ == '__main__':
    main()