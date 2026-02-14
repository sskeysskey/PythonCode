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
    """
    在屏幕上查找图片
    返回: (max_loc, shape) 或 (None, None)
    """
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

def is_content_qualified(text, min_chinese=50):
    """校验内容是否包含足够多的中文"""
    if not text:
        return False
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return len(chinese_chars) > min_chinese

def perform_click(location, shape):
    """
    封装点击逻辑，根据位置和形状计算中心点并点击
    """
    phys_center_x = location[0] + shape[1] // 2
    phys_center_y = location[1] + shape[0] // 2
    
    # 转换为逻辑坐标
    logic_center_x = int(phys_center_x / SCALE_FACTOR)
    logic_center_y = int(phys_center_y / SCALE_FACTOR)
    
    pyautogui.click(logic_center_x, logic_center_y)
    return logic_center_x, logic_center_y

def main():
    # ==== 新增：获取命令行参数 ====
    # 默认阈值为 50
    target_threshold = 50
    
    # 如果运行脚本时带了参数（例如 python3 Doubao_auto.py 50），则使用传入的数字
    if len(sys.argv) > 1:
        try:
            target_threshold = int(sys.argv[1])
            print(f"接收到自定义汉字阈值: {target_threshold}")
        except ValueError:
            print("参数格式错误，使用默认阈值 50")

    # ==== 1. 加载 Copy 模板 ====
    template_path = os.path.join(BASE_RESOURCE_DIR, "doubao_copy.png")
    if not os.path.exists(template_path):
        print(f"错误：找不到模板文件 {template_path}")
        sys.exit(3) # 模板缺失错误
    
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    
    # ==== 2. 新增：加载 Related 模板 ====
    related_path = os.path.join(BASE_RESOURCE_DIR, "doubao_related.png")
    if not os.path.exists(related_path):
        print(f"错误：找不到关联模板文件 {related_path}")
        sys.exit(3)
    related_template = cv2.imread(related_path, cv2.IMREAD_COLOR)
    
    max_attempts = 3
    current_attempt = 1
    timeout_duration = 120 
    start_time = time.time()
    
    print(f"开始监控豆包内容（最多尝试3次，汉字阈值：{target_threshold}）...")
    
    while current_attempt <= max_attempts:
        # 检查总时间是否超时
        if time.time() - start_time > timeout_duration:
            print("寻找超时：未能在规定时间内找到复制按钮")
            sys.exit(2) # 状态码 2：超时退出
            
        # 1. 初次寻找 Copy 按钮 (仅作为触发条件)
        location, shape = find_image_on_screen(template)
        
        if location:
            print("初次定位到 Copy 按钮，开始检测 Related 标识...")
            
            # ==== 2. 寻找 Related 图片 (最多4秒) ====
            check_start_time = time.time()
            found_related = False
            
            # 4秒内循环查找 related 图片
            while time.time() - check_start_time < 4:
                rel_loc, _ = find_image_on_screen(related_template, threshold=0.8) # 阈值可微调
                if rel_loc:
                    print("检测到 Related 标识 (布局已变化)，立即进行下一步。")
                    found_related = True
                    break # 找到了就立刻跳出循环，不再空等
                sleep(0.5) 
            
            if not found_related:
                print("4秒内未检测到 Related 标识 (超时)，准备重新定位 Copy。")

            # ==== 3. 无论是否找到 Related，都必须重新定位 Copy 按钮 ====
            # 原因：Related 的出现会挤压布局；即使没出现，4秒的时间差也可能导致页面微动。
            final_loc, final_shape = find_image_on_screen(template)
            
            if final_loc:
                # 执行点击
                lx, ly = perform_click(final_loc, final_shape)
                print(f"第 {current_attempt} 次尝试 - 点击重新定位后的按钮: {lx}, {ly}")
                
                # 校验内容
                sleep(0.5) 
                content = pyperclip.paste()
                
                if is_content_qualified(content, min_chinese=target_threshold):
                    print(f"第 {current_attempt} 次尝试成功：内容校验通过。")
                    sys.exit(0)
                else:
                    print(f"第 {current_attempt} 次尝试失败：内容不合格。")
                    current_attempt += 1
                    if current_attempt <= max_attempts:
                        pyautogui.scroll(SCROLL_AMOUNT)
                        sleep(1)
                    else:
                        print("已达到最大尝试次数，内容均不合格。")
                        sys.exit(1)
            else:
                # 如果等待4秒后，Copy按钮竟然找不到了（比如被挤出屏幕了）
                print("错误：等待后无法重新定位 Copy 按钮，尝试滚动屏幕...")
                pyautogui.scroll(SCROLL_AMOUNT)
                sleep(1)
                # 这里不增加 attempt 次数，因为并没有实际点击，只是定位失败
                continue 
        else:
            # 连最初的 Copy 按钮都没找到
            pyautogui.scroll(SCROLL_AMOUNT)
            sleep(1)
            
    sys.exit(1)

if __name__ == '__main__':
    main()