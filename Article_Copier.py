import cv2
import numpy as np
from PIL import ImageGrab
import os
import sys
from datetime import datetime

def capture_screen():
    """
    使用PIL的ImageGrab直接截取屏幕，并转换为OpenCV格式
    """
    screenshot = ImageGrab.grab()
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

def find_image_on_screen(template, threshold=0.9):
    """
    在当前屏幕中查找给定模板图像的匹配位置（精度默认0.9）。
    如果找到，则返回匹配位置，否则返回None。
    """
    screen = capture_screen()
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    # 释放截图及相关资源
    del screen
    if max_val >= threshold:
        return max_loc
    return None

def write_to_failure_file(url):
    """
    将URL写入失败记录文件
    """
    file_path = "/Users/yanzhang/Coding/News/Copier_failure.txt"
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"[{current_time}] {url}\n"
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(content)

def main():
    # 获取传入的URL参数
    url = sys.argv[1] if len(sys.argv) > 1 else "No URL provided"
    
    # 读取模板图片
    template_path = "/Users/yanzhang/Coding/python_code/Resource/copier_text_failure.png"
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        raise FileNotFoundError(f"模板图片未能正确读取于路径 {template_path}")

    # 检查failure图片
    location = find_image_on_screen(template)
    if location:
        print(f"找到failure图片位置: {location}")
        write_to_failure_file(url)

if __name__ == '__main__':
    main()