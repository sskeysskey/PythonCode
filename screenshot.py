import os
import cv2
import sys
import time
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab
from typing import List, Tuple, Optional, Union # Union 添加进来

class ScreenDetector:
    def __init__(self, template_names: Union[str, List[str]],
                 clickValue: Optional[str] = None,
                 Opposite: bool = False,
                 scroll_on_not_found_run1: bool = False,
                 x_offset: Optional[int] = None,
                 y_offset: Optional[int] = None,
                 nth_match: int = 1,
                 timeout_seconds: int = 590): # 新增 timeout_seconds 参数
        self.templates = []
        # clickValue 现在可以是 'left', 'right', 或 None
        self.clickValue = clickValue
        self.Opposite = Opposite # 注意：Opposite 参数在 run1 和 run2 中似乎没有直接使用其布尔值来反转逻辑，而是用来选择 run1 还是 run2
        self.scroll_on_not_found_run1 = scroll_on_not_found_run1
        self.x_offset = x_offset
        self.y_offset = y_offset
        # 注意：下面的 "寻找最佳匹配" 逻辑优先于 nth_match。
        # 它将找到全局最佳的那个匹配项，这通常是第1个最理想的匹配。
        self.nth_match = max(1, nth_match)
        self.timeout_seconds = timeout_seconds # 存储超时时间

        if isinstance(template_names, str):
            self.template_name_list = [name.strip() for name in template_names.split(',')]
        else:
            self.template_name_list = template_names
        
        self._load_templates(self.template_name_list) # 使用 self.template_name_list

    def _load_templates(self, template_names_list: List[str]) -> None: # 参数名修改以更清晰
        """优化的模板加载方法"""
        for template_name in template_names_list:
            template_path = os.path.join('/Users/yanzhang/Documents/python_code/Resource', template_name)
            try:
                # 使用 with self._load_template(template_path) as template:
                # cv2.imread 返回的 numpy 数组不需要特别的资源释放，所以 contextmanager 可能不是必须的
                # 但如果未来 _load_template 做了更复杂的事情，它仍然有用
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
        # ImageGrab.grab() 已经是上下文管理器了，但这里显式使用 with 更好
        with ImageGrab.grab() as screenshot:
            # 直接转换为numpy数组并更改颜色空间
            return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    def find_images_on_screen(self, threshold: float = 0.95) -> Tuple[Optional[str], Optional[Tuple[int, int]], Optional[Tuple[int, int, int]]]:
        """
        在屏幕上查找所有模板，并返回匹配得分最高的那个。
        此方法能有效区分形状相似的图像。
        """
        screen = self.capture_screen() # 捕获一次屏幕用于所有模板的比较
        
        best_match_info = {
            "score": -1.0,  # 初始分数设为最低
            "name": None,
            "location": None,
            "shape": None
        }

        # 遍历每个模板，寻找各自在屏幕上的最佳匹配点
        for template_name, template in self.templates:
            if template is None: # 以防万一有模板加载失败但仍然在列表中
                continue

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            # minMaxLoc 会返回模板在屏幕上匹配得分最高和最低的位置及其得分
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # 如果当前模板的最佳匹配分数比我们记录的全局最高分还要高
            if max_val > best_match_info["score"]:
                best_match_info.update({
                    "score": max_val,
                    "name": template_name,
                    "location": max_loc,  # max_loc 是得分最高点的左上角坐标 (x, y)
                    "shape": template.shape
                })

        # 在检查完所有模板后，如果找到的最佳匹配分数满足阈值，则返回它
        if best_match_info["score"] >= threshold:
            print(f"找到最佳匹配: {best_match_info['name']}，分数为: {best_match_info['score']:.4f}")
            return best_match_info["name"], best_match_info["location"], best_match_info["shape"]
        
        # 如果所有模板的最高分都达不到阈值，则说明没找到
        return None, None, None

    def _perform_click(self, location: Tuple[int, int], shape: Tuple[int, int, int]) -> None:
        """优化的点击操作，支持左键和右键"""
        # 注意：pyautogui 的坐标通常是屏幕的绝对坐标。
        # matchTemplate 返回的 (x,y) 是模板左上角在屏幕截图中的位置。
        # ImageGrab.grab() 捕获的是主屏幕。如果有多显示器，可能需要调整。
        # 中心点计算应该是相对于模板的，然后加上模板的左上角坐标。
        # location[0] is x, location[1] is y
        # shape[1] is width, shape[0] is height

        # pyautogui 使用的是屏幕的1:1像素坐标，而不是像某些高DPI环境下的缩放坐标
        # 因此，这里计算的 center_x, center_y 应该是准确的屏幕像素坐标
        center_x = (location[0] + shape[1] // 2) // 2
        center_y = (location[1] + shape[0] // 2) // 2
        
        if self.x_offset is not None:
            center_x += self.x_offset
        if self.y_offset is not None:
            center_y += self.y_offset

        if self.clickValue == "left":
            pyautogui.click(center_x, center_y, button='left')
            print(f"执行左键点击于: ({center_x}, {center_y})")
        elif self.clickValue == "right":
            pyautogui.click(center_x, center_y, button='right')
            print(f"执行右键点击于: ({center_x}, {center_y})")
        # 如果 self.clickValue 为 None，则此方法不应被调用（由 run1 中的 if self.clickValue 控制）


    def run1(self) -> str:
        # 使用 self.timeout_seconds 而不是硬编码的 590
        timeout = time.time() + self.timeout_seconds
        
        while time.time() < timeout:
            # 建议为 "最佳匹配" 逻辑使用一个较高的阈值
            template_name, location, shape = self.find_images_on_screen(threshold=0.9)
            
            if location and template_name and shape: #确保所有值都有效
                if self.clickValue:
                    self._perform_click(location, shape)
                print(f"找到图片 {template_name} 位置: {location}")
                if len(self.template_name_list) > 1:
                    print(f"FOUND_IMAGE:{template_name}")
                return template_name # 返回找到的第一个符合 nth_match 条件的模板名         
            else:
                if self.scroll_on_not_found_run1:
                    print("在 run1 中未找到图片，执行滚动操作 pyautogui.scroll(-120)")
                    pyautogui.scroll(-120)
                    sleep(0.5)
            sleep(1)
        
        # 返回 "TIMEOUT" 字符串，以便 AppleScript 可以检查
        print(f"在 {self.timeout_seconds} 秒内未找到图片，退出程序。")
        return "TIMEOUT"

    def run2(self) -> None:
        """优化的运行方法2 - 持续查找并滚动，直到找不到"""
        while True:
            template_name, location, shape = self.find_images_on_screen(threshold=0.95)
            
            if not location: # 如果没找到 (或者 template_name/shape 为 None)
                print("未找到图片，停止滚动并退出run2。")
                break # 退出 while 循环
            
            # 如果找到了，则执行滚动
            # 注意：如果 clickValue 为 True，这里不会自动点击，run2 似乎只负责滚动
            # 如果希望 run2 也点击，需要添加 self._perform_click 调用
            pyautogui.scroll(-120) # 向下滚动
            print(f"找到图片 {template_name} 位置: {location}，已滚动。")
            sleep(1) # 操作后稍作等待

def parse_args() -> Tuple[Union[str, List[str]], Optional[str], bool, bool, Optional[int], Optional[int], int, int]:
    """参数解析函数"""
    # 参数顺序: image_names, click_type, Opposite, [scroll_in_run1], [x_offset], [y_offset], [nth_match]
    # 返回元组中新增了 int 用于 timeout
    if len(sys.argv) < 4: # image_names, click_type, Opposite 是必需的
        print("用法: python a.py <image_name1[,image_name2,...]> <click_type:true|false|right> <Opposite:true|false> [scroll_in_run1:true|false] [x_offset] [y_offset] [nth_match] [timeout]")
        print("  click_type:")
        print("    true: 左键点击")
        print("    false: 不点击")
        print("    right: 右键点击")
        print("  Opposite:")
        print("    true: 执行 run2 (持续查找并滚动)")
        print("    false: 执行 run1 (查找，可选超时前滚动)")
        print("  scroll_in_run1 (可选, 默认为 false):")
        print("    true: 在 run1 中若找不到图片则向下滚动后重试")
        print("    false: 在 run1 中若找不到图片则不滚动，仅在当前屏幕重试")
        sys.exit(1)

    image_names_str = sys.argv[1]
    # 支持单个或多个逗号分隔的图片名
    # image_names = [name.strip() for name in image_names_str.split(',')] if ',' in image_names_str else image_names_str

    click_arg = sys.argv[2].lower()
    clickValue: Optional[str] = None # 默认为不点击
    if click_arg == 'true':
        clickValue = 'left'
    elif click_arg == 'right':
        clickValue = 'right'
    elif click_arg == 'false':
        clickValue = None # 明确设置为 None
    else:
        print(f"错误: 无效的 click_type '{sys.argv[2]}'. 请使用 'true', 'false', 或 'right'.")
        sys.exit(1)

    Opposite = sys.argv[3].lower() == 'true'
    
    # --- 修改开始: 使 scroll_in_run1 可选 ---
    scroll_in_run1: bool = False # 默认值为 false
    current_arg_index = 4 # 指向 scroll_in_run1 或 x_offset 的潜在位置

    if len(sys.argv) > current_arg_index: # 检查是否有足够的参数作为 scroll_in_run1 或后续参数
        potential_scroll_arg = sys.argv[current_arg_index].lower()
        if potential_scroll_arg in ['true', 'false']:
            scroll_in_run1 = potential_scroll_arg == 'true'
            current_arg_index += 1 # scroll_in_run1 已被处理，下一个可选参数索引增加
        # else: potential_scroll_arg 不是 true/false，则它可能是 x_offset 等，
        # scroll_in_run1 保持默认的 false，current_arg_index 不变
    
    # --- 处理 x_offset, y_offset, nth_match ---
    x_offset: Optional[int] = None
    y_offset: Optional[int] = None
    nth_match: int = 1 # 默认值

    timeout_seconds: int = 590 # 默认超时时间
    # final_optional_args 包含 scroll_in_run1 之后的所有参数
    
    final_optional_args = sys.argv[current_arg_index:]

    try:
        if len(final_optional_args) >= 4:
            if final_optional_args[0]: x_offset = int(final_optional_args[0])
            if final_optional_args[1]: y_offset = int(final_optional_args[1])
            if final_optional_args[2]: nth_match = int(final_optional_args[2])
            if final_optional_args[3]: timeout_seconds = int(final_optional_args[3])
        elif len(final_optional_args) == 3:
            if final_optional_args[0]: x_offset = int(final_optional_args[0])
            if final_optional_args[1]: y_offset = int(final_optional_args[1])
            if final_optional_args[2]: nth_match = int(final_optional_args[2])
        elif len(final_optional_args) == 2:
            if final_optional_args[0]: x_offset = int(final_optional_args[0])
            if final_optional_args[1]: y_offset = int(final_optional_args[1])
        elif len(final_optional_args) == 1:
            if final_optional_args[0]: nth_match = int(final_optional_args[0])
    except (ValueError, IndexError):
        pass

    return image_names_str, clickValue, Opposite, scroll_in_run1, x_offset, y_offset, nth_match, timeout_seconds

if __name__ == '__main__':
    args_tuple = parse_args() # (image_names_str, clickValue, Opposite, x_offset, y_offset, nth_match, timeout)
    
    # print(f"Parsed args: {args_tuple}") # 调试用

    # 创建 ScreenDetector 实例
    detector = ScreenDetector(
        template_names=args_tuple[0],
        clickValue=args_tuple[1], # 现在是 'left', 'right', 或 None
        Opposite=args_tuple[2], # 这个参数主要用于选择 run1 还是 run2
        scroll_on_not_found_run1=args_tuple[3],
        x_offset=args_tuple[4],
        y_offset=args_tuple[5],
        nth_match=args_tuple[6],
        timeout_seconds=args_tuple[7] # 将解析出的 timeout 传递给类
    )
    
    try:
        if args_tuple[2]:  # Opposite is True, run run2
            detector.run2()
        else: # Opposite is False, run run1
            result = detector.run1()
            # 打印结果，这样 AppleScript 的 "do shell script" 才能捕获到
            print(result) 
    finally:
        # 清理模板列表中的图像数据（如果需要手动管理，但cv2图像通常由GC处理）
        # self.templates.clear() 实际上不需要，因为 detector 实例会被销毁
        # del detector # 也不需要显式删除
        print("程序执行完毕。")