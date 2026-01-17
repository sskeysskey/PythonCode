import os
import cv2
import sys
import time
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab
from typing import List, Tuple, Optional, Union

# ================= 配置区域 =================

# 1. 动态获取当前用户的主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义资源目录
# 假设资源文件夹结构是: ~/Coding/python_code/Resource
# 如果在 Windows 上路径不同，请在这里修改
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")

# ===========================================

class ScreenDetector:
    def __init__(self, template_names: Union[str, List[str]],
                 clickValue: Optional[str] = None,
                 Opposite: bool = False,
                 scroll_on_not_found_run1: bool = False,
                 x_offset: Optional[int] = None,
                 y_offset: Optional[int] = None,
                 nth_match: int = 1,
                 timeout_seconds: int = 590):
        self.templates = []
        self.clickValue = clickValue
        self.Opposite = Opposite
        self.scroll_on_not_found_run1 = scroll_on_not_found_run1
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.nth_match = max(1, nth_match)
        self.timeout_seconds = timeout_seconds

        if isinstance(template_names, str):
            self.template_name_list = [name.strip() for name in template_names.split(',')]
        else:
            self.template_name_list = template_names
        
        # <--- 新增：计算屏幕缩放因子 (用于处理 Mac Retina 2x 问题)
        self.scale_factor = self._get_scale_factor()
        print(f"检测到屏幕缩放因子: {self.scale_factor}")

        self._load_templates(self.template_name_list)

    def _get_scale_factor(self) -> float:
        """
        计算 ImageGrab (物理像素) 和 pyautogui (逻辑坐标) 之间的缩放比例。
        在 Mac Retina 屏上通常是 2.0，在普通 Windows 屏上通常是 1.0。
        """
        try:
            # 获取屏幕截图的宽度
            with ImageGrab.grab() as sc:
                img_width = sc.size[0]
            
            # 获取 pyautogui 认为的屏幕宽度
            screen_width, _ = pyautogui.size()
            
            return img_width / screen_width
        except Exception as e:
            print(f"警告: 无法计算屏幕缩放因子，默认为 1.0。错误: {e}")
            return 1.0

    def _load_templates(self, template_names_list: List[str]) -> None:
        """优化的模板加载方法"""
        for template_name in template_names_list:
            # <--- 修改：使用动态路径
            template_path = os.path.join(BASE_RESOURCE_DIR, template_name)
            try:
                # <--- 新增：检查文件是否存在，避免 cv2.imread 静默失败
                if not os.path.exists(template_path):
                    print(f"错误: 模板文件不存在: {template_path}")
                    continue

                template_img = cv2.imread(template_path, cv2.IMREAD_COLOR)
                if template_img is None:
                    print(f"警告: 模板图片未能正确读取于路径 {template_path}")
                    continue
                self.templates.append((template_name, template_img))
            except Exception as e:
                print(f"An unexpected error occurred while loading template {template_name}: {e}")
                continue

    def capture_screen(self) -> np.ndarray:
        """优化的屏幕捕获方法"""
        with ImageGrab.grab() as screenshot:
            # 转换为 numpy 数组 (BGR 格式用于 OpenCV)
            img_np = np.array(screenshot)
            # 处理部分系统截图带 Alpha 通道的情况 (RGBA -> BGR)
            if img_np.shape[2] == 4:
                return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

    def find_images_on_screen(self, threshold: float = 0.95) -> Tuple[Optional[str], Optional[Tuple[int, int]], Optional[Tuple[int, int, int]]]:
        """
        在屏幕上查找所有模板，并返回匹配得分最高的那个。
        """
        screen = self.capture_screen()
        
        best_match_info = {
            "score": -1.0,
            "name": None,
            "location": None,
            "shape": None
        }

        for template_name, template in self.templates:
            if template is None:
                continue
            
            # 确保模板尺寸不大于屏幕尺寸，否则 cv2.matchTemplate 会报错
            if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
                print(f"警告: 模板 {template_name} 尺寸 {template.shape} 大于屏幕截图 {screen.shape}，跳过。")
                continue

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if max_val > best_match_info["score"]:
                best_match_info.update({
                    "score": max_val,
                    "name": template_name,
                    "location": max_loc,
                    "shape": template.shape
                })

        if best_match_info["score"] >= threshold:
            print(f"找到最佳匹配: {best_match_info['name']}，分数为: {best_match_info['score']:.4f}")
            return best_match_info["name"], best_match_info["location"], best_match_info["shape"]
        
        return None, None, None

    def _perform_click(self, location: Tuple[int, int], shape: Tuple[int, int, int]) -> None:
        """
        优化的点击操作，自动处理 Retina 缩放。
        location: (x, y) - 这是基于 ImageGrab 截图（物理像素）的坐标
        shape: (h, w, c) - 模板的物理像素尺寸
        """
        # 1. 计算物理像素坐标系的中心点
        phys_center_x = location[0] + shape[1] // 2
        phys_center_y = location[1] + shape[0] // 2
        
        # 2. <--- 关键修改：转换为逻辑坐标 (pyautogui 使用的坐标)
        # 比如 Retina 屏 scale_factor=2，物理坐标 200 对应逻辑坐标 100
        logic_center_x = int(phys_center_x / self.scale_factor)
        logic_center_y = int(phys_center_y / self.scale_factor)

        # 3. 应用偏移量 (偏移量通常由用户指定，假设用户想的是逻辑偏移量)
        if self.x_offset is not None:
            logic_center_x += self.x_offset
        if self.y_offset is not None:
            logic_center_y += self.y_offset

        # 4. 执行点击
        try:
            if self.clickValue == "left":
                pyautogui.click(logic_center_x, logic_center_y, button='left')
                print(f"执行左键点击于: ({logic_center_x}, {logic_center_y}) [物理: ({phys_center_x}, {phys_center_y})]")
            elif self.clickValue == "right":
                pyautogui.click(logic_center_x, logic_center_y, button='right')
                print(f"执行右键点击于: ({logic_center_x}, {logic_center_y}) [物理: ({phys_center_x}, {phys_center_y})]")
        except pyautogui.FailSafeException:
            print("错误: 触发了 PyAutoGUI 的故障安全机制 (鼠标移到了角落)。")
        except Exception as e:
            print(f"点击操作失败: {e}")

    def run1(self) -> str:
        timeout = time.time() + self.timeout_seconds
        
        while time.time() < timeout:
            template_name, location, shape = self.find_images_on_screen(threshold=0.9)
            
            if location and template_name and shape:
                if self.clickValue:
                    self._perform_click(location, shape)
                print(f"找到图片 {template_name} 位置: {location}")
                if len(self.template_name_list) > 1:
                    print(f"FOUND_IMAGE:{template_name}")
                return template_name      
            else:
                if self.scroll_on_not_found_run1:
                    print("在 run1 中未找到图片，执行滚动操作 pyautogui.scroll(-120)")
                    pyautogui.scroll(-120)
                    sleep(0.5)
            sleep(1)
        
        print(f"在 {self.timeout_seconds} 秒内未找到图片，退出程序。")
        return "TIMEOUT"

    def run2(self) -> None:
        """优化的运行方法2 - 持续查找并滚动，直到找不到"""
        while True:
            template_name, location, shape = self.find_images_on_screen(threshold=0.95)
            
            if not location:
                print("未找到图片，停止滚动并退出run2。")
                break
            
            # <--- 注意：run2 原逻辑不含点击，如果需要点击请取消注释下面这行
            # if self.clickValue: self._perform_click(location, shape)

            pyautogui.scroll(-120)
            print(f"找到图片 {template_name} 位置: {location}，已滚动。")
            sleep(1)

def parse_args() -> Tuple[Union[str, List[str]], Optional[str], bool, bool, Optional[int], Optional[int], int, int]:
    """参数解析函数"""
    if len(sys.argv) < 4:
        print("用法: python a.py <image_name1[,image_name2...]> <click_type> <Opposite> [scroll] [x] [y] [nth] [timeout]")
        sys.exit(1)

    image_names_str = sys.argv[1]
    
    click_arg = sys.argv[2].lower()
    clickValue: Optional[str] = None
    if click_arg == 'true':
        clickValue = 'left'
    elif click_arg == 'right':
        clickValue = 'right'
    elif click_arg == 'false':
        clickValue = None
    else:
        print(f"错误: 无效的 click_type '{sys.argv[2]}'.")
        sys.exit(1)

    Opposite = sys.argv[3].lower() == 'true'
    
    scroll_in_run1: bool = False
    current_arg_index = 4
    if len(sys.argv) > current_arg_index:
        potential_scroll_arg = sys.argv[current_arg_index].lower()
        if potential_scroll_arg in ['true', 'false']:
            scroll_in_run1 = potential_scroll_arg == 'true'
            current_arg_index += 1
    
    x_offset: Optional[int] = None
    y_offset: Optional[int] = None
    nth_match: int = 1
    timeout_seconds: int = 590
    
    final_optional_args = sys.argv[current_arg_index:]
    try:
        # 这里使用更灵活的解析方式，依次填充非空参数
        if len(final_optional_args) >= 1: x_offset = int(final_optional_args[0])
        if len(final_optional_args) >= 2: y_offset = int(final_optional_args[1])
        if len(final_optional_args) >= 3: nth_match = int(final_optional_args[2])
        if len(final_optional_args) >= 4: timeout_seconds = int(final_optional_args[3])
    except (ValueError, IndexError):
        pass

    return image_names_str, clickValue, Opposite, scroll_in_run1, x_offset, y_offset, nth_match, timeout_seconds

if __name__ == '__main__':
    args_tuple = parse_args()
    
    detector = ScreenDetector(
        template_names=args_tuple[0],
        clickValue=args_tuple[1],
        Opposite=args_tuple[2],
        scroll_on_not_found_run1=args_tuple[3],
        x_offset=args_tuple[4],
        y_offset=args_tuple[5],
        nth_match=args_tuple[6],
        timeout_seconds=args_tuple[7]
    )
    
    try:
        if args_tuple[2]:  # Opposite is True, run run2
            detector.run2()
        else: # Opposite is False, run run1
            result = detector.run1()
            print(result) 
    finally:
        print("程序执行完毕。")
