import sys
import os
import time
import subprocess
import platform

# 确保当前目录在 Python 搜索路径中，以便能找到同目录下的其他 py 文件
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# --- 导入你的各个爬虫模块 ---
# 注意：文件名必须与 import 后面的名字一致 (去掉 .py 后缀)
try:
    # 1. 导入 GUI/Javascript 爬虫 (作为第一阶段)
    import Javascript_News
    
    # 2. 导入 Selenium 爬虫 (作为第二阶段)
    import selenium_dw_cn
    import selenium_rfi_cn
    import selenium_bbc_cn
    import selenium_economist
    import selenium_techreview
    import selenium_nikkei_asia
    import selenium_washingtonpost
    import selenium_nytimes

except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请确保 javascript_news.py 和其他 selenium_*.py 文件在同一个文件夹内。")
    sys.exit(1)

def run_task(module_name, module_obj):
    """
    通用任务执行器
    :param module_name: 显示名称
    :param module_obj: 导入的模块对象
    """
    print("=" * 60)
    print(f"🚀 开始执行: {module_name}")
    print("=" * 60)
    
    try:
        # 调用模块中的 main() 函数
        module_obj.main()
        print(f"\n✅ {module_name} 执行完毕。\n")
    except Exception as e:
        print(f"\n❌ {module_name} 执行出错: {e}\n")
    
    # 任务之间稍作停顿，让系统资源缓冲一下
    time.sleep(3)

def activate_terminal():
    """
    跨平台：将终端/命令行窗口置于前台
    """
    system_name = platform.system()
    
    if system_name == 'Darwin':
        # macOS: 使用 AppleScript
        script = '''
        delay 0.5
        tell application "Terminal"
            activate
        end tell
        '''
        try:
            subprocess.run(['osascript', '-e', script], check=True)
        except Exception as e:
            print(f"尝试置顶终端失败 (macOS): {e}")
            
    elif system_name == 'Windows':
        # Windows: 使用 ctypes 调用 Win32 API
        try:
            import ctypes
            # 获取当前控制台窗口句柄
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd != 0:
                # SW_RESTORE = 9 (如果窗口最小化了，恢复它)
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                # 将窗口带到前台
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception as e:
            print(f"尝试置顶终端失败 (Windows): {e}")
    else:
        # Linux 其他系统暂不处理
        pass

def main():
    total_start = time.time()
    print(f"🕒 开始全量更新任务，当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ================= 第一阶段：GUI / Javascript 抓取 =================
    # 包括: FT, WSJ(Eng), Bloomberg, Reuters
    # 注意：这部分会控制鼠标，且不是 Headless 的
    try:
        # 确保 Javascript_News 模块已经按照之前的建议修改为跨平台版本
        Javascript_News.main()
    except Exception as e:
        print(f"❌ 第一阶段 (JavaScript News) 执行失败: {e}")
        # 即使第一阶段失败，也继续尝试第二阶段
    
    time.sleep(2) # 阶段切换缓冲
    
    # 尝试将控制权交回终端窗口
    activate_terminal()
    time.sleep(1)

    # ================= 第二阶段：Selenium Headless 抓取 =================
    # 包括: WSJ(CN), Economist, TechReview, Nikkei, WaPo, NYTimes

    # 1.2 RFI CN
    run_task("法广头条", selenium_rfi_cn)

    # 1.3 DE CN
    run_task("德国之声", selenium_dw_cn)

    # 1.4 BBC CN
    run_task("BBC", selenium_bbc_cn)

    # 2. The Economist
    run_task("The Economist", selenium_economist)

    # 3. MIT Tech Review
    run_task("MIT Technology Review", selenium_techreview)

    # 4. Nikkei Asia
    run_task("Nikkei Asia", selenium_nikkei_asia)

    # 5. Washington Post
    run_task("Washington Post", selenium_washingtonpost)

    # 6. NY Times
    run_task("The New York Times", selenium_nytimes)

    total_end = time.time()
    duration = total_end - total_start

    print("=" * 60)
    print(f"🎉 所有任务执行完成！总耗时: {duration:.2f} 秒")
    print("=" * 60)

if __name__ == "__main__":
    main()
