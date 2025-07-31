import cv2
import time
import pyautogui
import subprocess
import numpy as np
from time import sleep
from PIL import ImageGrab

# 截取屏幕
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
    # 释放截图和模板图像以节省内存
    del screen
    if max_val >= threshold:
        return max_loc, template.shape
    else:
        return None, None

# 主函数
def main():
    # 定义模板路径字典
    template_paths = {
        "stop": "/Users/yanzhang/Coding/python_code/Resource/poe_stop.png",
        "waiting": "/Users/yanzhang/Coding/python_code/Resource/poe_stillwaiting.png",
        "success": "/Users/yanzhang/Coding/python_code/Resource/poe_copy_success.png",
        "thumb": "/Users/yanzhang/Coding/python_code/Resource/poe_thumb.png",
        "failure": "/Users/yanzhang/Coding/python_code/Resource/poe_failure.png",
        "no": "/Users/yanzhang/Coding/python_code/Resource/poe_no.png",
        "copy": "/Users/yanzhang/Coding/python_code/Resource/poe_copy.png",
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {path}")
        templates[key] = template

    found = False
    timeout_stop = time.time() + 10
    while not found and time.time() < timeout_stop:
        location, shape = find_image_on_screen(templates["stop"])
        if location:
            print(f"找到图片位置: {location}")
            found = True
        else:
            print("未找到图片，继续监控...")
            location, shape = find_image_on_screen(templates["failure"])
            if location:
                print("找到poe_failure图片，执行页面刷新操作...")
                pyautogui.click(x=617, y=574)
                sleep(0.5)
                script = '''
                tell application "System Events"
                    key code 15 using command down
                end tell
                '''
                subprocess.run(['osascript', '-e', script], check=True)
                # 给系统一点时间来完成复制操作
                sleep(0.5)
            location, shape = find_image_on_screen(templates["no"])
            if location:
                print("找到poe_no图片，执行页面刷新操作...")
                pyautogui.click(x=617, y=574)
                sleep(0.5)
                script = '''
                tell application "System Events"
                    key code 15 using command down
                end tell
                '''
                subprocess.run(['osascript', '-e', script], check=True)
                # 给系统一点时间来完成复制操作
                sleep(0.5)
            sleep(1)

    found_stop = True
    while found_stop:
        location, shape = find_image_on_screen(templates["stop"])
        if location:
            print("找到poe_stop图片，继续监控...")
            pyautogui.scroll(-120)
            # 检测poe_stillwaiting.png图片
            location, shape = find_image_on_screen(templates["waiting"])
            if location:
                print("找到poe_stillwaiting图片，执行页面刷新操作...")
                pyautogui.click(x=617, y=574)
                sleep(0.5)
                script = '''
                tell application "System Events"
                    key code 15 using command down
                end tell
                '''
                subprocess.run(['osascript', '-e', script], check=True)
                # 给系统一点时间来完成复制操作
                sleep(0.5)
            sleep(1)  # 简短暂停再次监控
        else:
            print("Stop图片没有了...")
            pyautogui.scroll(-80)
            found_stop = False

    found_thumb = False
    timeout_thumb = time.time() + 15
    while not found_thumb and time.time() < timeout_thumb:
        location, shape = find_image_on_screen(templates["thumb"])
        if location:
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2

            # 调整坐标，假设你已经计算好了需要传递给AppleScript的坐标值
            xCoord = center_x
            yCoord = center_y - 50

            # 使用pyautogui移动鼠标并进行右键点击
            pyautogui.moveTo(xCoord, yCoord)
            pyautogui.click(button='right')
            found_thumb = True
        else:
            print(f"找到图片位置: {location}")
            pyautogui.scroll(-80)
            sleep(0.5)

    sleep(1)
    found_copy = False
    timeout_copy = time.time() + 5
    while not found_copy and time.time() < timeout_copy:
        location, shape = find_image_on_screen(templates["copy"])
        if location:
            # 计算中心坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2
            
            # 鼠标点击中心坐标
            pyautogui.click(center_x, center_y)
            found_copy = True
            print(f"找到图片位置: {location}")
        else:
            print("未找到图片，继续监控...")
            sleep(1)

    # 设置寻找poe_copy_success.png图片的超时时间为15秒
    sleep(1)
    found_success_image = False
    timeout_success = time.time() + 10
    while not found_success_image and time.time() < timeout_success:
        location, shape = find_image_on_screen(templates["success"])
        if location:
            print("找到poe_copy_success图片，继续执行程序...")
            found_success_image = True
        else:
            sleep(1)  # 每次检测间隔1秒

if __name__ == '__main__':
    main()