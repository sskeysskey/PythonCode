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
def find_image_on_screen(template, screen=None, threshold=0.9):
    """
    在屏幕上查找图片
    新增 screen 参数：如果传入了截屏数据，则直接使用，避免重复截屏提高效率
    返回: (max_loc, shape) 或 (None, None)
    """
    if screen is None:
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

def is_refusal_response(text: str) -> bool:
    """
    判断 qianwen 是否返回了拒答/无法处理内容。
    命中后应直接跳过当前文章，而不是继续重试。
    """
    if not text:
        return False

    normalized = re.sub(r'\s+', '', text)

    refusal_phrases = [
        "抱歉，我无法回答这个问题，我们聊聊别的吧",
        "抱歉，我无法回答这个问题",
        "我们聊聊别的吧",
        "无法回答这个问题",
        "不能回答这个问题",
        "无法协助处理该请求",
        "我无法协助完成该请求",
        "我不能协助完成该请求",
        "该内容无法处理",
        "很抱歉，我不能",
        "很抱歉，我无法",
    ]

    return any(phrase in normalized for phrase in refusal_phrases)

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

def refresh_page_mac():
    """
    使用 AppleScript 模拟 Command + R 刷新页面
    """
    apple_script = """
    osascript -e 'tell application "System Events" to key code 15 using command down'
    """
    os.system(apple_script)

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

    # ==== 1. 加载所有模板 ====
    template_copy_path = os.path.join(BASE_RESOURCE_DIR, "qianwen_copy.png")
    template_forbidden_path = os.path.join(BASE_RESOURCE_DIR, "qianwen_forbidden.png")
    template_forbidden2_path = os.path.join(BASE_RESOURCE_DIR, "qianwen_forbidden2.png")
    template_retry_path = os.path.join(BASE_RESOURCE_DIR, "qianwen_retry.png")
    template_timeout_path = os.path.join(BASE_RESOURCE_DIR, "qianwen_timeout.png")
    
    # 检查所有必需的模板文件是否存在
    required_templates = [
        ("copy", template_copy_path),
        ("forbidden", template_forbidden_path),
        ("forbidden2", template_forbidden2_path),
        ("retry", template_retry_path),
        ("timeout", template_timeout_path)
    ]
    
    for name, path in required_templates:
        if not os.path.exists(path):
            print(f"错误：找不到模板文件 {path}")
            sys.exit(3) # 模板缺失错误
    
    template_copy = cv2.imread(template_copy_path, cv2.IMREAD_COLOR)
    template_forbidden = cv2.imread(template_forbidden_path, cv2.IMREAD_COLOR)
    template_forbidden2 = cv2.imread(template_forbidden2_path, cv2.IMREAD_COLOR)
    template_retry = cv2.imread(template_retry_path, cv2.IMREAD_COLOR)
    template_timeout = cv2.imread(template_timeout_path, cv2.IMREAD_COLOR)
    
    max_attempts = 3
    current_attempt = 1
    timeout_duration = 120 
    start_time = time.time()
    
    print(f"开始监控内容（最多尝试3次，汉字阈值：{target_threshold}）...")
    
    while current_attempt <= max_attempts:
        # 检查总时间是否超时
        if time.time() - start_time > timeout_duration:
            print("寻找超时：未能在规定时间内完成任务")
            sys.exit(2) # 状态码 2：超时退出
            
        # 截取当前屏幕，供后续所有模板共用，提高匹配效率
        current_screen = capture_screen()
        
        # 1. 优先寻找 Forbidden / Forbidden2 按钮（任意一个匹配都触发拒答）
        forbidden_loc, _ = find_image_on_screen(template_forbidden, screen=current_screen)
        forbidden2_loc, _ = find_image_on_screen(template_forbidden2, screen=current_screen)

        if forbidden_loc or forbidden2_loc:
            found_name = "qianwen_forbidden" if forbidden_loc else "qianwen_forbidden2"
            print(f"检测到 {found_name} 图片，触发拒答机制，跳过当前文章。")
            sys.exit(4)
            
        # 2. 寻找 Retry 和 Timeout 按钮
        retry_loc, _ = find_image_on_screen(template_retry, screen=current_screen)
        timeout_loc, _ = find_image_on_screen(template_timeout, screen=current_screen)
        
        if retry_loc or timeout_loc:
            matched_name = "retry" if retry_loc else "timeout"
            print(f"检测到 {matched_name} 图片，等待 15 秒后刷新页面...")
            sleep(15)
            print("执行 Command + R 刷新页面...")
            refresh_page_mac()
            
            # 刷新后等待几秒钟让页面加载，然后再继续下一轮寻找
            sleep(5) 
            # 注意：这里使用 continue 跳过本次循环，重新开始截图并寻找。
            # 刷新页面不算作 current_attempt 的消耗。
            continue
            
        # 3. 寻找 Copy 按钮 (触发条件)
        location, shape = find_image_on_screen(template_copy, screen=current_screen)
        
        if location:
            print("初步定位到 Copy 按钮，等待 1 秒以确保 UI 稳定...")
            sleep(1) # 等待 1 秒
            
            # 再次寻找，获取最新的坐标 (这里不传 current_screen，因为需要获取 1 秒后的最新屏幕状态)
            new_location, new_shape = find_image_on_screen(template_copy)
            
            # 如果第二次没找到（可能页面刷新了），则跳过本次循环继续找
            if not new_location:
                print("等待后未找到按钮，继续寻找...")
                continue
                
            print(f"确认定位到 Copy 按钮，准备点击 (原位置: {location}, 新位置: {new_location})...")
            
            # 执行点击（使用最新的坐标和形状）
            lx, ly = perform_click(new_location, new_shape)
            print(f"第 {current_attempt} 次尝试 - 点击按钮: {lx}, {ly}")
            
            # 校验内容
            sleep(0.5) 
            content = pyperclip.paste()

            # 先判断是否是 qianwen 拒答文本
            if is_refusal_response(content):
                print("检测到 qianwen 拒答内容，跳过当前文章。")
                sys.exit(4)
            
            if is_content_qualified(content, min_chinese=target_threshold):
                print(f"第 {current_attempt} 次尝试成功：内容校验通过。")
                sys.exit(0)
            else:
                print(f"第 {current_attempt} 次尝试失败：内容不合格。")
                current_attempt += 1
                if current_attempt <= max_attempts:
                    print("内容不合格，移动光标到 (709, 749) 并向下滚屏...")
                    pyautogui.moveTo(709, 749)
                    pyautogui.scroll(SCROLL_AMOUNT)
                    sleep(1)
                else:
                    print("已达到最大尝试次数，内容均不合格。")
                    sys.exit(1)
        else:
            # 没找到 Copy、Retry、Timeout 也没有 Forbidden 按钮，滚动屏幕继续寻找
            pyautogui.scroll(SCROLL_AMOUNT)
            sleep(1)
            
    sys.exit(1)

if __name__ == '__main__':
    main()