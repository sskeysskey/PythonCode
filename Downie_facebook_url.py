import re
import sys
import pyperclip
import subprocess
from time import sleep

# 复用你现有 a.py 里的 ScreenDetector 类
from screenshot import ScreenDetector


# ================= 配置区域 =================
ADD_IMAGE      = "downie_add.png"        # 添加下载的按钮
FINISHED_IMAGE = "facebook_finished.png" # 下载完成的标志
CLEAR_IMAGE    = "facebook_clear.png"    # 清除列表的按钮

# 各阶段超时（秒）
ADD_TIMEOUT      = 30    # 等待 add 按钮出现的最长时间
FINISHED_TIMEOUT = 590   # 等待下载完成的最长时间（下载可能较慢，给大一点）
CLEAR_TIMEOUT    = 30    # 等待 clear 按钮出现的最长时间

CLIPBOARD_SETTLE = 1.5   # 写入剪贴板后，等 Downie 检测到链接的缓冲时间
# ===========================================


def get_urls_from_clipboard():
    """从当前剪贴板内容中提取所有 http(s) URL，并按出现顺序去重。"""
    content = pyperclip.paste()
    raw_urls = re.findall(r'https?://[^\s]+', content)

    seen = set()
    unique_urls = []
    for u in raw_urls:
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            unique_urls.append(u)
    return unique_urls


def scan_and_click(image_name, timeout):
    """扫描并点击某张图片。找到并点击返回 True，超时返回 False。"""
    detector = ScreenDetector(
        template_names=image_name,
        clickValue="left",
        Opposite=False,
        timeout_seconds=timeout
    )
    result = detector.run1()
    return result != "TIMEOUT"


def wait_until_appears(image_name, timeout):
    """只等待某张图片出现（不点击）。出现返回 True，超时返回 False。"""
    detector = ScreenDetector(
        template_names=image_name,
        clickValue=None,        # 不点击，只检测出现
        Opposite=False,
        timeout_seconds=timeout
    )
    result = detector.run1()
    return result != "TIMEOUT"


def activate_downie():
    """
    Mac 自动：
    激活 downie
    """
    print("\n===== 开始激活Downie =====")

    script = '''
    tell application "Downie 4"
        activate
        delay 0.3
    end tell

    -- 强制系统把Chrome窗口置顶（关键修复，原脚本缺失）
    tell application "System Events"
        tell application process "Downie 4"
            perform action "AXRaise" of front window
        end tell
    end tell
    '''

    # 执行脚本并捕获返回结果
    subprocess.run(['osascript', '-e', script], check=True)

def process_one_url(url, index, total):
    """处理单个 URL 的完整一轮循环。"""
    print("\n" + "=" * 60)
    print(f"[{index}/{total}] 开始处理: {url}")
    print("=" * 60)

    # 1. 把 URL 放进剪贴板，让 Downie 检测
    pyperclip.copy(url)
    print(f"已写入剪贴板，等待 {CLIPBOARD_SETTLE} 秒让 Downie 检测...")
    sleep(CLIPBOARD_SETTLE)

    # 2. 扫描并点击 downie_add.png
    print(f"步骤2: 查找并点击 {ADD_IMAGE} ...")
    if not scan_and_click(ADD_IMAGE, ADD_TIMEOUT):
        print(f"⚠️ 未找到 {ADD_IMAGE}，跳过该 URL。")
        return False

    # 3. 等待 facebook_finished.png 出现（下载完成）
    print(f"步骤3: 等待 {FINISHED_IMAGE} 出现（下载完成）...")
    if not wait_until_appears(FINISHED_IMAGE, FINISHED_TIMEOUT):
        print(f"⚠️ 在 {FINISHED_TIMEOUT} 秒内未检测到完成标志，跳过清除步骤。")
        return False

    # 4. 扫描并点击 facebook_clear.png
    print(f"步骤4: 查找并点击 {CLEAR_IMAGE} ...")
    if not scan_and_click(CLEAR_IMAGE, CLEAR_TIMEOUT):
        print(f"⚠️ 未找到 {CLEAR_IMAGE}（可能已自动清除）。")

    print(f"✅ [{index}/{total}] 处理完成。")
    return True


def main():
    activate_downie()

    urls = get_urls_from_clipboard()

    if not urls:
        print("剪贴板里没有检测到任何 URL，请先在 Notes 里全选复制后再运行。")
        sys.exit(0)

    print(f"共检测到 {len(urls)} 个唯一 URL：")
    for i, u in enumerate(urls, 1):
        print(f"  {i}. {u}")

    print("\n3 秒后开始自动化，请把鼠标准备好（移到屏幕角落可触发急停）...")
    sleep(3)

    success = 0
    for i, url in enumerate(urls, 1):
        if process_one_url(url, i, len(urls)):
            success += 1
        sleep(1)  # 两轮之间稍作停顿

    print("\n" + "=" * 60)
    print(f"全部处理完毕！成功 {success}/{len(urls)} 个。")
    print("=" * 60)


if __name__ == '__main__':
    main()