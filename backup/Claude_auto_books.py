import re
import os
import cv2
import sys
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

# 主函数
def main():
    template_path1 = '/Users/yanzhang/Documents/python_code/Resource/claude_done_125.png'
    template_path2 = '/Users/yanzhang/Documents/python_code/Resource/claude_soldout2.png'
    sleep(2)

    while True:
        location, shape = find_image_on_screen(template_path2)
        if location:
                # 设置stop_signal文件的保存目录
                stop_signal_directory = '/private/tmp'
                
                # 设置stop_signal文件的保存路径
                now = datetime.now()
                time_str = now.strftime("_%m_%d_%H")
                stop_signal_file_name = f"stop_signal{time_str}.txt"
                stop_signal_path = os.path.join(stop_signal_directory, stop_signal_file_name)

                with open(stop_signal_path, 'w') as signal_file:
                        signal_file.write('stop')
                sys.exit(0)  # 安全退出程序
        else:
                print("没找到图片，继续执行...")

    
        location, shape = find_image_on_screen(template_path1)
        if location:
            # 计算中心坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            
            # 鼠标点击中心坐标
            pyautogui.click(center_x, center_y)

            # 设置TXT文件的保存路径
            txt_file_path = '/Users/yanzhang/Documents/book.txt'

            # 读取剪贴板内容
            clipboard_content = pyperclip.paste()

            # 使用splitlines()分割剪贴板内容为多行
            lines = clipboard_content.splitlines()
            # 移除空行
            non_empty_lines = [line for line in lines if line.strip()]

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

            # 删除/tmp/segment.txt文件
            os.remove(segment_file_path)

            # 设置stop_signal文件的保存目录
            stop_signal_directory = '/private/tmp'
            
            # 设置stop_signal文件的保存路径
            now = datetime.now()
            time_str = now.strftime("_%m_%d_%H")
            stop_signal_file_name = f"stop_signal{time_str}.txt"
            stop_signal_path = os.path.join(stop_signal_directory, stop_signal_file_name)

            # 检查 soldout.png 是否存在于屏幕上
            if check_soldout_image():
                # 如果存在，则运行另一个Python脚本
                with open(stop_signal_path, 'w') as signal_file:
                    signal_file.write('stop')
                break  # 运行了另一个脚本后退出循环
            else:
                # 如果soldout.png不存在，则按原步骤执行
                break  # 图片消失后退出循环
        else:
            print("未找到A图片，继续监控...")
            sleep(1)  # 简短暂停再次监控

if __name__ == '__main__':
    main()