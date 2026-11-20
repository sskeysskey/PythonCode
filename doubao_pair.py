# ~/Coding/python_code/doubao_pair.py
import os
import cv2
import numpy as np
import pyautogui
import pyperclip
from PIL import ImageGrab
from time import sleep

USER_HOME = os.path.expanduser("~")
RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")

COPY_THRESHOLD = 0.9
REGEN_THRESHOLD = 0.88
SCROLL_AMOUNT = -120

# copy 相对 regenerate 的固定偏移（逻辑坐标），与 Doubao_auto.py 保持一致
PAIR_CFG = {"dx": -104, "dy": 0, "tol_x": 30, "tol_y": 25}

_scale_factor = None


def get_scale_factor():
    """ImageGrab 物理像素 / pyautogui 逻辑坐标，Retina 通常为 2.0"""
    global _scale_factor
    if _scale_factor is None:
        try:
            with ImageGrab.grab() as sc:
                img_w = sc.size[0]
            screen_w, _ = pyautogui.size()
            _scale_factor = img_w / screen_w
        except Exception:
            _scale_factor = 1.0
    return _scale_factor


def load_template(name):
    """加载模板，缺失则抛出异常（关键模板必须存在）"""
    path = os.path.join(RESOURCE_DIR, name)
    img = cv2.imread(path, cv2.IMREAD_COLOR) if os.path.exists(path) else None
    if img is None:
        raise FileNotFoundError(f"模板缺失或无法读取: {path}")
    return img


def capture_screen():
    with ImageGrab.grab() as shot:
        img = np.array(shot)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def match_all(template, threshold, screen, max_candidates=2000):
    """返回模板全部命中的中心点（逻辑坐标），做了 NMS 去重"""
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

    s = get_scale_factor()
    return [(int((x + tw / 2) / s), int((y + th / 2) / s)) for x, y in picked]


def find_regen_copy_pair(regen_tpl, copy_tpl, screen=None):
    """找到与 regenerate 配对的 copy，返回逻辑坐标 (x, y) 或 None"""
    if screen is None:
        screen = capture_screen()

    anchors = match_all(regen_tpl, REGEN_THRESHOLD, screen)
    targets = match_all(copy_tpl, COPY_THRESHOLD, screen)
    if not anchors or not targets:
        return None

    anchors.sort(key=lambda p: (p[1], p[0]))  # 从上到下、从左到右

    for ax, ay in anchors:
        best = None
        for tx, ty in targets:
            ex = (tx - ax) - PAIR_CFG["dx"]
            ey = (ty - ay) - PAIR_CFG["dy"]
            if abs(ex) <= PAIR_CFG["tol_x"] and abs(ey) <= PAIR_CFG["tol_y"]:
                d = ex * ex + ey * ey
                if best is None or d < best[0]:
                    best = (d, tx, ty)
        if best:
            return best[1], best[2]
    return None


def click_paired_copy(regen_tpl, copy_tpl, max_scrolls=10, wait=1.0):
    """
    循环查找并点击与 regenerate 配对的 copy。
    找不到就滚动后重试，最多滚动 max_scrolls 次。
    成功返回 (x, y)，失败返回 None。
    """
    for _ in range(max_scrolls + 1):
        pair = find_regen_copy_pair(regen_tpl, copy_tpl)
        if pair:
            x, y = pair
            try:
                pyperclip.copy("")  # 先清空剪贴板，避免读到旧内容
            except Exception:
                pass
            pyautogui.click(x, y)
            return x, y
        pyautogui.scroll(SCROLL_AMOUNT)
        sleep(wait)
    return None