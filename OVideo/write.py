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

    # --- 修改部分：判断文件名是否包含黑名单关键字 ---
    # 使用 any() 检查文件名中是否包含列表中的任意一个关键字
    is_blacklist_item = any(keyword in json_filename for keyword in BLACKLIST_KEYWORDS)

    if is_blacklist_item:
        print(f"检测到文件名包含黑名单关键字 ({[k for k in BLACKLIST_KEYWORDS if k in json_filename]})，执行黑名单逻辑...")
        
        if not extracted_mapping_url:
            show_warning("无法从 url_mapping.json 的空行中提取出 URL 键！")
            sys.exit(1)
            
        # 从 lines 中删除该空行
        del lines[empty_line_idx]
        
        # 修复 JSON 格式：如果删除的是最后一行数据，上一行末尾可能会多出一个逗号
        # 倒序查找右大括号 '}'，并将它前面有内容的最后一行的逗号去掉
        for j in range(len(lines)-1, -1, -1):
            if '}' in lines[j]:
                for k in range(j-1, -1, -1):
                    if lines[k].strip():  # 找到大括号前最近的有内容的行
                        stripped_k = lines[k].rstrip('\n\r ')
                        if stripped_k.endswith(','):
                            # 去掉末尾的逗号并补回换行符
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
                pass  # 如果文件为空或损坏，初始化为空字典

        # 按照需求写入：键为 mapping 里提取的 url，值为 [json文件名, json里解析的url]
        blacklist_data[extracted_mapping_url] = [json_name_no_ext, url]

        with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(blacklist_data, f, ensure_ascii=False, indent=4)
        print("✅ blacklist_url.json 写入成功！")

    else:
        # 不包含违禁字，执行原有逻辑（已修改为写入列表形式）
        line = lines[empty_line_idx]
        idx = line.rfind('""')
        
        # 使用 json.dumps 将 [解析的url, json名字] 转换为标准的 JSON 数组字符串
        # ensure_ascii=False 保证中文不会被转义为 Unicode 编码
        new_value = json.dumps([url, json_name_no_ext], ensure_ascii=False)
        
        # 替换掉原本的 ""
        new_line = line[:idx] + new_value + line[idx + 2:]
        lines[empty_line_idx] = new_line
        
        print(f"已在第 {empty_line_idx + 1} 行写入 URL 和 文件名")
        print(f"原内容: {line.rstrip()}")
        print(f"新内容: {new_line.rstrip()}")

        # 5. 写回 url_mapping.json
        with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print("✅ url_mapping.json 写入成功！")

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