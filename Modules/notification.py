import argparse
import tkinter as tk

def show_toast(message, duration=2000, bg='green', fg='white', font=('Helvetica', 22)):
    """
    在屏幕右下角弹出一个无边框悬浮窗，duration 毫秒后自动销毁。
    """
    # 新建一个顶层窗口
    root = tk.Tk()
    root.overrideredirect(True)           # 去掉标题栏和边框
    root.attributes('-topmost', True)     # 置顶

    # 传递整个窗口背景色参数
    root.configure(bg=bg)

    # 文字标签
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

    # 计算放在屏幕右下角
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    
    # 水平居中，垂直居中下方偏移
    x = (sw - w) // 2
    # 换成你想要的偏移量
    y = (sh - h) // 2 -300
    
    root.geometry(f'{w}x{h}+{x}+{y}')

    # duration 毫秒后销毁自己
    root.after(duration, root.destroy)
    root.mainloop()

def parse_args():
    p = argparse.ArgumentParser(description="在 macOS 上弹出一个 tkinter “Toast” 提示")
    p.add_argument('message', nargs='+',
                   help='要显示的文字，多词不必加引号')
    p.add_argument('--duration', '-d', type=int, default=2000,
                   help='提示持续时间，单位毫秒 (默认: 2000)')
    p.add_argument('--bg',     type=str, default='green',
                   help='背景色 (默认: green)')
    p.add_argument('--fg',     type=str, default='white',
                   help='文字颜色 (默认: white)')
    p.add_argument('--font',   type=str, default='Helvetica 22',
                   help='字体及大小 (默认: "Helvetica 22")')
    return p.parse_args()

if __name__ == '__main__':
    args = parse_args()
    # message 可能是多词，拼回成一个字符串
    msg = ' '.join(args.message)
    # font 字符串 needs 拆分成 tuple：("FontName", size)
    font_name, font_size = args.font.rsplit(' ', 1)
    try:
        font_tuple = (font_name, int(font_size))
    except:
        font_tuple = ("Helvetica", 22)

    show_toast(
        msg,
        duration=args.duration,
        bg=args.bg,
        fg=args.fg,
        font=font_tuple
    )