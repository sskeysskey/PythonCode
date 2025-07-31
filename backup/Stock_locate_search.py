import cv2
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab

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
        "searchlogo": "/Users/yanzhang/Coding/python_code/Resource/Stock_search_logo.png",
    }

    # 读取所有模板图片，并存储在字典中
    templates = {}
    for key, path in template_paths.items():
        template = cv2.imread(path, cv2.IMREAD_COLOR)
        if template is None:
            raise FileNotFoundError(f"模板图片未能正确读取于路径 {path}")
        templates[key] = template
    
    found_searchlogo = False
    while not found_searchlogo:
        location, shape = find_image_on_screen(templates["searchlogo"])
        if location:
            print("找到图片，继续监控...")
            # 计算中心坐标
            center_x = (location[0] + shape[1] // 2) // 2
            center_y = (location[1] + shape[0] // 2) // 2

            click_x = center_x + 30
            click_y = center_y
            
            # 写入坐标到文件
            with open('/tmp/coordinates.txt', 'w') as f:
                f.write(f'{center_x}\n{center_y}\n')
            
            pyautogui.click(click_x, click_y)
            found_searchlogo = True
        else:
            print("图片没找到，继续找...")
            sleep(1)

if __name__ == '__main__':
    main()