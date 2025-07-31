import time
import random
import pyautogui
import threading
import tkinter as tk
import sys

# 1. 鼠标移动的核心功能 (与您原来的代码基本一致)
# 这个函数将在一个独立的后台线程中运行
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
            
            # 缓慢移动鼠标到随机位置
            # print(f"正在移动鼠标到: ({x}, {y})") # 如果需要调试，可以取消此行注释
            pyautogui.moveTo(x, y, duration=1.5) # 稍微增加时长，移动更平滑
            
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
    print("接收到停止信号，正在关闭程序...")
    root.destroy()
    # 由于mouse_thread是守护线程，当这个主线程结束后，它会自动终止。
    # sys.exit() 也可以确保退出，但destroy()通常足够了。

# 4. 创建主窗口
root = tk.Tk()
root.title("鼠标移动控制器")

# 5. 创建GUI控件
# 创建一个标签，用于显示提示信息
label = tk.Label(root, text="\n鼠标正在后台随机移动...\n\n点击下方按钮或按“回车/空格”键可立即停止。\n", font=("Arial", 12))
label.pack(padx=20, pady=10)

# 创建一个按钮，点击时调用 stop_program 函数
stop_button = tk.Button(root, text="停止移动并退出", command=stop_program, font=("Arial", 14, "bold"), bg="salmon", fg="black", relief=tk.GROOVE, width=20)
stop_button.pack(pady=20, padx=20, ipady=10) # ipady 增加按钮内部垂直填充

# 6. 绑定键盘事件
# 将回车键 (<Return>) 和空格键 (<space>) 的按下事件也绑定到 stop_program 函数
root.bind('<Return>', stop_program)
root.bind('<space>', stop_program)

# 7. 将窗口居中显示
root.update_idletasks() # 更新窗口信息以获取准确尺寸
window_width = root.winfo_width()
window_height = root.winfo_height()
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
x_coordinate = int((screen_width / 2) - (window_width / 2))
y_coordinate = int((screen_height / 2) - (window_height / 2))
root.geometry(f"{window_width}x{window_height}+{x_coordinate}+{y_coordinate}")

# 8. 【修改部分】将窗口强制置于最前台并激活
# --------------------------------------------------------------------
# root.lift() 将窗口提升到窗口堆叠顺序的顶部。
root.lift()
# root.attributes('-topmost', True) 确保窗口始终保持在所有其他窗口之上。
root.attributes('-topmost', True)
# root.focus_force() 强制将焦点设置到该窗口，使其成为活动窗口。
# 这对于确保窗口一出现就能立即响应键盘事件至关重要，无需用户手动点击。
root.focus_force()
# --------------------------------------------------------------------


# 9. 启动GUI事件循环
# 这会显示窗口并等待用户交互。代码会在这里“暂停”，直到窗口被关闭。
root.mainloop()

print("程序已成功终止。")