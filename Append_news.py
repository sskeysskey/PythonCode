import os
import cv2
import html
import time
import shutil
import glob
import pyperclip
import pyautogui
import subprocess
import numpy as np
from time import sleep
from PIL import ImageGrab
from datetime import datetime

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

def get_clipboard_content():
    content = pyperclip.paste()
    if not content:
        return ""
    
    # 分割成行并去除空白行
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    
    # 如果行数小于3，直接返回原内容
    if len(lines) < 3:
        return "\n".join(lines)
    
    # 移除第一行和最后一行
    filtered_lines = lines[:-1]
    
    # 重新组合文本
    return "\n".join(filtered_lines)

def append_to_html(html_file_path, segment_content, modified_content):
    # 获取当前的系统时间，并格式化为字符串
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # HTML转义段落和修改后的内容
    escaped_segment = html.escape(segment_content).replace('\n', '<br>\n')
    escaped_modified = html.escape(modified_content).replace('\n', '<br>\n')
    
    # 读取整个HTML文件内容
    with open(html_file_path, 'r', encoding='utf-8-sig') as html_file:
        html_content = html_file.read()

    # 构造新的表格行
    new_row = f"""
        <tr>
            <td>{current_time}</td>
            <td>{escaped_modified}</td>
        </tr>
    """

    # 找到插入点（在</tr>标签后的第一次出现的位置，这意味着在表格的开头）
    insert_position = html_content.find("</tr>") + 5

    # 插入新的表格行
    updated_html_content = html_content[:insert_position] + new_row + html_content[insert_position:]

    # 写回修改后的HTML内容
    with open(html_file_path, 'w', encoding='utf-8-sig') as html_file:
        html_file.write(updated_html_content)

def create_html_skeleton(html_file_path, title):
    # 创建HTML框架，并设定字体大小
    with open(html_file_path, 'w', encoding='utf-8-sig') as html_file:
        html_file.write(f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
    body {{
        font-size: 28px; /* 设置字体大小 */
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        border: 2px solid #000; /* 加粗整个表格的外边框 */
        box-shadow: 3px 3px 10px rgba(0, 0, 0, 0.2); /* 增加阴影效果 */
    }}
    th, td {{
        padding: 10px;
        text-align: left;
        border-bottom: 2px solid #000;
        border-right: 2px solid #000; /* 增加垂直分割线 */
    }}
    th {{
        background-color: #f2f2f2; /* 表头背景色 */
        font-weight: bold; /* 表头字体加粗 */
    }}
    tr:hover {{
        background-color: #f5f5f5; /* 鼠标悬浮时行背景色变化 */
    }}
    tr:last-child td {{
        border-bottom: 2px solid #000; /* 最后一行的底部边框加粗 */
    }}
    td:last-child, th:last-child {{
        border-right: none; /* 最后一列去除垂直分割线 */
    }}
</style>
        </head>
        <body>
            <table>
                <tr>
                    <th>时间</th>
                    <th>摘要</th>
                </tr>
        """)

def close_html_skeleton(html_file_path):
    # 结束HTML框架
    with open(html_file_path, 'a', encoding='utf-8-sig') as html_file:
        html_file.write("""
            </table>
        </body>
        </html>
        """)

# 主函数
def main():
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

    html_skeleton_created = False
    html_file_path = ''  # 用空字符串初始化

    template_paths = {
        "success": "/Users/yanzhang/Documents/python_code/Resource/poe_copy_success.png",
        "thumb": "/Users/yanzhang/Documents/python_code/Resource/poe_thumb.png",
        "copy": "/Users/yanzhang/Documents/python_code/Resource/poe_copy.png",
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {path}")
        templates[key] = template

    sleep(0.5)
    pyautogui.scroll(-80)

    found_copy = False
    while not found_copy:
        location, shape = find_image_on_screen(templates["thumb"])
        if location:
            print("找到copy图了，准备点击copy...")
            # 计算中心坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            
            xCoord = center_x
            yCoord = center_y - 50

            # 使用pyautogui移动鼠标并进行右键点击
            pyautogui.moveTo(xCoord, yCoord)
            pyautogui.click(button='right')
            
            sleep(1)
            location, shape = find_image_on_screen(templates["copy"])
            if location:
                # 计算中心坐标
                center_x = (location[0] + shape[1] // 2) // 2
                center_y = (location[1] + shape[0] // 2) // 2
                
                # 鼠标点击中心坐标
                pyautogui.click(center_x, center_y)
            found_copy = True

        # 设置寻找poe_copy_success.png图片的超时时间为15秒
        sleep(1)
        found_success_image = False
        timeout_success = time.time() + 5
        while not found_success_image and time.time() < timeout_success:
            location, shape = find_image_on_screen(templates["success"])
            if location:
                print("找到poe_copy_success图片，继续执行程序...")
                found_success_image = True
            sleep(1)  # 每次检测间隔1秒

        if not found_success_image:
            print("在15秒内未找到poe_copy_success图片，退出程序。")
            # webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)

    # 读取剪贴板内容
    clipboard_content = get_clipboard_content()

    # 检查clipboard_content是否为None或者是否是一个字符串
    if clipboard_content:
        # 使用splitlines()分割剪贴板内容为多行
        lines = clipboard_content.splitlines()
        # 移除空行
        non_empty_lines = [line for line in lines if line.strip()]
    else:
        print("剪贴板中没有内容或pyperclip无法访问剪贴板。")
        non_empty_lines = []  # 确保non_empty_lines是一个列表，即使剪贴板为空

    # 将非空行合并为一个字符串，用换行符分隔
    modified_content = '\n'.join(non_empty_lines)

    # 读取/tmp/segment.txt文件内容
    segment_file_path = '/tmp/segment.txt'
    segment_content = ""
    if os.path.exists(segment_file_path):
        with open(segment_file_path, 'r', encoding='utf-8-sig') as segment_file:
            segment_content = segment_file.read().strip()  # 使用strip()移除可能的空白字符

    # 读取/tmp/site.txt文件内容
    site_file_path = '/tmp/site.txt'
    site_content = ""
    if os.path.exists(site_file_path):
        with open(site_file_path, 'r', encoding='utf-8-sig') as site_file:
            site_content = site_file.read().strip()  # 使用strip()移除可能的空白字符
        
    # 在site_content的前后分别加入</document>
    # site_content_with_tags = '<document>' + site_content + '</document>'
    site_content_with_tags = f'{site_content}'

    # 将读取到的segment_content内容插入在剪贴板内容的最前面
    # final_content = segment_content + '\n' + site_content_with_tags + '\n\n' + modified_content
    final_content = f"{site_content_with_tags}\n\n{clipboard_content}"

    # 设置txt文件的保存目录
    txt_directory = '/Users/yanzhang/Documents/News'
    
    # 设置TXT文件的保存路径
    now = datetime.now()
    time_str = now.strftime("_%y_%m_%d")
    txt_file_name = f"News{time_str}.txt"
    txt_file_path = os.path.join(txt_directory, txt_file_name)

    if not os.path.isfile(txt_file_path):
        with open(txt_file_path, 'w', encoding='utf-8-sig') as txt_file:
            pass  # 创建文件后不进行任何操作，文件会被关闭

    # 追加处理后的内容到TXT文件
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content)
        txt_file.write('\n\n')  # 添加两个换行符以创建一个空行

    # 确定segment内容，并选择相应的HTML文件
    segment_to_html_file = {
        "technologyreview": "technologyreview.html",
        "economist": "economist.html",
        "nytimes": "nytimes.html",
        "nikkei": "nikkei.html",
        "bloomberg": "bloomberg.html",
        "hbr": "hbr.html",
        "ft": "ft.html",
        "wsj": "wsj.com"
    }

    # 根据segment内容获取对应的HTML文件名
    html_file_name = segment_to_html_file.get(segment_content.lower(), "other.html")
    html_file_path = os.path.join('/Users/yanzhang/Documents/sskeysskey.github.io/news', html_file_name)

    # 根据segment内容获取对应的标题
    title = segment_content if segment_content.lower() in segment_to_html_file else "新闻摘要"

    # 检查HTML文件是否已经存在
    html_skeleton_created = os.path.isfile(html_file_path)

    # 检查HTML文件是否已经存在
    if not html_skeleton_created:
        create_html_skeleton(html_file_path, title)
    
    # 追加内容到HTML文件
    append_to_html(html_file_path, segment_content, modified_content)

    # 最后，关闭HTML框架
    if html_skeleton_created and not os.path.isfile(html_file_path):
        close_html_skeleton(html_file_path)

    script_path = '/Users/yanzhang/Documents/ScriptEditor/Close_Tab_News.scpt'
    try:
        # 将坐标值作为参数传递给AppleScript
        process = subprocess.run(['osascript', script_path], check=True, text=True, stdout=subprocess.PIPE)
        # 输出AppleScript的返回结果
        print(process.stdout.strip())
    except subprocess.CalledProcessError as e:
        # 如果有错误发生，打印错误信息
        print(f"Error running AppleScript: {e}")
    
    move_and_record_images(site_content)
    sleep(0.3)
    
    # 检查并删除/tmp/segment.txt和site.txt文件
    try:
        if os.path.exists(segment_file_path):
            os.remove(segment_file_path)
    except Exception as e:
        print(f"无法删除文件：{e}")
    
    try:
        if os.path.exists(site_file_path):
            os.remove(site_file_path)
    except Exception as e:
        print(f"无法删除文件：{e}")
    
if __name__ == '__main__':
    main()