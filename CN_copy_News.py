import os
import cv2
import html
import time
import shutil
import glob
import sys
import pyperclip
import subprocess
import tempfile
import numpy as np
from PIL import ImageGrab
from datetime import datetime

# ================= 配置区域 =================

# 1. 动态获取当前用户的主目录
# Mac: /Users/yanzhang
# Windows: C:\Users\yanzhang
USER_HOME = os.path.expanduser("~")

# 2. 定义你的 Coding 根目录
# 默认假设 Coding 文件夹在主目录下。如果换了电脑想换位置，只需修改这一行即可。
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 定义下载目录
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 4. 获取临时目录 (关键修改！)
if os.name == 'nt':
    # 如果是 Windows 系统，使用系统标准临时目录 (通常是 AppData\Local\Temp)
    SYSTEM_TEMP_DIR = tempfile.gettempdir()
else:
    # 如果是 macOS 或 Linux，保持使用 /tmp 以兼容你现有的 AppleScript/Shell 流程
    SYSTEM_TEMP_DIR = '/tmp'

# ================= 常量定义 (路径拼接) =================

TXT_DIRECTORY = os.path.join(BASE_CODING_DIR, 'News')
HTML_DIRECTORY = os.path.join(BASE_CODING_DIR, 'Website', 'news')

SEGMENT_FILE_PATH = os.path.join(SYSTEM_TEMP_DIR, 'segment.txt')
SITE_FILE_PATH = os.path.join(SYSTEM_TEMP_DIR, 'site.txt')

SEGMENT_TO_HTML_FILE = {
    "technologyreview": "technologyreview.html",
    "economist": "economist.html",
    "nytimes": "nytimes.html",
    "nikkei": "nikkei.html",
    "bloomberg": "bloomberg.html",
    "hbr": "hbr.html",
    "ft": "ft.html",
    "wsj": "wsj.html",
    "rfi": "rfi.html",
    "dw": "dw.html"
}

# ================= 函数定义 =================

def move_and_record_images(url):
    """
    移动多种格式图片并记录到 article_copier.txt
    """
    # 使用前面定义的动态变量
    source_dir = DOWNLOADS_DIR
    target_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    
    today = datetime.now().strftime("%y%m%d")
    record_file = os.path.join(TXT_DIRECTORY, f"article_copier_{today}.txt")

    # 支持的图片格式
    image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]

    # 确保目标目录和记录文件所在的目录存在
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)

    # 获取所有图片文件
    image_files = []
    for format in image_formats:
        # glob 在 Windows 下也能正常工作
        image_files.extend(glob.glob(os.path.join(source_dir, format)))

    moved_files = []
    # 移动文件
    for image_file in image_files:
        filename = os.path.basename(image_file)
        target_path = os.path.join(target_dir, filename)

        try:
            shutil.move(image_file, target_path)
            moved_files.append(filename)
        except Exception as e:
            # 如果移动失败（例如文件被占用），打印错误但继续
            print(f"Error moving file {image_file}: {e}")


    # 写入记录文件，无论是否有移动文件都写入URL
    content = f"{url}\n\n"
    if moved_files:
        content += "\n".join(moved_files) + "\n\n"
    
    # 使用 with open 确保文件被正确关闭，这是导致死锁的关键操作
    with open(record_file, 'a', encoding='utf-8') as f:
        f.write(content)

def capture_screen():
    # 使用PIL的ImageGrab直接截取屏幕
    screenshot = ImageGrab.grab()
    # 将截图对象转换为OpenCV格式
    screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    return screenshot

# 查找图片
def find_image_on_screen(template, threshold=0.9):
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    # 释放截图和模板图像以节省内存
    del screen
    if max_val >= threshold:
        return max_loc, template.shape
    else:
        return None, None

def refresh_page():
    """
    对当前页面执行 AppleScript 刷新操作
    """
    script = """
    tell application "System Events"
        key code 15 using command down
    end tell
    """
    subprocess.run(['osascript', '-e', script], check=True)
    # 给系统一点时间来完成操作
    time.sleep(0.5)

def get_clipboard_content():
    content = pyperclip.paste()  # 从剪贴板获取原始内容
    
    if not content:  # 检查剪贴板是否为空
        return ""
    
    # —— 新增：如果存在“新闻简报订阅”，则截断并删除它及其后面的所有内容 —— 
    marker = "新闻简报订阅"
    idx = content.find(marker)
    if idx != -1:
        content = content[:idx]
    # —— 新增结束 —— 
    
    # 原来的多行去空行、去首尾空白逻辑
    lines = [line.strip() for line in content.splitlines()]
    # 过滤掉空行
    lines = [line for line in lines if line]
    return "\n".join(lines)

def read_file(file_path):
    # <--- 修改 3: 增加文件存在性检查，避免脚本因文件不存在而崩溃
    if not os.path.exists(file_path):
        print(f"Warning: File not found at {file_path}. Returning empty string.")
        return ""
    with open(file_path, 'r', encoding='utf-8-sig') as file:
        return file.read().strip()

def write_html_skeleton(file_path, title):
    with open(file_path, 'w', encoding='utf-8-sig') as file:
        file.write(f"""
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

def append_to_html(file_path, current_time, content):
    # 读取、处理、写入分离，更安全
    with open(file_path, 'r', encoding='utf-8-sig') as file:
        html_content = file.read()

    escaped_content = html.escape(content).replace('\n', '<br>\n')
    insert_position = html_content.find("</tr>") + 5
    new_row = f"""
            <tr>
                <td>{current_time}</td>
                <td>{escaped_content}</td>
            </tr>
    """
    updated_content = html_content[:insert_position] + new_row + html_content[insert_position:]
    
    with open(file_path, 'w', encoding='utf-8-sig') as file:
        file.write(updated_content)

def close_html_skeleton(file_path):
    with open(file_path, 'a', encoding='utf-8-sig') as file:
        file.write("""
            </table>
        </body>
        </html>
        """)

def main():
    # 获取传入的URL参数
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"

    # 跳转到clipboard_content处理部分
    clipboard_content = get_clipboard_content()
    segment_content = read_file(SEGMENT_FILE_PATH)
    site_content = read_file(SITE_FILE_PATH)
    
    # === 步骤 2: 读取后立刻清理临时文件 ===
    # 这样做可以尽早释放对这些文件的锁定
    if os.path.exists(SEGMENT_FILE_PATH):
        os.remove(SEGMENT_FILE_PATH)
    if os.path.exists(SITE_FILE_PATH):
        os.remove(SITE_FILE_PATH)

    # === 步骤 3: 准备所有要写入的内容 ===
    site_content_with_tags = f'{site_content}'
    
    # final_content = f"{segment_content}\n{site_content_with_tags}\n\n{clipboard_content}"
    final_content = f"{site_content_with_tags}\n\n{clipboard_content}"
    
    now = datetime.now()
    
    # === 步骤 4: 集中执行所有文件写入操作 ===
    # 4.1 写入主新闻日志
    txt_file_name = f"News_{now.strftime('%y_%m_%d')}.txt"
    txt_file_path = os.path.join(TXT_DIRECTORY, txt_file_name)
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content + '\n\n')
    
    # 4.2 写入HTML文件
    html_file_name = SEGMENT_TO_HTML_FILE.get(segment_content.lower(), "other.html")
    html_file_path = os.path.join(HTML_DIRECTORY, html_file_name)
    
    if not os.path.isfile(html_file_path):
        write_html_skeleton(html_file_path, segment_content)
    
    append_to_html(html_file_path, now.strftime('%Y-%m-%d %H:%M:%S'), clipboard_content)
    
    if os.path.isfile(html_file_path):
        close_html_skeleton(html_file_path)
    
    # 4.3 移动图片并写入 article_copier.txt (这是最关键的冲突点)
    # 我们把它放在所有其他文件写入之后，执行外部脚本之前
    move_and_record_images(url)

if __name__ == '__main__':
    main()