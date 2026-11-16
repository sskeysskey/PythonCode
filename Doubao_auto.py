import os
import cv2
import time
import pyautogui
import numpy as np
import sys
import pyperclip  # 读取剪贴板
import re         # 正则匹配汉字
from PIL import ImageGrab
from time import sleep

# ================= 配置区域 =================
USER_HOME = os.path.expanduser("~")
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")
SCROLL_AMOUNT = -120  # 稍微加大滚动幅度，确保跳过已检查的按钮

COPY_TEMPLATE_NAME    = "doubao_copy.png"
RELATED_TEMPLATE_NAME = "doubao_related.png"
WRONG_TEMPLATE_NAME   = "doubao_wrong.png"   # 【新增】豆包回答异常标识

COPY_THRESHOLD    = 0.9
RELATED_THRESHOLD = 0.8
WRONG_THRESHOLD   = 0.88   # 【新增】可按实际命中率微调

REGEN_TEMPLATE_NAME = "doubao_regenerate.png"   # 锚点模板（必须存在于 Resource 目录）
REGEN_THRESHOLD     = 0.88

# copy 相对 regenerate 的固定偏移（逻辑坐标）
PAIR_CFG = {
    "dx": -104,            # copy.x - regenerate.x
    "dy": 0,               # copy.y - regenerate.y
    "tol_x": 30,
    "tol_y": 25,
    "row_fallback": False, # 关闭同行兜底，防止误配到别的 copy
}

# ================= 退出码约定 =================
EXIT_OK               = 0  # 成功，剪贴板内容合格
EXIT_CONTENT_FAIL     = 1  # 3 次点击复制，内容均不合格
EXIT_TIMEOUT          = 2  # 超时未找到复制按钮
EXIT_TEMPLATE_MISSING = 3  # 关键模板图缺失
EXIT_REFUSED          = 4  # 豆包拒答（保留给你原有逻辑）
EXIT_WRONG            = 6  # 【新增】检测到 doubao_wrong.png（回答异常）


def get_scale_factor():
    """
    计算 ImageGrab (物理像素) 和 pyautogui (逻辑坐标) 之间的缩放比例。
    Mac Retina 通常 2.0，普通屏 1.0。
    """
    try:
        with ImageGrab.grab() as sc:
            img_width = sc.size[0]
        screen_width, _ = pyautogui.size()
        return img_width / screen_width
    except Exception:
        return 1.0


SCALE_FACTOR = get_scale_factor()
print(f"检测到屏幕缩放因子: {SCALE_FACTOR}")


def capture_screen():
    with ImageGrab.grab() as screenshot:
        img_np = np.array(screenshot)
        if img_np.shape[2] == 4:
            return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)


def find_image_on_screen(template, threshold=COPY_THRESHOLD):
    """
    在屏幕上查找图片
    返回: (max_loc, shape) 或 (None, None)
    """
    if template is None:
        return None, None

    screen = capture_screen()

    # 防止模板比屏幕还大导致报错
    if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
        return None, None

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    if max_val >= threshold:
        return max_loc, template.shape
    return None, None


def load_template(name, required=True):
    """
    加载模板图。required=False 时缺失只警告，返回 None（等于关闭该功能）。
    """
    path = os.path.join(BASE_RESOURCE_DIR, name)
    if not os.path.exists(path):
        if required:
            print(f"错误：找不到模板文件 {path}")
            sys.exit(EXIT_TEMPLATE_MISSING)
        print(f"警告：未找到可选模板 {path}，该检测功能自动关闭。")
        return None

    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        if required:
            print(f"错误：模板文件无法读取 {path}")
            sys.exit(EXIT_TEMPLATE_MISSING)
        print(f"警告：可选模板无法读取 {path}，该检测功能自动关闭。")
        return None
    return img


def is_content_qualified(text, min_chinese=50):
    """校验内容是否包含足够多的中文"""
    if not text:
        return False
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    return len(chinese_chars) > min_chinese


def perform_click(location, shape):
    """根据位置和形状计算中心点并点击"""
    phys_center_x = location[0] + shape[1] // 2
    phys_center_y = location[1] + shape[0] // 2

    logic_center_x = int(phys_center_x / SCALE_FACTOR)
    logic_center_y = int(phys_center_y / SCALE_FACTOR)

    pyautogui.click(logic_center_x, logic_center_y)
    return logic_center_x, logic_center_y

def match_all(template, threshold, screen=None, max_candidates=2000):
    """返回模板的全部命中，格式 [(逻辑x, 逻辑y), ...]，已做 NMS 去重（中心点，逻辑坐标）"""
    if template is None:
        return []
    if screen is None:
        screen = capture_screen()

    th, tw = template.shape[:2]
    if th > screen.shape[0] or tw > screen.shape[1]:
        return []

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    if len(xs) == 0:
        return []

    scores = result[ys, xs]
    order = np.argsort(-scores)[:max_candidates]
    half_w, half_h = max(1, tw // 2), max(1, th // 2)

    picked = []
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        if all(abs(x - px) >= half_w or abs(y - py) >= half_h for px, py in picked):
            picked.append((x, y))

    out = []
    for x, y in picked:
        cx = int((x + tw / 2) / SCALE_FACTOR)
        cy = int((y + th / 2) / SCALE_FACTOR)
        out.append((cx, cy))
    return out


def find_regen_copy_pair(regen_tpl, copy_tpl, screen=None):
    """
    找到「regenerate + 与之配对的 copy」。
    返回 (copy_x, copy_y)（逻辑坐标）或 None。
    锚点按从上到下、从左到右排序，最上方配不上时尝试下一个。
    """
    if screen is None:
        screen = capture_screen()

    anchors = match_all(regen_tpl, REGEN_THRESHOLD, screen)
    if not anchors:
        return None
    anchors.sort(key=lambda p: (p[1], p[0]))

    targets = match_all(copy_tpl, COPY_THRESHOLD, screen)
    if not targets:
        return None

    for rank, (ax, ay) in enumerate(anchors, 1):
        best = None
        for tx, ty in targets:
            ex = (tx - ax) - PAIR_CFG["dx"]
            ey = (ty - ay) - PAIR_CFG["dy"]
            if abs(ex) <= PAIR_CFG["tol_x"] and abs(ey) <= PAIR_CFG["tol_y"]:
                d = ex * ex + ey * ey
                if best is None or d < best[0]:
                    best = (d, tx, ty)

        if best:
            _, tx, ty = best
            print(f"配对成功(锚点#{rank})：锚点({ax},{ay}) -> 复制({tx},{ty})，"
                  f"实际偏移({tx - ax},{ty - ay})，期望({PAIR_CFG['dx']},{PAIR_CFG['dy']})")
            return tx, ty

    return None

def check_wrong_confirmed(copy_template, wrong_template):
    """
    【新增】二次确认「回答异常」：
    1) 第一次命中 wrong 后，等 1.5s
    2) 复查时优先看 copy（万一复制按钮刚刚渲染出来，就以 copy 为准，返回 False）
    3) copy 仍无、wrong 仍在 -> 确认异常，返回 True
    """
    if wrong_template is None:
        return False

    loc, _ = find_image_on_screen(wrong_template, threshold=WRONG_THRESHOLD)
    if not loc:
        return False

    print("疑似检测到 doubao_wrong 标识，1.5 秒后二次确认...")
    sleep(1.5)

    copy_loc, _ = find_image_on_screen(copy_template, threshold=COPY_THRESHOLD)
    if copy_loc:
        print("二次确认时发现 Copy 按钮已出现，忽略 wrong 标识。")
        return False

    loc2, _ = find_image_on_screen(wrong_template, threshold=WRONG_THRESHOLD)
    if loc2:
        print("二次确认成立：豆包回答异常（doubao_wrong）。")
        return True

    print("二次确认不成立（wrong 已消失），继续正常流程。")
    return False


def main():
    # ==== 命令行参数：汉字阈值 ====
    target_threshold = 50
    if len(sys.argv) > 1:
        try:
            target_threshold = int(sys.argv[1])
            print(f"接收到自定义汉字阈值: {target_threshold}")
        except ValueError:
            print("参数格式错误，使用默认阈值 50")

    # ==== 加载模板 ====
    copy_template    = load_template(COPY_TEMPLATE_NAME, required=True)
    related_template = load_template(RELATED_TEMPLATE_NAME, required=True)
    wrong_template   = load_template(WRONG_TEMPLATE_NAME, required=False)
    regen_template   = load_template(REGEN_TEMPLATE_NAME, required=True)

    max_attempts = 3
    current_attempt = 1
    timeout_duration = 120
    start_time = time.time()

    print(f"开始监控豆包内容（最多尝试3次，汉字阈值：{target_threshold}）...")

    while current_attempt <= max_attempts:
        if time.time() - start_time > timeout_duration:
            print("寻找超时：未能在规定时间内找到复制按钮")
            sys.exit(EXIT_TIMEOUT)

        # ==== 1. 寻找 regenerate + 配对的 copy ====
        pair = find_regen_copy_pair(regen_template, copy_template)

        if not pair:
            # 连配对都没有 -> 检查 wrong
            if check_wrong_confirmed(copy_template, wrong_template):
                sys.exit(EXIT_WRONG)
            pyautogui.scroll(SCROLL_AMOUNT)
            sleep(1)
            continue

        print("初次配对到 Copy 按钮，开始检测 Related 标识...")

        # ==== 2. 等待 Related 标识（最多 4 秒，布局可能变化）====
        gate_start = time.time()
        found_related = False
        while time.time() - gate_start < 4:
            rel_loc, _ = find_image_on_screen(related_template, threshold=RELATED_THRESHOLD)
            if rel_loc:
                print("检测到 Related 标识（布局已变化）。")
                found_related = True
                break
            sleep(0.5)
        if not found_related:
            print("4 秒内未检测到 Related 标识，重新配对 Copy。")

        # ==== 3. 重新配对（布局可能已变，必须再配一次）====
        pair = find_regen_copy_pair(regen_template, copy_template)
        if not pair:
            print("等待后无法重新配对 Copy，检查是否回答异常...")
            if check_wrong_confirmed(copy_template, wrong_template):
                sys.exit(EXIT_WRONG)
            pyautogui.scroll(SCROLL_AMOUNT)
            sleep(1)
            continue  # 未实际点击，不消耗 attempt

        # ==== 4. 点击配对的 copy 并校验剪贴板 ====
        lx, ly = pair
        try:
            pyperclip.copy("")          # 先清空，避免旧内容误判为合格
        except Exception as e:
            print(f"清空剪贴板失败（忽略）: {e}")

        pyautogui.click(lx, ly)
        print(f"第 {current_attempt} 次尝试 - 点击配对的复制按钮: {lx}, {ly}")
        sleep(0.5)
        content = pyperclip.paste()

        if is_content_qualified(content, min_chinese=target_threshold):
            print(f"第 {current_attempt} 次尝试成功：内容校验通过。")
            sys.exit(EXIT_OK)

        print(f"第 {current_attempt} 次尝试失败：内容不合格。")

        if check_wrong_confirmed(copy_template, wrong_template):
            sys.exit(EXIT_WRONG)

        current_attempt += 1
        if current_attempt <= max_attempts:
            pyautogui.scroll(SCROLL_AMOUNT)
            sleep(1)
        else:
            print("已达到最大尝试次数，内容均不合格。")
            sys.exit(EXIT_CONTENT_FAIL)

    sys.exit(EXIT_CONTENT_FAIL)


if __name__ == '__main__':
    main()