import os
import cv2
import time
import pyperclip
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab
import sys
sys.path.append('/Users/yanzhang/Coding/python_code/Modules')
from Rename_segment import rename_first_segment_file

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

# 主函数
def main():
    template_paths = {
        "stop": "/Users/yanzhang/Coding/python_code/Resource/Kimi_stop.png",
        "copy": "/Users/yanzhang/Coding/python_code/Resource/Kimi_copy.png",
        "outofline": "/Users/yanzhang/Coding/python_code/Resource/Kimi_outofline.png"
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {path}")
        templates[key] = template

    found = False
    timeout_stop = time.time() + 5
    while not found and time.time() < timeout_stop:
        location, shape = find_image_on_screen(templates["stop"])
        if location:
            found = True
            print(f"找到图片位置: {location}")
        else:
            print("未找到图片，继续监控...")
            pyautogui.scroll(-80)
            sleep(1)

    if time.time() > timeout_stop:
        print("在15秒内未找到图片，退出程序。")

    location, shape = find_image_on_screen(templates["outofline"])
    if location:
        pyperclip.copy("illegal")
        timeout_stop = time.time() - 20
        exit()

    found_stop = True
    while found_stop:
        location, shape = find_image_on_screen(templates["stop"])
        if location:
            print("找到stop图了，准备下一步...")
            pyautogui.scroll(-80)
            sleep(1) # 继续监控
        else:
            print("没找到图片，继续执行...")
            pyautogui.scroll(-80)
            location, shape = find_image_on_screen(templates["stop"])
            if not location:
                found_stop = False

    pyautogui.scroll(-80)
    sleep(1.5)
    found_copy = False
    timeout_copy = time.time() + 30
    while not found_copy and time.time() < timeout_copy:
        location, shape = find_image_on_screen(templates["copy"])
        if location:
            print("找到copy图了，准备点击copy...")
            # 计算中心坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            
            modify_x = center_x
            modify_y = center_y - 2

            # 鼠标点击中心坐标
            pyautogui.click(modify_x, modify_y)
            found_copy = True
            sleep(0.5)
            pyautogui.moveTo(x=569, y=474)
        else:
            print("没找到图片，继续执行...")
            pyautogui.scroll(-80)
            location, shape = find_image_on_screen(templates["outofline"])
            if location:
                pyperclip.copy("illegal")
                print(f"找到图片位置: {location}")
                exit()
            sleep(1)

    if not found_copy:
        print("在5秒内未找到copy_success图片，退出程序。")
        webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)

    # 设置目录路径
    directory_path = '/Users/yanzhang/Coding/'

    # 寻找目录下的第一个txt文件
    for filename in os.listdir(directory_path):
        if filename.endswith('.txt'):
            txt_file_path = os.path.join(directory_path, filename)
            break  # 找到第一个txt文件后停止循环

    # 读取剪贴板内容
    clipboard_content = pyperclip.paste()

    # 检查clipboard_content是否为None或者是否是一个字符串
    if clipboard_content:
        # 使用splitlines()分割剪贴板内容为多行
        lines = clipboard_content.splitlines()
        # 移除空行
        non_empty_lines = [line.replace('#', '').replace('*', '').strip() for line in lines if line.strip()]
    else:
        print("剪贴板中没有内容或pyperclip无法访问剪贴板。")
        non_empty_lines = []  # 确保non_empty_lines是一个列表，即使剪贴板为空

    # 将非空行合并为一个字符串，用换行符分隔
    modified_content = '\n'.join(non_empty_lines)

    # 读取/tmp/segment.txt文件内容
    segment_file_path = '/tmp/segment.txt'
    with open(segment_file_path, 'r', encoding='utf-8-sig') as segment_file:
        segment_content = segment_file.read().strip()  # 使用strip()移除可能的空白字符

    # 在segment_content后面添加一个换行符
    segment_content += '\n'
    
    # 将读取到的segment_content内容插入在剪贴板内容的最前面
    final_content = segment_content + modified_content

    # 追加处理后的内容到TXT文件
    with open(txt_file_path, 'a', encoding='utf-8-sig') as txt_file:
        txt_file.write(final_content)
        txt_file.write('\n\n')  # 添加两个换行符以创建一个空行

    # 使用函数
    directory = "/Users/yanzhang/Downloads/backup/TXT/Segments/"
    rename_first_segment_file(directory)
    
    # 删除/tmp/segment.txt文件
    os.remove(segment_file_path)

    book_auto_signal_path = "/private/tmp/book_auto_signal.txt"
    # 检查并删除/private/tmp/book_auto_signal.txt文件
    if os.path.exists(book_auto_signal_path):
        os.remove(book_auto_signal_path)

if __name__ == '__main__':
    main()