import os
import cv2
import time
import pyautogui
import numpy as np
import sys
import pyperclip  # 新增：用于读取剪贴板
import re         # 新增：用于正则匹配汉字
from PIL import ImageGrab
from time import sleep

# ================= 配置区域 =================
USER_HOME = os.path.expanduser("~")
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")
SCROLL_AMOUNT = -120 # 稍微加大滚动幅度，确保跳过已检查的按钮

def get_scale_factor():
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
    except Exception:
        # 如果获取失败，默认假设没有缩放
        return 1.0

# 全局计算缩放因子，避免每次点击都重复计算
SCALE_FACTOR = get_scale_factor()
print(f"检测到屏幕缩放因子: {SCALE_FACTOR}")

def capture_screen():
    # 使用PIL的ImageGrab直接截取屏幕
    with ImageGrab.grab() as screenshot:
        img_np = np.array(screenshot)
        # 处理 RGBA (例如某些 Mac/Linux 截图包含 Alpha 通道)
        if img_np.shape[2] == 4:
            return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        # 将截图对象转换为OpenCV格式 (RGB -> BGR)
        return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

# 查找图片
def find_image_on_screen(template, threshold=0.9):
    screen = capture_screen()
    
    # 简单的尺寸校验，防止模板比屏幕还大导致报错
    if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
        return None, None
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        return max_loc, template.shape
    else:
        return None, None

def is_content_qualified(text, min_chinese=10):
    """校验内容是否包含足够多的中文"""
    if not text:
        return False
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return len(chinese_chars) > min_chinese

def main():
    template_path = os.path.join(BASE_RESOURCE_DIR, "doubao_copy.png")
    if not os.path.exists(template_path):
        print(f"错误：找不到模板文件 {template_path}")
        sys.exit(3) # 模板缺失错误
    
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    
    max_attempts = 3
    current_attempt = 1
    timeout_duration = 120 
    start_time = time.time()
    
    print("开始监控豆包内容（最多尝试3次）...")
    
    while current_attempt <= max_attempts:
        # 检查总时间是否超时
        if time.time() - start_time > timeout_duration:
            print("寻找超时：未能在规定时间内找到复制按钮")
            sys.exit(2) # 状态码 2：超时退出
            
        location, shape = find_image_on_screen(template)
        
        if location:
            # 1. 点击按钮
            phys_center_x = location[0] + shape[1] // 2
            phys_center_y = location[1] + shape[0] // 2
            
            # 转换为逻辑坐标 (除以缩放因子)
            logic_center_x = int(phys_center_x / SCALE_FACTOR)
            logic_center_y = int(phys_center_y / SCALE_FACTOR)
            
            pyautogui.click(logic_center_x, logic_center_y)
            print(f"第 {current_attempt} 次尝试 - 点击按钮: {logic_center_x}, {logic_center_y}")
            
            # 2. 校验内容
            sleep(0.5) # 给剪贴板一点反应时间
            content = pyperclip.paste()
            
            if is_content_qualified(content):
                print(f"第 {current_attempt} 次尝试成功：内容校验通过。")
                sys.exit(0) # 状态码 0：成功退出
            else:
                print(f"第 {current_attempt} 次尝试失败：内容不合格。")
                current_attempt += 1
                if current_attempt <= max_attempts:
                    # 向上或向下滚动一下，试图寻找另一个（上一个）复制按钮
                    pyautogui.scroll(SCROLL_AMOUNT)
                    sleep(1)
                else:
                    # 已经试了3次都不行
                    print("已达到最大尝试次数，内容均不合格。")
                    sys.exit(1) # 状态码 1：内容错误退出
        else:
            # 没找到按钮，继续滚动寻找
            pyautogui.scroll(SCROLL_AMOUNT)
            sleep(1)

    sys.exit(1)

if __name__ == '__main__':
    main()