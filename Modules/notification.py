import argparse
import os
import signal
import tkinter as tk

# 记录“常驻”提示的进程 PID，新提示出现时用它来结束旧的常驻提示
PID_FILE = '/tmp/notification_sticky.pid'
MOUSE_THRESHOLD = 3   # 鼠标移动超过这个像素数才关闭（防止抖动误判）


def _read_pid():
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def kill_previous_sticky():
    """结束上一个常驻提示（如果存在）"""
    pid = _read_pid()
    if pid and pid != os.getpid():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass  # 进程已经不存在
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def write_pid():
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


def clear_pid():
    # 只删除属于自己的 PID 文件，避免误删新提示写入的文件
    if _read_pid() == os.getpid():
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def show_toast(message, duration=2000, bg='green', fg='white',
               font=('Helvetica', 22), sticky=False):
    # 新建一个顶层窗口
    root = tk.Tk()
    root.overrideredirect(True)           # 去掉标题栏和边框
    root.attributes('-topmost', True)     # 置顶
    root.configure(bg=bg)

    label = tk.Label(
        root,
        text=message,
        bg=bg,
        fg=fg,
        font=font,
        justify='left',
        anchor='w',
        padx=10,
        pady=5
    )
    label.pack()

    # 计算位置（保持你原来的偏移设置）
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    # --- 修改这里 ---
    # 向右移动：增加 x_offset
    x_offset = 130
    x = (sw - w) // 2 + x_offset

    # 向下移动：增大 y_offset（原来是 -200）
    y_offset = -200
    y = (sh - h) // 2 + y_offset

    root.geometry(f'{w}x{h}+{x}+{y}')

    if sticky:
        # 常驻模式：鼠标移动后关闭
        state = {'origin': None}

        def watch_mouse():
            mx, my = root.winfo_pointerxy()
            if state['origin'] is None:
                state['origin'] = (mx, my)   # 第一次记录基准位置
            else:
                ox, oy = state['origin']
                if abs(mx - ox) > MOUSE_THRESHOLD or abs(my - oy) > MOUSE_THRESHOLD:
                    root.destroy()
                    return
            root.after(150, watch_mouse)

        root.after(500, watch_mouse)     # 等 0.5 秒后再开始监听
    else:
        # 普通模式：duration 毫秒后自动消失
        root.after(duration, root.destroy)

    root.mainloop()


def parse_args():
    p = argparse.ArgumentParser(description="在 macOS 上弹出一个 tkinter “Toast” 提示")
    p.add_argument('message', nargs='+',
                   help='要显示的文字，多词不必加引号')
    p.add_argument('--duration', '-d', type=int, default=2000,
                   help='提示持续时间，单位毫秒 (默认: 2000)，--sticky 时无效')
    p.add_argument('--bg', type=str, default='green',
                   help='背景色 (默认: green)')
    p.add_argument('--fg', type=str, default='white',
                   help='文字颜色 (默认: white)')
    p.add_argument('--font', type=str, default='Helvetica 22',
                   help='字体及大小 (默认: "Helvetica 22")')
    p.add_argument('--sticky', action='store_true',
                   help='常驻显示，直到鼠标移动或被新提示替换')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    msg = ' '.join(args.message)
    font_name, font_size = args.font.rsplit(' ', 1)
    try:
        font_tuple = (font_name, int(font_size))
    except:
        font_tuple = ("Helvetica", 22)

    # 任何新提示出现时，都先结束上一条常驻提示
    kill_previous_sticky()
    if args.sticky:
        write_pid()

    try:
        show_toast(
            msg,
            duration=args.duration,
            bg=args.bg,
            fg=args.fg,
            font=font_tuple,
            sticky=args.sticky
        )
    finally:
        clear_pid()