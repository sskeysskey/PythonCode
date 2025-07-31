import os
import cv2
import sys
import time
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab
from contextlib import contextmanager
from typing import List, Tuple, Optional, Generator

class ScreenDetector:
    def __init__(self, template_names: str | List[str], clickValue: bool = False, 
                 Opposite: bool = False, x_offset: Optional[int] = None, 
                 y_offset: Optional[int] = None, nth_match: int = 1):
        self.templates = []
        self.clickValue = clickValue
        self.Opposite = Opposite
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.nth_match = max(1, nth_match)
        
        # 存储模板名称列表，用于判断是否有多个模板
        if isinstance(template_names, str):
            self.template_name_list = [name.strip() for name in template_names.split(',')]
        else:
            self.template_name_list = template_names
        
        # 优化模板加载
        self._load_templates(template_names)

    def _load_templates(self, template_names: str | List[str]) -> None:
        """优化的模板加载方法"""
        if isinstance(template_names, str):
            template_names = [name.strip() for name in template_names.split(',')]
        
        for template_name in template_names:
            template_path = os.path.join('/Users/yanzhang/Coding/python_code/Resource', template_name)
            try:
                with self._load_template(template_path) as template:
                    self.templates.append((template_name, template))
            except FileNotFoundError as e:
                print(f"Error loading template: {e}")
                continue

    @staticmethod
    @contextmanager
    def _load_template(template_path: str) -> Generator:
        """使用上下文管理器加载模板"""
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {template_path}")
        try:
            yield template
        finally:
            del template

    def capture_screen(self) -> np.ndarray:
        """优化的屏幕捕获方法"""
        with ImageGrab.grab() as screenshot:
            # 直接转换为numpy数组并更改颜色空间
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    def find_images_on_screen(self, threshold: float = 0.9) -> Tuple[Optional[str], Optional[Tuple[int, int]], Optional[Tuple[int, int, int]]]:
        """优化的图像查找方法"""
        with np.errstate(divide='ignore', invalid='ignore'):
            screen = self.capture_screen()
            
            for template_name, template in self.templates:
                result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                locations = np.where(result >= threshold)
                
                if locations[0].size > 0:
                    matches = [(loc, result[loc[1]][loc[0]]) 
                             for loc in zip(*locations[::-1])]
                    matches.sort(key=lambda x: x[1], reverse=True)
                    
                    if len(matches) >= self.nth_match:
                        return template_name, matches[self.nth_match - 1][0], template.shape
            
            return None, None, None

    def _perform_click(self, location: Tuple[int, int], shape: Tuple[int, int, int]) -> None:
        """优化的点击操作"""
        center_x = (location[0] + shape[1] // 2) // 2
        center_y = (location[1] + shape[0] // 2) // 2
        
        if self.x_offset is not None:
            center_x += self.x_offset
        if self.y_offset is not None:
            center_y += self.y_offset
        
        pyautogui.click(center_x, center_y)

    def run1(self) -> str:
        """优化的运行方法1，返回找到的图片名"""
        timeout = time.time() + 590
        
        while time.time() < timeout:
            template_name, location, shape = self.find_images_on_screen()
            
            if location:
                if self.clickValue:
                    self._perform_click(location, shape)
                print(f"找到图片 {template_name} 位置: {location}")

                if len(self.template_name_list) > 1:
                    print(f"FOUND_IMAGE:{template_name}")
                return template_name            
            
            print("未找到任何目标图片，继续监控...")
            sleep(1)
        
        print("在590秒内未找到图片，退出程序。")
        return "TIMEOUT"

    def run2(self) -> None:
        """优化的运行方法2"""
        while True:
            template_name, location, shape = self.find_images_on_screen()
            
            if not location:
                print("未找到图片，继续监控...")
                break
            
            pyautogui.scroll(-120)
            print(f"找到图片 {template_name} 位置: {location}")
            sleep(1)

def parse_args() -> Tuple:
    """参数解析函数"""
    if len(sys.argv) < 4:
        print("Usage: python a.py <image_name1[,image_name2]> <clickValue> <Opposite> [x_offset] [y_offset] [nth_match]")
        sys.exit(1)

    image_names = sys.argv[1]
    clickValue = sys.argv[2].lower() == 'true'
    Opposite = sys.argv[3].lower() == 'true'

    x_offset = None
    y_offset = None
    nth_match = 1

    remaining_args = sys.argv[4:]
    
    try:
        if len(remaining_args) == 1:
            nth_match = int(remaining_args[0])
        elif len(remaining_args) == 2:
            x_offset = int(remaining_args[0]) if remaining_args[0] else None
            y_offset = int(remaining_args[1]) if remaining_args[1] else None
        elif len(remaining_args) == 3:
            x_offset = int(remaining_args[0]) if remaining_args[0] else None
            y_offset = int(remaining_args[1]) if remaining_args[1] else None
            nth_match = int(remaining_args[2]) if remaining_args[2] else 1
    except ValueError as e:
        print(f"Invalid parameter values: {e}")
        sys.exit(1)

    return image_names, clickValue, Opposite, x_offset, y_offset, nth_match

if __name__ == '__main__':
    args = parse_args()
    detector = ScreenDetector(*args)
    
    try:
        if args[2]:  # Opposite
            detector.run2()
        else:
            detector.run1()
    finally:
        # 清理资源
        detector.templates.clear()
        del detector