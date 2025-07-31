import os
import cv2
import sys
import time
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab

class ScreenDetector:
    def __init__(self, template_names, clickValue=False, Opposite=False, x_offset=None, y_offset=None, nth_match=1):
        self.templates = []
        # 支持单个字符串或字符串列表
        if isinstance(template_names, str):
            template_names = [name.strip() for name in template_names.split(',')]  # 添加strip()去除空白字符
        
        # 加载所有模板
        for template_name in template_names:
            template_path = f'/Users/yanzhang/Documents/python_code/Resource/{template_name}'
            template = self.load_template(template_path)
            self.templates.append((template_name, template))
            
        self.clickValue = clickValue
        self.Opposite = Opposite
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.nth_match = max(1, nth_match)  # 确保至少为1

    def load_template(self, template_path):
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {template_path}")
        return template

    def capture_screen(self):
        # 使用PIL的ImageGrab直接截取屏幕
        screenshot = ImageGrab.grab()
        # 将截图对象转换为OpenCV格式
        screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        return screenshot

    def find_images_on_screen(self, threshold=0.9):
        screen = self.capture_screen()
        for template_name, template in self.templates:
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            locations = list(zip(*locations[::-1]))
            
            if locations:  # 如果找到匹配
                matches = []
                for loc in locations:
                    match_value = result[loc[1]][loc[0]]
                    matches.append((loc, match_value))
                
                matches.sort(key=lambda x: x[1], reverse=True)
                
                if len(matches) >= self.nth_match:
                    return template_name, matches[self.nth_match - 1][0], template.shape
                    
        return None, None, None

    def run1(self):
        found = False
        timeout = time.time() + 590
        while not found and time.time() < timeout:
            template_name, location, shape = self.find_images_on_screen()
            if location:
                if self.clickValue:
                    # 计算中心坐标
                    center_x = (location[0] + shape[1] // 2) // 2
                    center_y = (location[1] + shape[0] // 2) // 2
                    # 判断是否有偏移量，调整点击坐标
                    if self.x_offset is not None:
                        center_x += self.x_offset
                    if self.y_offset is not None:
                        center_y += self.y_offset
                    
                    # 鼠标点击中心坐标或偏移后的坐标
                    pyautogui.click(center_x, center_y)
                found = True
                print(f"找到图片 {template_name} 位置: {location}")
            else:
                print("未找到任何目标图片，继续监控...")
                sleep(1)
        
        if time.time() > timeout:
            print("在590秒内未找到图片，退出程序。")
            webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)
    
    def run2(self):
        found = True
        while found:
            template_name, location, shape = self.find_images_on_screen()
            if location:
                pyautogui.scroll(-120)
                print(f"找到图片 {template_name} 位置: {location}")
                sleep(1)
            else:
                print("未找到图片，继续监控...")
                found = False

if __name__ == '__main__':
    # 检查基本参数数量
    if len(sys.argv) < 4:
        print("Usage: python a.py <image_name1[,image_name2]> <clickValue> <Opposite> [x_offset] [y_offset] [nth_match]")
        sys.exit(1)

    # 支持多个图片名称，用逗号分隔，并清理空白字符
    image_names = [name.strip() for name in sys.argv[1].split(',')]
    clickValue = sys.argv[2].lower() == 'true'
    Opposite = sys.argv[3].lower() == 'true'

    # 初始化可选参数
    x_offset = None
    y_offset = None
    nth_match = 1  # 默认值为1

    remaining_args = sys.argv[4:]
    
    # 处理剩余参数的逻辑保持不变
    if remaining_args:
        # 场景1: 只有一个额外参数，认为是 nth_match
        if len(remaining_args) == 1:
            try:
                nth_match = int(remaining_args[0])
            except ValueError:
                print("Invalid nth_match value")
                sys.exit(1)
        
        # 场景2: 有两个额外参数，认为是 x_offset 和 y_offset
        elif len(remaining_args) == 2:
            try:
                x_offset = int(remaining_args[0]) if remaining_args[0] and remaining_args[0] != "" else None
                y_offset = int(remaining_args[1]) if remaining_args[1] and remaining_args[1] != "" else None
            except ValueError:
                print("Invalid offset values")
                sys.exit(1)
        
        # 场景3: 有三个额外参数，认为是 x_offset, y_offset 和 nth_match
        elif len(remaining_args) == 3:
            try:
                x_offset = int(remaining_args[0]) if remaining_args[0] and remaining_args[0] != "" else None
                y_offset = int(remaining_args[1]) if remaining_args[1] and remaining_args[1] != "" else None
                nth_match = int(remaining_args[2]) if remaining_args[2] and remaining_args[2] != "" else 1
            except ValueError:
                print("Invalid parameter values")
                sys.exit(1)

    detector = ScreenDetector(image_names, clickValue, Opposite, x_offset, y_offset, nth_match)

    if Opposite:
        detector.run2()
    else:
        detector.run1()