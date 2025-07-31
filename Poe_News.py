# o1优化后代码
import html
import os
import re
import pyperclip
import shutil
import glob
import subprocess
import sys
from datetime import datetime
from time import sleep

# 常量定义
TXT_DIRECTORY = '/Users/yanzhang/Documents/News'
HTML_DIRECTORY = '/Users/yanzhang/Documents/sskeysskey.github.io/news'
SCRIPT_PATH = '/Users/yanzhang/Documents/ScriptEditor/Close_Tab_News.scpt'
SEGMENT_FILE_PATH = '/tmp/segment.txt'
SITE_FILE_PATH = '/tmp/site.txt'
RATIO_FILE_PATH = '/tmp/english_ratio_result.txt'

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
    "nytimes": "nytimes.html",
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
    从剪贴板获取文本，计算其中英文字母占比并将结果写入 /tmp/english_ratio_result.txt。
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
    
    with open(RATIO_FILE_PATH, 'w') as f:
        f.write('true' if english_ratio > 0.5 else 'false')
    
    return english_ratio > 0.5

def get_clipboard_content() -> str:
    """
    获取剪贴板内容，去除空白行。
    如果行数小于 3，直接返回原内容，否则去掉第一行和最后一行后再返回。
    """
    content = pyperclip.paste()
    if not content:
        return ""
    
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    # 移除第一行和最后一行
    # filtered_lines = lines[1:-1]
    
    return "\n".join(lines)

def read_file(file_path: str) -> str:
    """
    读取指定文件并返回其内容（去除首尾空白）。
    """
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        return f.read().strip()

def write_html_skeleton(file_path: str, title: str) -> None:
    """
    创建并写入 HTML 骨架。
    """
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
    except OSError as e:
        print(f"Error removing {file_path}: {e}")

def main() -> None:
    """
    主流程：
    1. 检查剪贴板中英文字符占比并写入临时文件。
    2. 读取结果判断是否执行 Poe_auto.py。
    3. 读取 segment.txt 和 site.txt，并生成最终文本写入 TXT。
    4. 在对应的 HTML 中追加记录并关闭 HTML 标签。
    5. 执行关闭新闻 Tab 的 AppleScript 脚本。
    6. 删除临时文件。
    """
    # 获取传入的URL参数
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"

    def move_and_record_images(url):
        """
        移动多种格式图片并记录到article_copier.txt
        """
        source_dir = "/Users/yanzhang/Downloads"
        today = datetime.now().strftime("%y%m%d")
        target_dir = f"/Users/yanzhang/Downloads/news_images"
        record_file = f"/Users/yanzhang/Documents/News/article_copier_{today}.txt"
        
        # 支持的图片格式
        image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]

        # 确保目标目录存在
        os.makedirs(target_dir, exist_ok=True)
        os.makedirs(os.path.dirname(record_file), exist_ok=True)

        # 获取所有图片文件
        image_files = []
        for format in image_formats:
            image_files.extend(glob.glob(os.path.join(source_dir, format)))
        moved_files = []

        # 移动文件
        for image_file in image_files:
            filename = os.path.basename(image_file)
            target_path = os.path.join(target_dir, filename)
            shutil.move(image_file, target_path)
            moved_files.append(filename)

        # 写入记录文件，无论是否有移动文件都写入URL
        content = f"{url}\n\n"
        if moved_files:
            content += "\n".join(moved_files) + "\n\n"
        
        with open(record_file, 'a', encoding='utf-8') as f:
            f.write(content)

    check_english_ratio()
    sleep(0.2)
    
    try:
        with open(RATIO_FILE_PATH, 'r') as f:
            is_english = (f.read().strip().lower() == 'true')
        remove_file(RATIO_FILE_PATH)
        
        if is_english:
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                poe_auto_path = os.path.join(current_dir, 'Poe_auto.py')
                # 执行 Poe_auto.py，带参数"short"
                subprocess.run([sys.executable, poe_auto_path, 'short'], check=True)
            except subprocess.CalledProcessError as e:
                print(f"Error executing Poe_auto.py: {e}")
            except Exception as e:
                print(f"Unexpected error running Poe_auto.py: {e}")
    except Exception as e:
        print(f"Error reading english_ratio_result.txt: {e}")
    
    # 拼接最终内容
    clipboard_content = get_clipboard_content()
    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)
    
    # site_content_with_tags = f'<document>{site_content}</document>请用中文详细总结这篇文章'
    site_content_with_tags = f'{site_content}'
    # final_content = f"{segment_content}\n{site_content_with_tags}\n\n{clipboard_content}"
    final_content = f"{site_content_with_tags}\n\n{clipboard_content}"
    
    # 写入 TXT 文件
    now = datetime.now()
    txt_file_name = f"News_{now.strftime('%y_%m_%d')}.txt"
    txt_file_path = os.path.join(TXT_DIRECTORY, txt_file_name)
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
    
    # 执行 AppleScript
    try:
        result = subprocess.run(['osascript', SCRIPT_PATH], check=True, text=True, stdout=subprocess.PIPE)
        print(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        print(f"Error running AppleScript: {e}")
    
    move_and_record_images(url)
    sleep(0.3)
    # 删除临时文件
    remove_file(SEGMENT_FILE_PATH)
    remove_file(SITE_FILE_PATH)

if __name__ == '__main__':
    main()