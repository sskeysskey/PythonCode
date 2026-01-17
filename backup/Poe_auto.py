import cv2
import time
import argparse
import pyautogui
import subprocess
import numpy as np
import sys
import os
import platform # <--- 新增
from PIL import ImageGrab

# ================= 配置区域 (跨平台修改) =================

# 1. 动态获取主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义资源目录
# 假设资源文件夹结构是: ~/Coding/python_code/Resource
# 如果在 Windows 上路径不同，请在这里修改
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")

# 3. 固定点击坐标与滚动值
# 注意：这些坐标通常是基于特定分辨率和UI布局的。
# 换了电脑或屏幕分辨率，这些硬编码的坐标可能需要重新校准。
SCREEN_CLICK_COORDS = (355, 545)
SECONDARY_CLICK_COORDS = (618, 458)

# 滚动值调整
# Mac 上 scroll(-80) 可能是向下，Windows 上 scroll(-80) 也是向下
# 但单位可能不同，这里保持默认，如有需要可针对系统做 if platform.system() == 'Windows' 的微调
SCROLL_AMOUNT = -80
SCROLL_AMOUNT_LARGE = -120

# ========================================================

def get_scale_factor():
    """
    计算 ImageGrab (物理像素) 和 pyautogui (逻辑坐标) 之间的缩放比例。
    在 Mac Retina 屏上通常是 2.0，在普通 Windows 屏上通常是 1.0。
    """
    try:
        with ImageGrab.grab() as sc:
            img_width = sc.size[0]
        screen_width, _ = pyautogui.size()
        return img_width / screen_width
    except Exception:
        return 1.0

# 全局计算一次缩放因子
SCALE_FACTOR = get_scale_factor()
print(f"检测到屏幕缩放因子: {SCALE_FACTOR}")

def capture_screen():
    """
    使用PIL的ImageGrab直接截取屏幕，并转换为OpenCV格式
    """
    with ImageGrab.grab() as screenshot:
        # 转换为 numpy 数组
        img_np = np.array(screenshot)
        # 处理 RGBA
        if img_np.shape[2] == 4:
            return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

def find_image_on_screen(template, threshold=0.95):
    """
    在当前屏幕中查找给定模板图像的匹配位置（精度默认0.95）。
    如果找到，则返回 (top_left坐标, 模板形状)，否则返回 (None, None)。
    """
    screen = capture_screen()
    
    # 防御性检查：如果模板比屏幕还大，直接跳过
    if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
        print("警告：模板尺寸大于屏幕尺寸，跳过匹配。")
        return None, None

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    
    del screen
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None

def refresh_page():
    """
    跨平台刷新页面操作
    """
    if platform.system() == 'Darwin':
        # macOS: 使用 AppleScript 发送 Cmd+R
        script = """
        tell application "System Events"
            key code 15 using command down
        end tell
        """
        try:
            subprocess.run(['osascript', '-e', script], check=True)
        except Exception as e:
            print(f"AppleScript 刷新失败: {e}")
            # 备选方案: 使用 pyautogui
            # pyautogui.hotkey('command', 'r')
    else:
        # Windows/Linux: 使用 F5 或 Ctrl+R
        print("执行 Windows/Linux 页面刷新 (F5)")
        pyautogui.press('f5')
        # 或者使用 pyautogui.hotkey('ctrl', 'r')

    # 给系统一点时间来完成操作
    time.sleep(0.5)

def click_retry_and_refresh():
    """
    找到retry图片后，点击固定坐标并执行页面刷新
    """
    print("找到poe_retry图片，执行页面刷新操作...")
    pyautogui.click(*SCREEN_CLICK_COORDS)
    time.sleep(0.5)
    refresh_page()

def to_logic_coords(phys_x, phys_y):
    """
    将物理像素坐标转换为逻辑坐标
    """
    return int(phys_x / SCALE_FACTOR), int(phys_y / SCALE_FACTOR)

def click_image_center(location, shape, button='left', offset_x=0, offset_y=0, move_only=False):
    """
    辅助函数：点击图片的中心位置，自动处理缩放
    """
    # 计算物理中心
    phys_center_x = location[0] + shape[1] // 2
    phys_center_y = location[1] + shape[0] // 2
    
    # 转换为逻辑中心
    logic_x, logic_y = to_logic_coords(phys_center_x, phys_center_y)
    
    # 应用偏移
    target_x = logic_x + offset_x
    target_y = logic_y + offset_y
    
    if move_only:
        pyautogui.moveTo(target_x, target_y)
    else:
        # 如果是移动并点击
        if offset_x != 0 or offset_y != 0:
            pyautogui.moveTo(target_x, target_y)
        pyautogui.click(target_x, target_y, button=button)

def main(mode):
    # 定义模板路径字典 (使用 os.path.join)
    template_paths = {
        "success": os.path.join(BASE_RESOURCE_DIR, "poe_copy_success.png"),
        "compare": os.path.join(BASE_RESOURCE_DIR, "poe_compare.png"),
        "copy":    os.path.join(BASE_RESOURCE_DIR, "poe_copy.png"),
        "thumb":   os.path.join(BASE_RESOURCE_DIR, "poe_thumb.png"),
        # 注意：原代码中有两个 "retry"，后一个覆盖了前一个。这里假设你是想检测 failure
        "retry":   os.path.join(BASE_RESOURCE_DIR, "poe_retry.png"),
        "failure": os.path.join(BASE_RESOURCE_DIR, "poe_failure.png"), 
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        if not os.path.exists(path):
            # 如果文件不存在，只打印警告，不抛出异常，防止某张非关键图片缺失导致程序无法启动
            print(f"警告：模板文件不存在 {path}")
            continue
            
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            print(f"警告：模板图片未能正确读取于路径 {path}")
            continue
        templates[key] = template

    # 检查关键模板是否存在
    if "thumb" not in templates:
        print("错误：关键模板 'poe_thumb.png' 未加载，程序退出。")
        sys.exit(1)

    monitoring_stop = False
    timeout_monitoring = time.time() + 65
    
    # 优先检测 failure/retry 列表
    retry_keys = [k for k in ["retry", "failure"] if k in templates]

    while not monitoring_stop and time.time() < timeout_monitoring:
        # 1. 找 retry / failure
        found_retry = False
        for key in retry_keys:
            location_retry, _ = find_image_on_screen(templates[key])
            if location_retry:
                print(f"找到 {key}，执行重试并刷新")
                click_retry_and_refresh()
                time.sleep(0.5)
                # 刷新后页面状态变化，需要重新从头寻找
                monitoring_stop = True
                found_retry = True
                break # 找到一个就退出循环
        
        if found_retry:
            continue # 如果执行了刷新，跳过本次循环剩下的检测，重新开始

        # 2. 找 thumb
        location, shape = find_image_on_screen(templates["thumb"])
        if location:
            print("找到 thumb，退出循环，继续后续逻辑")
            monitoring_stop = True
        else:
            # 3. 都没找到，就滚动屏幕再试
            print("未找到 retry 或 thumb，滚动页面后重试...")
            pyautogui.scroll(SCROLL_AMOUNT)
            time.sleep(0.5)

    if not monitoring_stop:
        print("60秒内未找到 retry 或 thumb 图片，退出或执行兜底逻辑。")
        sys.exit()

    # 如果模式是 long
    if mode == 'long':
        found_thumb = False
        timeout_thumb = time.time() + 35
        while not found_thumb and time.time() < timeout_thumb:
            location, shape = find_image_on_screen(templates["thumb"])
            if location:
                found_thumb = True
                print(f"找到图片位置: {location}")
            else:
                print("未找到thumb图片，继续监控...")
                pyautogui.scroll(SCROLL_AMOUNT)
                time.sleep(1)

        if time.time() > timeout_thumb:
            print("在35秒内未找到thumb图片，退出程序。")
            sys.exit()

        # 找 compare 图片
        if "compare" in templates:
            found_compare = False
            timeout_compare = time.time() + 25
            while not found_compare and time.time() < timeout_compare:
                location_compare, shape_compare = find_image_on_screen(templates["compare"])
                if location_compare:
                    found_compare = True
                else:
                    pyautogui.click(*SECONDARY_CLICK_COORDS)
                    pyautogui.scroll(SCROLL_AMOUNT)
                    print("未找到compare图片，继续监控...")

        # 找 thumb，然后右键点击
        location, shape = find_image_on_screen(templates["thumb"])
        if location:
            # <--- 修改：使用动态计算的点击函数，偏移 -200
            click_image_center(location, shape, button='right', offset_y=-200, move_only=True)
            pyautogui.click(button='right')
        else:
            print(f"找不到thumb图片，location结果: {location}")

    elif mode == 'short':
        # 如果模式是 short
        found_thumb = False
        timeout_thumb = time.time() + 25
        while not found_thumb and time.time() < timeout_thumb:
            location, shape = find_image_on_screen(templates["thumb"])
            if location:
                # <--- 修改：使用动态计算的点击函数，偏移 -100
                click_image_center(location, shape, button='right', offset_y=-100, move_only=True)
                pyautogui.click(button='right')
                found_thumb = True
            else:
                print(f"未找到thumb图片，继续滚动")
                pyautogui.scroll(SCROLL_AMOUNT)
                time.sleep(0.5)

    # 找 copy 图片，点击它
    time.sleep(0.5)
    if "copy" in templates:
        found_copy = False
        timeout_copy = time.time() + 25
        while not found_copy and time.time() < timeout_copy:
            location_copy, shape_copy = find_image_on_screen(templates["copy"])
            if location_copy:
                # <--- 修改：点击 copy 图片中心
                click_image_center(location_copy, shape_copy)
                found_copy = True
                print(f"找到copy图片位置: {location_copy}")
            else:
                print("未找到copy图片，继续监控...")
                time.sleep(1)

    # 最后找 success 图片
    time.sleep(1)
    if "success" in templates:
        found_success_image = False
        timeout_success = time.time() + 25
        while not found_success_image and time.time() < timeout_success:
            location_success, shape_success = find_image_on_screen(templates["success"])
            if location_success:
                print("找到poe_copy_success图片，继续执行程序...")
                found_success_image = True
            else:
                time.sleep(1)  # 每次检测间隔1秒

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process files based on the given mode.')
    parser.add_argument('mode', choices=['short', 'long'], help='The processing mode: short or long')
    args = parser.parse_args()
    main(args.mode)
