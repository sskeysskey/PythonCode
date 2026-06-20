import os
import json
import glob
import sys
import re
import tkinter as tk
from tkinter import messagebox
from send2trash import send2trash
import pyperclip  # 新增：剪贴板库

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


def main():
    # 1. 查找 Downloads 目录下的 json 文件
    all_json_files = glob.glob(os.path.join(DOWNLOADS_DIR, '*.json'))

    # --- 新增逻辑：过滤掉 kalshi_ 开头的文件 ---
    # 使用列表推导式，只保留不以 'kalshi_' 开头的文件
    json_files = [f for f in all_json_files if not os.path.basename(f).startswith('kalshi_')]

    if len(json_files) == 0:
        show_warning("Downloads 目录下没有找到有效的 json 文件（已排除 kalshi_ 相关文件）！")
        sys.exit(1)

    if len(json_files) > 1:
        # 如果过滤后仍然大于1，说明确实存在多个需要处理的文件，报错
        files_list = "\n".join(os.path.basename(f) for f in json_files)
        show_warning(f"Downloads 目录下发现 {len(json_files)} 个有效 json 文件，程序终止：\n\n{files_list}")
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

    # 新增：自动复制到剪贴板
    try:
        pyperclip.copy(url)
        print(f"✅ 已将 .m3u8 链接复制到剪贴板！")
    except Exception as e:
        show_warning(f"复制到剪贴板失败：{str(e)}")

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