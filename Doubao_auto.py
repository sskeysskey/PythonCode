import os
import cv2
import time
import pyautogui
import numpy as np
from PIL import ImageGrab
from time import sleep

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
    
    if max_val >= threshold:
        return max_loc, template.shape
    else:
        return None, None

def main():
    # 1. 统一键名为 "doubaocopy"
    template_paths = {
        "doubaocopy": "/Users/yanzhang/Coding/python_code/Resource/doubao_copy.png",
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        if not os.path.exists(path):
            print(f"错误：找不到模板文件 {path}")
            return
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        templates[key] = template

    found = False
    timeout_duration = 30  # 设置30秒超时
    timeout_stop = time.time() + timeout_duration
    
    print("开始监控豆包复制按钮...")

    while not found and time.time() < timeout_stop:
        # 使用正确的键名 "doubaocopy"
        location, shape = find_image_on_screen(templates["doubaocopy"])
        
        if location:
            found = True
            # 计算点击坐标 (针对 Retina 屏通常需要除以 2)
            # location 是像素坐标，pyautogui 需要的是点坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            
            pyautogui.click(center_x, center_y)
            print(f"找到并点击图片位置: {center_x}, {center_y}")
            sleep(1) # 点击后稍作停顿，确保剪贴板刷新
        else:
            print("未找到复制按钮，尝试向下滚动...")
            pyautogui.scroll(-80)
            sleep(1)

    if not found:
        print("在60秒内未找到图片，退出程序。")
        
if __name__ == '__main__':
    main()
