import html
import os
import re
import pyperclip
import shutil
import glob
import subprocess
import sys
import tempfile
from datetime import datetime
from time import sleep

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义基础 Coding 目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 具体业务路径
TXT_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
HTML_DIRECTORY = os.path.join(BASE_CODING_DIR, "Website", "news")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 4. 临时文件路径 (混合策略)
# Windows 下使用系统临时目录，Mac 下保持 /tmp 以兼容可能的外部 AppleScript
if os.name == 'nt':
    TEMP_DIR = tempfile.gettempdir()
else:
    TEMP_DIR = "/tmp"

SEGMENT_FILE_PATH = os.path.join(TEMP_DIR, 'segment.txt')
SITE_FILE_PATH = os.path.join(TEMP_DIR, 'site.txt')
RATIO_FILE_PATH = os.path.join(TEMP_DIR, 'english_ratio_result.txt')

SEGMENT_TO_HTML_FILE = {
    "technologyreview": "technologyreview.html",
    "economist": "economist.html",
    "nytimes": "nytimes.html",
    "nikkei": "nikkei.html",
    "bloomberg": "bloomberg.html",
    "hbr": "hbr.html",
    "ft": "ft.html",
    "wsj": "wsj.html",
    "reuters": "reuters.html",
    "washingtonpost": "washingtonpost.html",
    "nikkeiasia": "nikkei_asia.html"
}

def is_english_char(char: str) -> bool:
    """
    判断字符是否为英文字母（包含大小写）。
    """
    return bool(re.match(r'[a-zA-Z]', char))

def check_english_ratio() -> bool:
    """
    从剪贴板获取文本，计算其中英文字母占比并将结果写入临时文件。
    返回英文字母占比是否大于 0.5。
    """
    text = pyperclip.paste()
    if not text:
        return False
    english_chars = sum(1 for char in text if is_english_char(char))
    total_chars = sum(1 for char in text if not char.isspace())
    if total_chars == 0:
        return False
    english_ratio = english_chars / total_chars
    with open(RATIO_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write('true' if english_ratio > 0.5 else 'false')
    return english_ratio > 0.5

def get_clipboard_content() -> str:
    """
    获取剪贴板内容，去除空白行。
    """
    content = pyperclip.paste()
    if not content:
        return ""
    
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return "\n".join(lines)

def read_file(file_path: str) -> str:
    """
    读取指定文件并返回其内容（去除首尾空白）。
    """
    if not os.path.exists(file_path):
        return ""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        return f.read().strip()

def write_html_skeleton(file_path: str, title: str) -> None:
    """
    创建并写入 HTML 骨架。
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8-sig') as f:
        f.write(f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
                body {{ font-size: 28px; }}
                table {{ width: 100%; border-collapse: collapse; border: 2px solid #000; box-shadow: 3px 3px 10px rgba(0, 0, 0, 0.2); }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 2px solid #000; border-right: 2px solid #000; }}
                th {{ background-color: #f2f2f2; font-weight: bold; }}
                tr:hover {{ background-color: #f5f5f5; }}
                tr:last-child td {{ border-bottom: 2px solid #000; }}
                td:last-child, th:last-child {{ border-right: none; }}
            </style>
        </head>
        <body>
            <table>
                <tr>
                    <th>时间</th>
                    <th>摘要</th>
                </tr>
        """)

def append_to_html(file_path: str, current_time: str, content: str) -> None:
    """
    将新的条目（时间和内容）以行的形式插入到指定的 HTML 文件第一行记录之后。
    """
    if not os.path.exists(file_path):
        return
    with open(file_path, 'r+', encoding='utf-8-sig') as f:
        escaped_content = html.escape(content).replace('\n', '<br>\n')
        html_content = f.read()
        insert_position = html_content.find("</tr>") + 5
        new_row = f"""
            <tr>
                <td>{current_time}</td>
                <td>{escaped_content}</td>
            </tr>
        """
        updated_content = html_content[:insert_position] + new_row + html_content[insert_position:]
        f.seek(0)
        f.write(updated_content)

def close_html_skeleton(file_path: str) -> None:
    """
    在 HTML 文件末尾补充关闭标签。
    """
    with open(file_path, 'a', encoding='utf-8-sig') as f:
        f.write("""
            </table>
        </body>
        </html>
        """)

def remove_file(file_path: str) -> None:
    """
    安全地删除文件，如果文件不存在则忽略错误并打印提示。
    """
    try:
        os.remove(file_path)
    except OSError:
        pass

def move_and_record_images(url: str) -> None:
    """
    移动多种格式图片并记录到article_copier.txt
    (已提取为独立函数，并使用动态路径)
    """
    source_dir = DOWNLOADS_DIR
    today = datetime.now().strftime("%y%m%d")
    target_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    record_file = os.path.join(TXT_DIRECTORY, f"article_copier_{today}.txt")
    image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)
    image_files = []
    for fmt in image_formats:
        image_files.extend(glob.glob(os.path.join(source_dir, fmt)))
    moved_files = []
    for image_file in image_files:
        filename = os.path.basename(image_file)
        target_path = os.path.join(target_dir, filename)
        try:
            shutil.move(image_file, target_path)
            moved_files.append(filename)
        except Exception as e:
            print(f"Error moving file {image_file}: {e}")
    content = f"{url}\n\n"
    if moved_files:
        content += "\n".join(moved_files) + "\n\n"
    with open(record_file, 'a', encoding='utf-8') as f:
        f.write(content)

def main() -> None:
    """
    主流程
    """
    # 获取传入的URL参数
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"
    check_english_ratio()
    sleep(0.2)
    
    # 拼接最终内容
    clipboard_content = get_clipboard_content()
    if clipboard_content:
        # 全局去除 # 和 *
        clipboard_content = clipboard_content.replace('#', '').replace('*', '')
        lines = [line.strip() for line in clipboard_content.splitlines()]

        # =========================================================
        #   逻辑块 A：条件删除第一段内容
        #   修改点：
        #     1. 原有：第一段包含"总结"则删除（无字数限制）
        #     2. 新增：前两段中字符数 ≤ 13 且含"总结"或"分模块"则整段删除
        # =========================================================
        if lines:
            # 原有逻辑保持不变
            if "总结" in lines[0]:
                lines.pop(0)

            # 新增逻辑：收集前两段里符合条件的行索引，再倒序删除
            indices_to_remove = [
                i for i in range(min(2, len(lines)))
                if len(lines[i]) <= 15 and ("总结" in lines[i] or "分模块" in lines[i])
            ]
            for i in reversed(indices_to_remove):
                lines.pop(i)

        # =========================================================
        #   逻辑块 B：处理尾部 (Footer Processing) - 顺序清理
        # =========================================================
        changed = True
        while changed and lines:
            changed = False
            last_line = lines[-1]

            # 1. 文本特征判断
            if last_line.startswith(("需要我", "是否需要", "你是否", "我可以", "要不要我", "如果你需要")):
                lines.pop(-1)
                changed = True
                continue

            # 2. 横线判断
            if lines:
                current_last = lines[-1]
                if len(current_last) > 0 and current_last.replace('-', '').strip() == '':
                    lines.pop(-1)
                    changed = True
                    continue

        # =========================================================
        #   逻辑块 C：广告过滤及全局横线过滤
        # =========================================================
        lines = [
            line for line in lines 
            if line.strip() != "广告"  # 过滤只有“广告”两个字的行
            and not line.strip().startswith("AdChoices") # 过滤以 AdChoices 开头的行
            and not (len(line) > 0 and line.replace('-', '').strip() == '') # 全局过滤只包含“-”的行
        ]
        clipboard_content = "\n".join(lines)

    # 拼接最终内容
    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)
    
    site_content_with_tags = f'{site_content}'
    final_content = f"{site_content_with_tags}\n\n{clipboard_content}"
    
    # 写入 TXT 文件
    now = datetime.now()
    txt_file_name = f"News_{now.strftime('%y_%m_%d')}.txt"
    txt_file_path = os.path.join(TXT_DIRECTORY, txt_file_name)
    
    # 确保目录存在
    os.makedirs(TXT_DIRECTORY, exist_ok=True)
    
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content + '\n\n')
    
    # 写入 HTML 文件
    html_file_name = SEGMENT_TO_HTML_FILE.get(segment_content.lower(), "other.html")
    html_file_path = os.path.join(HTML_DIRECTORY, html_file_name)
    if not os.path.isfile(html_file_path):
        write_html_skeleton(html_file_path, segment_content)
    append_to_html(html_file_path, now.strftime('%Y-%m-%d %H:%M:%S'), clipboard_content)
    
    if os.path.isfile(html_file_path):
        close_html_skeleton(html_file_path)
    
    move_and_record_images(url)
    sleep(0.3)
    
    # 删除临时文件
    remove_file(SEGMENT_FILE_PATH)
    remove_file(SITE_FILE_PATH)

if __name__ == '__main__':
    main()