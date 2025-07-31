import os
import cv2
import sys
import time
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab

class ScreenDetector:
    def __init__(self, template_name, clickValue=False, Opposite=False, x_offset=None, y_offset=None, nth_match=1):
        self.template_path = f'/Users/yanzhang/Coding/python_code/Resource/{template_name}'
        self.template = self.load_template()
        self.clickValue = clickValue
        self.Opposite = Opposite
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.nth_match = max(1, nth_match)  # 确保至少为1

    def load_template(self):
        # 在初始化时加载模板图片
        template = cv2.imread(self.template_path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {self.template_path}")
        return template

    def capture_screen(self):
        # 使用PIL的ImageGrab直接截取屏幕
        screenshot = ImageGrab.grab()
        # 将截图对象转换为OpenCV格式
        screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        return screenshot

    # def find_image_on_screen(self, threshold=0.9):
    #     screen = self.capture_screen()
    #     result = cv2.matchTemplate(screen, self.template, cv2.TM_CCOEFF_NORMED)
    #     min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    #     # 释放截图和模板图像以节省内存
    #     del screen
    #     if max_val >= threshold:
    #         return max_loc, self.template.shape
    #     else:
    #         return None, None

    def find_image_on_screen(self, threshold=0.9):
        screen = self.capture_screen()
        result = cv2.matchTemplate(screen, self.template, cv2.TM_CCOEFF_NORMED)
        
        # 找到所有匹配位置
        locations = np.where(result >= threshold)
        locations = list(zip(*locations[::-1]))  # 转换坐标格式
        
        # 按匹配度排序
        matches = []
        for loc in locations:
            match_value = result[loc[1]][loc[0]]
            matches.append((loc, match_value))
        
        matches.sort(key=lambda x: x[1], reverse=True)  # 按匹配度降序排序
        
        # 释放内存
        del screen
        del result
        
        # 如果找到足够的匹配且指定的第n个存在
        if len(matches) >= self.nth_match:
            return matches[self.nth_match - 1][0], self.template.shape
        return None, None

    def run1(self):
        found = False
        timeout = time.time() + 590
        while not found and time.time() < timeout:
            location, shape = self.find_image_on_screen()
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
                print(f"找到图片位置: {location}")
            else:
                print("未找到图片，继续监控...")
                sleep(1)
        
        if time.time() > timeout:
            print("在60秒内未找到图片，退出程序。")
            webbrowser.open('file://' + os.path.realpath(txt_file_path), new=2)
    
    def run2(self):
        found = True
        while found:
            location, shape = self.find_image_on_screen()
            if location:
                pyautogui.scroll(-120)
                print(f"找到图片位置: {location}")
                sleep(1)
            else:
                print("未找到图片，继续监控...")
                found = False

if __name__ == '__main__':
    # 检查基本参数数量
    if len(sys.argv) < 4:
        print("Usage: python a.py <image_name> <clickValue> <Opposite> [x_offset] [y_offset] [nth_match]")
        sys.exit(1)

    # 基本参数
    image_name = sys.argv[1]
    clickValue = sys.argv[2].lower() == 'true'
    Opposite = sys.argv[3].lower() == 'true'

    # 初始化可选参数
    x_offset = None
    y_offset = None
    nth_match = 1  # 默认值为1

    remaining_args = sys.argv[4:]
    
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

    detector = ScreenDetector(image_name, clickValue, Opposite, x_offset, y_offset, nth_match)

    if Opposite:
        detector.run2()
    else:
        detector.run1()