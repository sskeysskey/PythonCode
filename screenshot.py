import os
import cv2
import sys
import time
import pyautogui
import numpy as np
from time import sleep
from PIL import ImageGrab
from typing import List, Tuple, Optional, Union, Dict

# ================= 配置区域 =================

# 1. 动态获取当前用户的主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义资源目录
BASE_RESOURCE_DIR = os.path.join(USER_HOME, "Coding", "python_code", "Resource")

# 退出码（与 News_auto.py / API_Client.py 协议保持一致）
EXIT_OK = 0
EXIT_DEPENDENCY = 3   # 依赖或参数错误（模板缺失 / 参数非法）

# 模板匹配阈值（与 run1/run2 保持一致）
MATCH_THRESHOLD = 0.9
# 多目标匹配时参与 NMS 的最大候选点数量（防止极端情况下卡顿）
MAX_CANDIDATES = 2000

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
        self.template_map: Dict[str, np.ndarray] = {}
        self.clickValue = clickValue          # None / 'left' / 'right' / 'move'
        self.Opposite = Opposite
        self.scroll_on_not_found_run1 = scroll_on_not_found_run1
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.nth_match = max(1, nth_match)    # 保留参数（兼容旧调用），当前未使用
        self.timeout_seconds = max(0, timeout_seconds)

        if isinstance(template_names, str):
            self.template_name_list = [name.strip() for name in template_names.split(',') if name.strip()]
        else:
            self.template_name_list = template_names

        # 计算屏幕缩放因子 (用于处理 Mac Retina 2x 问题)
        self.scale_factor = self._get_scale_factor()
        print(f"检测到屏幕缩放因子: {self.scale_factor}")

        self._load_templates(self.template_name_list)

    def _get_scale_factor(self) -> float:
        """
        计算 ImageGrab (物理像素) 和 pyautogui (逻辑坐标) 之间的缩放比例。
        在 Mac Retina 屏上通常是 2.0，在普通屏上通常是 1.0。
        """
        try:
            with ImageGrab.grab() as sc:
                img_width = sc.size[0]
            screen_width, _ = pyautogui.size()
            return img_width / screen_width
        except Exception as e:
            print(f"警告: 无法计算屏幕缩放因子，默认为 1.0。错误: {e}")
            return 1.0

    def _load_templates(self, template_names_list: List[str]) -> None:
        """模板加载"""
        for template_name in template_names_list:
            template_path = os.path.join(BASE_RESOURCE_DIR, template_name)
            try:
                if not os.path.exists(template_path):
                    print(f"错误: 模板文件不存在: {template_path}")
                    continue

                template_img = cv2.imread(template_path, cv2.IMREAD_COLOR)
                if template_img is None:
                    print(f"警告: 模板图片未能正确读取于路径 {template_path}")
                    continue
                self.templates.append((template_name, template_img))
                self.template_map[template_name] = template_img
            except Exception as e:
                print(f"An unexpected error occurred while loading template {template_name}: {e}")
                continue

    def has_templates(self) -> bool:
        return len(self.templates) > 0

    def capture_screen(self) -> np.ndarray:
        """屏幕捕获"""
        with ImageGrab.grab() as screenshot:
            img_np = np.array(screenshot)
            if img_np.shape[2] == 4:
                return cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            return cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

    def find_images_on_screen(self, threshold: float = 0.95) -> Tuple[Optional[str], Optional[Tuple[int, int]], Optional[Tuple[int, int, int]]]:
        """
        在屏幕上查找所有模板，并返回匹配得分最高的那个。
        （多模板相似时，例如 36 / 37，靠"取最高分"区分）
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

    # ------------------------------------------------------------------
    # 【新增】多目标匹配：返回某模板在屏幕上的全部匹配（逻辑坐标中心点）
    # ------------------------------------------------------------------
    def _match_all(self, screen: np.ndarray, template_name: str,
                   threshold: float = MATCH_THRESHOLD) -> List[Tuple[int, int, float]]:
        """
        返回 [(logic_center_x, logic_center_y, score), ...]
        使用贪心 NMS 去掉同一目标周围的重复命中点。
        """
        template = self.template_map.get(template_name)
        if template is None:
            return []

        th, tw = template.shape[:2]
        if th > screen.shape[0] or tw > screen.shape[1]:
            print(f"警告: 模板 {template_name} 尺寸 {template.shape} 大于屏幕截图 {screen.shape}，跳过。")
            return []

        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        if len(xs) == 0:
            return []

        scores = result[ys, xs]
        order = np.argsort(-scores)[:MAX_CANDIDATES]

        half_w = max(1, tw // 2)
        half_h = max(1, th // 2)
        picked: List[Tuple[int, int, float]] = []
        for i in order:
            x, y, s = int(xs[i]), int(ys[i]), float(scores[i])
            if all(abs(x - px) >= half_w or abs(y - py) >= half_h for px, py, _ in picked):
                picked.append((x, y, s))

        centers = []
        for x, y, s in picked:
            cx = int((x + tw / 2) / self.scale_factor)
            cy = int((y + th / 2) / self.scale_factor)
            centers.append((cx, cy, s))
        return centers

    def _click_logical(self, x: int, y: int) -> None:
        """【新增】直接按逻辑坐标执行点击"""
        try:
            if self.clickValue == "right":
                pyautogui.click(x, y, button='right')
                print(f"执行右键点击于: ({x}, {y})")
            elif self.clickValue == "move":
                pyautogui.moveTo(x, y, duration=0.25)
                print(f"鼠标悬停于: ({x}, {y})")
            else:
                pyautogui.click(x, y, button='left')
                print(f"执行左键点击于: ({x}, {y})")
        except pyautogui.FailSafeException:
            print("错误: 触发了 PyAutoGUI 的故障安全机制 (鼠标移到了角落)。")
        except Exception as e:
            print(f"点击操作失败: {e}")

    def _perform_click(self, location: Tuple[int, int], shape: Tuple[int, int, int]) -> None:
        """
        点击 / 悬停操作，自动处理 Retina 缩放。
        location: (x, y) - 基于 ImageGrab 截图（物理像素）的坐标
        shape: (h, w, c) - 模板的物理像素尺寸
        """
        phys_center_x = location[0] + shape[1] // 2
        phys_center_y = location[1] + shape[0] // 2

        logic_center_x = int(phys_center_x / self.scale_factor)
        logic_center_y = int(phys_center_y / self.scale_factor)

        if self.x_offset is not None:
            logic_center_x += self.x_offset
        if self.y_offset is not None:
            logic_center_y += self.y_offset

        try:
            if self.clickValue == "left":
                pyautogui.click(logic_center_x, logic_center_y, button='left')
                print(f"执行左键点击于: ({logic_center_x}, {logic_center_y}) [物理: ({phys_center_x}, {phys_center_y})]")
            elif self.clickValue == "right":
                pyautogui.click(logic_center_x, logic_center_y, button='right')
                print(f"执行右键点击于: ({logic_center_x}, {logic_center_y}) [物理: ({phys_center_x}, {phys_center_y})]")
            elif self.clickValue == "move":
                # 平滑移动：产生连续 mousemove 事件，确保网页 hover 菜单能被触发
                pyautogui.moveTo(logic_center_x, logic_center_y, duration=0.25)
                print(f"鼠标悬停于: ({logic_center_x}, {logic_center_y}) [物理: ({phys_center_x}, {phys_center_y})]")
        except pyautogui.FailSafeException:
            print("错误: 触发了 PyAutoGUI 的故障安全机制 (鼠标移到了角落)。")
        except Exception as e:
            print(f"点击操作失败: {e}")

    def run1(self) -> str:
        """查找图片（至少检测一次），找到后按需点击"""
        deadline = time.time() + self.timeout_seconds

        while True:
            template_name, location, shape = self.find_images_on_screen(threshold=MATCH_THRESHOLD)

            if location and template_name and shape:
                if self.clickValue:
                    self._perform_click(location, shape)
                print(f"找到图片 {template_name} 位置: {location}")
                if len(self.template_name_list) > 1:
                    print(f"FOUND_IMAGE:{template_name}")
                return template_name

            if time.time() >= deadline:
                break

            if self.scroll_on_not_found_run1:
                print("在 run1 中未找到图片，执行滚动操作 pyautogui.scroll(-120)")
                pyautogui.scroll(-120)
                sleep(0.5)
            sleep(1)

        print(f"在 {self.timeout_seconds} 秒内未找到图片，退出程序。")
        return "TIMEOUT"

    def run2(self) -> str:
        """
        持续查找，直到找不到图片（等待图片消失）。
        【修复】返回并输出明确状态：VANISHED / STILL_PRESENT
        （刻意不使用 TIMEOUT 字样，避免影响其他脚本的既有判断）
        """
        deadline = time.time() + self.timeout_seconds

        while True:
            template_name, location, shape = self.find_images_on_screen(threshold=MATCH_THRESHOLD)

            if not location:
                print("未找到图片，认为图片已消失，退出run2。")
                return "VANISHED"

            print(f"图片 {template_name} 仍在屏幕上位置: {location}，等待其消失...")
            if time.time() >= deadline:
                break
            sleep(1)

        print(f"在 {self.timeout_seconds} 秒内图片仍未消失。")
        return "STILL_PRESENT"

    # ------------------------------------------------------------------
    # 【新增】锚点-目标配对点击
    # ------------------------------------------------------------------
    def run_pair(self, anchor_name: str, target_name: str,
                 dx: int, dy: int, tol_x: int, tol_y: int, do_click: bool) -> str:
        """
        1. 找到 anchor 的全部匹配，按 (y, x) 升序排序（最上方优先）
        2. 对每个 anchor，在 target 全部匹配中寻找偏移 ≈ (dx, dy) 的那个
           （|实际dx-dx|<=tol_x 且 |实际dy-dy|<=tol_y，取欧氏误差最小者）
        3. 最上方 anchor 配不上时依次尝试下一个
        输出：PAIR_CLICKED:x,y / PAIR_FOUND:x,y / PAIR_NOT_FOUND / NO_ANCHOR
        """
        deadline = time.time() + self.timeout_seconds
        anchor_seen = False

        while True:
            screen = self.capture_screen()
            anchors = self._match_all(screen, anchor_name)

            if anchors:
                anchor_seen = True
                anchors.sort(key=lambda m: (m[1], m[0]))
                targets = self._match_all(screen, target_name)
                print(f"锚点 {anchor_name} 共 {len(anchors)} 个: {[(a[0], a[1]) for a in anchors]}")
                print(f"目标 {target_name} 共 {len(targets)} 个: {[(t[0], t[1]) for t in targets]}")

                for rank, (ax, ay, _) in enumerate(anchors, 1):
                    best = None
                    for tx, ty, _ts in targets:
                        ex = (tx - ax) - dx
                        ey = (ty - ay) - dy
                        if abs(ex) <= tol_x and abs(ey) <= tol_y:
                            dist = ex * ex + ey * ey
                            if best is None or dist < best[0]:
                                best = (dist, tx, ty)

                    if best is not None:
                        _, tx, ty = best
                        if rank > 1:
                            print(f"注意: 最上方锚点无对应目标，改用第 {rank} 个锚点。")
                        print(f"配对成功: 锚点({ax}, {ay}) -> 目标({tx}, {ty})，实际偏移 ({tx - ax}, {ty - ay})，期望 ({dx}, {dy})")
                        if do_click:
                            self._click_logical(tx, ty)
                            print(f"PAIR_CLICKED:{tx},{ty}")
                            return "PAIR_CLICKED"
                        print(f"PAIR_FOUND:{tx},{ty}")
                        return "PAIR_FOUND"

                    print(f"锚点#{rank} ({ax}, {ay}) 附近未找到偏移约 ({dx}, {dy}) 的 {target_name}。")

            if time.time() >= deadline:
                break
            sleep(0.5)

        if anchor_seen:
            print("PAIR_NOT_FOUND")
            return "PAIR_NOT_FOUND"
        print("NO_ANCHOR")
        return "NO_ANCHOR"


def parse_args() -> Tuple[Union[str, List[str]], Optional[str], bool, bool, Optional[int], Optional[int], int, int]:
    """参数解析函数"""
    if len(sys.argv) < 4:
        print("用法: python screenshot.py <image_name1[,image_name2...]> <click_type: true|right|move|false> <Opposite> [scroll] [x] [y] [nth] [timeout]")
        print("  或: python screenshot.py --pair <anchor.png> <target.png> <dx> <dy> [tol_x=60] [tol_y=20] [click=true] [timeout=3]")
        sys.exit(EXIT_DEPENDENCY)

    image_names_str = sys.argv[1]

    click_arg = sys.argv[2].lower()
    clickValue: Optional[str] = None
    if click_arg == 'true':
        clickValue = 'left'
    elif click_arg == 'right':
        clickValue = 'right'
    elif click_arg == 'move':
        clickValue = 'move'
    elif click_arg == 'false':
        clickValue = None
    else:
        print(f"错误: 无效的 click_type '{sys.argv[2]}'.")
        sys.exit(EXIT_DEPENDENCY)

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
        if len(final_optional_args) >= 1: x_offset = int(final_optional_args[0])
        if len(final_optional_args) >= 2: y_offset = int(final_optional_args[1])
        if len(final_optional_args) >= 3: nth_match = int(final_optional_args[2])
        if len(final_optional_args) >= 4: timeout_seconds = int(final_optional_args[3])
    except (ValueError, IndexError):
        print(f"警告: 可选参数解析失败 {final_optional_args}，未解析部分使用默认值。")

    return image_names_str, clickValue, Opposite, scroll_in_run1, x_offset, y_offset, nth_match, timeout_seconds


def parse_pair_args() -> Tuple[str, str, int, int, int, int, bool, int]:
    """【新增】--pair 模式参数解析"""
    argv = sys.argv[2:]
    if len(argv) < 4:
        print("用法: python screenshot.py --pair <anchor.png> <target.png> <dx> <dy> [tol_x=60] [tol_y=20] [click=true] [timeout=3]")
        sys.exit(EXIT_DEPENDENCY)
    try:
        anchor = argv[0].strip()
        target = argv[1].strip()
        dx = int(argv[2])
        dy = int(argv[3])
        tol_x = int(argv[4]) if len(argv) > 4 else 60
        tol_y = int(argv[5]) if len(argv) > 5 else 20
        do_click = (argv[6].lower() != 'false') if len(argv) > 6 else True
        timeout = int(argv[7]) if len(argv) > 7 else 3
    except ValueError as e:
        print(f"错误: --pair 参数非法: {e}")
        sys.exit(EXIT_DEPENDENCY)
    return anchor, target, dx, dy, abs(tol_x), abs(tol_y), do_click, timeout


if __name__ == '__main__':
    # ---------------- 【新增】配对模式 ----------------
    if len(sys.argv) > 1 and sys.argv[1] == '--pair':
        anchor, target, dx, dy, tol_x, tol_y, do_click, timeout = parse_pair_args()
        detector = ScreenDetector(
            template_names=[anchor, target],
            clickValue='left' if do_click else None,
            timeout_seconds=timeout
        )
        missing = [n for n in (anchor, target) if n not in detector.template_map]
        if missing:
            print(f"错误: 配对模式缺少模板 {missing}，请检查 {BASE_RESOURCE_DIR}")
            print("程序执行完毕。")
            sys.exit(EXIT_DEPENDENCY)
        try:
            detector.run_pair(anchor, target, dx, dy, tol_x, tol_y, do_click)
        finally:
            print("程序执行完毕。")
        sys.exit(EXIT_OK)

    # ---------------- 原有模式 ----------------
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

    # 模板全部缺失：立即失败，而不是空等 590 秒后"假成功"
    if not detector.has_templates():
        print(f"错误: 没有任何可用模板（{args_tuple[0]}），请检查 {BASE_RESOURCE_DIR}")
        print("程序执行完毕。")
        sys.exit(EXIT_DEPENDENCY)

    try:
        if args_tuple[2]:  # Opposite is True, run run2
            result = detector.run2()
            print(result)
        else:
            result = detector.run1()
            print(result)
    finally:
        print("程序执行完毕。")