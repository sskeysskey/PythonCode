import re
import os
import cv2
import time
import html
import pyperclip
import pyautogui
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
def find_image_on_screen(template_path, threshold=0.9):
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        raise FileNotFoundError(f"模板图片未能正确读取于路径 {template_path}")
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    # 释放截图和模板图像以节省内存
    del screen
    if max_val >= threshold:
        return max_loc, template.shape
    else:
        return None, None

# 检查 soldout.png 是否存在于屏幕上
def check_soldout_image():
    remaining_template_path = '/Users/yanzhang/Documents/python_code/Resource/claude_soldout1.png'  # 替换为你的remaining.png图片实际路径
    location, shape = find_image_on_screen(remaining_template_path, threshold=0.9)
    return bool(location)

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
    html_skeleton_created = False
    html_file_path = ''  # 用空字符串初始化

    template_stop = '/Users/yanzhang/Documents/python_code/Resource/Mistral_stop.png'
    template_copy = '/Users/yanzhang/Documents/python_code/Resource/Mistral_copy.png'

    found_stop = True
    while found_stop:
        location, shape = find_image_on_screen(template_stop)
        if location:
            print("找到stop图了，准备下一步...")
            pyautogui.scroll(-80)
            sleep(1) # 继续监控
        else:
            print("没找到图片，继续执行...")
            found_stop = False

    found_copy = False
    timeout_copy = time.time() + 5
    while not found_copy and time.time() < timeout_copy:
        location, shape = find_image_on_screen(template_copy)
        if location:
            print("找到copy图了，准备点击copy...")
            # 计算中心坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            
            # 鼠标点击中心坐标
            pyautogui.click(center_x, center_y)
            found_copy = True
        else:
            print("没找到图片，继续执行...")
            sleep(1)

    if not found_copy:
        print("在5秒内未找到copy_success图片，退出程序。")
        sys.exit()

    # 读取剪贴板内容
    clipboard_content = pyperclip.paste()

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
    with open(segment_file_path, 'r', encoding='utf-8-sig') as segment_file:
        segment_content = segment_file.read().strip()  # 使用strip()移除可能的空白字符

    # 读取/tmp/site.txt文件内容
    site_file_path = '/tmp/site.txt'
    with open(site_file_path, 'r', encoding='utf-8-sig') as site_file:
        site_content = site_file.read().strip()  # 使用strip()移除可能的空白字符
        
    # 在site_content的前后分别加入</document>
    site_content_with_tags = '<document>' + site_content + '</document>'

    # 将读取到的segment_content内容插入在剪贴板内容的最前面
    final_content = segment_content + '\n' + site_content_with_tags + '\n\n' + modified_content

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

    # 删除/tmp/segment.txt文件
    os.remove(segment_file_path)
    os.remove(site_file_path)

if __name__ == '__main__':
    main()