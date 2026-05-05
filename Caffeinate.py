#!/usr/bin/env python3
import subprocess
import time
import threading

def keep_awake_macos():
    """
    使用 macOS 原生的 caffeinate 命令。
    -i: 防止系统进入闲置休眠
    -d: 防止显示器进入休眠
    """
    print("正在启动 macOS 防休眠模式...")
    # 启动 caffeinate 进程
    # 只要这个进程存在，系统就不会休眠
    process = subprocess.Popen(['caffeinate', '-id'])
    return process

def stop_caffeinate(process):
    """关闭 caffeinate 进程的辅助函数"""
    if process.poll() is None:  # 检查进程是否还在运行
        print("\n[定时器触发] 3小时已到，正在自动关闭防休眠模式...")
        process.terminate()
        print("防休眠模式已关闭。")

# 使用示例
if __name__ == "__main__":
    # 1. 启动防休眠
    proc = keep_awake_macos()
    
    # 2. 设置定时器：3小时 = 10800秒
    # 如果你想测试，可以把 10800 改成 10 (即10秒)
    timer = threading.Timer(10800, stop_caffeinate, args=[proc])
    timer.daemon = True  # 设置为守护线程，确保主程序退出时它也会退出
    timer.start()
    
    print("系统已设置为防休眠，将在 3 小时后自动关闭。")
    print("按 Ctrl+C 可以手动提前停止。")

    try:
        # 你的主逻辑代码...
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # 手动停止时，先取消定时器，防止报错
        timer.cancel()
        # 程序结束时，关闭 caffeinate 进程
        if proc.poll() is None:
            proc.terminate()
        print("\n程序已手动停止。")