import time
import random
import pyautogui
import threading
import tkinter as tk

# --- 配置区域 ---
# 在这里设置自动退出的时间（单位：分钟）
# 如果设置为 0，则不开启自动退出功能
AUTO_EXIT_MINUTES = 130  

# 1. 鼠标移动的核心功能 (保持不变)
def move_mouse_periodically():
    """
    在一个无限循环中，周期性地、缓慢地将鼠标移动到屏幕上的一个随机位置。
    """
    print("后台鼠标移动线程已启动...")
    while True:
        try:
            # 获取屏幕尺寸
            screen_width, screen_height = pyautogui.size()
            
            # 随机生成目标位置，避免移动到屏幕边缘
            x = random.randint(100, screen_width - 100)
            y = random.randint(100, screen_height - 100)
            
            # 缓慢移动鼠标
            pyautogui.moveTo(x, y, duration=1.5) 
            
            # 等待一个随机时长（30-60秒）
            time.sleep(random.randint(30, 60))
            
        except pyautogui.FailSafeException:
            # 当鼠标快速移动到屏幕左上角时，pyautogui会触发此异常以保护用户
            print("PyAutoGUI Fail-Safe 已触发。程序将终止。")
            # 使用 os._exit 可以更强制地退出所有线程
            # 但在这里我们让主线程的GUI来控制退出
            break
        except Exception as e:
            print(f"鼠标移动出错: {str(e)}")
            # 即使出错，也短暂休眠后继续
            time.sleep(30)

# 2. 创建并启动后台线程
# 创建一个线程来运行 move_mouse_periodically 函数
mouse_thread = threading.Thread(target=move_mouse_periodically)
# 设置为守护线程 (daemon=True)。这是关键！
# 当主程序（即GUI窗口）退出时，这个线程会自动被销毁。
mouse_thread.daemon = True
mouse_thread.start()

# --- GUI部分 ---

# 3. 定义关闭窗口的函数
def stop_program(event=None):
    """
    此函数用于销毁GUI窗口，从而结束整个程序。
    (event=None) 是为了让此函数既能被按钮的 command 调用，也能被键盘的 bind 调用。
    """
    print("接收到停止信号或时间已到，正在关闭程序...")
    try:
        root.destroy()
    except tk.TclError:
        # 防止窗口已经被销毁后再次调用报错
        pass

# 4. 创建主窗口
root = tk.Tk()
root.title("鼠标移动控制器")

# 5. 创建GUI控件
# 根据配置生成提示文本
if AUTO_EXIT_MINUTES > 0:
    info_text = f"将在 {AUTO_EXIT_MINUTES} 分钟后自动停止并退出。"

label = tk.Label(root, text=info_text, font=("Arial", 12))
label.pack(padx=20, pady=10)

stop_button = tk.Button(root, text="回车或空格可立即停止", command=stop_program, 
                        font=("Arial", 14, "bold"), bg="salmon", fg="black", 
                        relief=tk.GROOVE, width=20)
stop_button.pack(pady=20, padx=20, ipady=10)

# 6. 绑定键盘事件
# 将回车键 (<Return>) 和空格键 (<space>) 的按下事件也绑定到 stop_program 函数
root.bind('<Return>', stop_program)
root.bind('<space>', stop_program)

# 7. 窗口位置设置 (保持不变)
root.update_idletasks()
window_width = root.winfo_width()
window_height = root.winfo_height()
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
# 计算右下角的坐标
x_coordinate = screen_width - window_width - 20  # 20是与屏幕右边的间距
y_coordinate = screen_height - window_height - 40  # 40是与屏幕底部的间距
root.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")

# 8. 窗口置顶设置 (保持不变)
root.lift()
# root.attributes('-topmost', True) 确保窗口始终保持在所有其他窗口之上。
root.attributes('-topmost', True)
# root.focus_force() 强制将焦点设置到该窗口，使其成为活动窗口。
# 这对于确保窗口一出现就能立即响应键盘事件至关重要，无需用户手动点击。
root.focus_force()

# ==========================================
# 9. 【新增部分】设置自动退出定时器
# ==========================================
if AUTO_EXIT_MINUTES > 0:
    # 将分钟转换为毫秒 (分钟 * 60 * 1000)
    timeout_ms = AUTO_EXIT_MINUTES * 60 * 1000
    # root.after(毫秒, 要执行的函数)
    root.after(timeout_ms, stop_program)
    print(f"定时器已设置：程序将在 {AUTO_EXIT_MINUTES} 分钟后自动退出。")

# 10. 启动GUI事件循环
root.mainloop()
print("程序已成功终止。")
