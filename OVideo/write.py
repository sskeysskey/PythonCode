import os
import json
import glob
import sys
import tkinter as tk
from tkinter import messagebox
from send2trash import send2trash

DOWNLOADS_DIR = '/Users/yanzhang/Downloads/'
MAPPING_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'


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
    print(f"找到 json 文件: {json_file}")

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

    # 3. 读取 url_mapping.json（按行读取以保留原格式）
    if not os.path.exists(MAPPING_FILE):
        show_warning(f"映射文件不存在：{MAPPING_FILE}")
        sys.exit(1)

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 4. 查找 value 为空的行，并写入 url
    modified = False
    for i, line in enumerate(lines):
        # 去除尾部换行/逗号/空格后判断是否以 "" 结尾（即值为空）
        stripped = line.rstrip('\n').rstrip().rstrip(',').rstrip()
        if stripped.endswith('""'):
            # 找到该行最后一个 "" 的位置（即 value 部分），替换为目标 url
            idx = line.rfind('""')
            new_line = line[:idx] + f'"{url}"' + line[idx + 2:]
            lines[i] = new_line
            print(f"已在第 {i + 1} 行写入 URL")
            print(f"原内容: {line.rstrip()}")
            print(f"新内容: {new_line.rstrip()}")
            modified = True
            break  # 只填充第一个空行；如想填充全部，删掉此行

    if not modified:
        show_warning("url_mapping.json 中没有找到值为空的行！")
        sys.exit(1)

    # 5. 写回文件
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