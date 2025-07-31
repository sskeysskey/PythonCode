import re
import pyperclip
import tkinter as tk
from tkinter import messagebox # 用于显示错误信息
from tkinter.font import Font

# --- 常量定义 ---
FONT_FAMILY = "Helvetica"
FONT_SIZE = 24
TEXT_WIDGET_HEIGHT = 15
TEXT_WIDGET_WIDTH = 20  # 稍微增加了宽度以更好地显示内容，您可以根据需要调整
WINDOW_TITLE = "剪贴板分析"

# 颜色标签定义
COLOR_TAGS = {
    'total': ('red', "总共字符："),
    'chinese': ('yellow', "中文字："),
    'english': ('orange', "英文单词："),
    'digit': ('white', "数字数量："), # Tkinter Text widget 默认背景通常是白色，白色前景可能看不清，可考虑更换
    'symbol': ('green', "符号数量："),
    'line': ('cyan', "总行数："), # 修改了行数颜色以便区分
    'pure_line': ('cyan', "除空行行数：") # 与总行数使用相同颜色
}
# 注意：如果您的Tkinter主题背景是浅色的，'white' 可能不是一个好的选择，可以考虑 'black' 或其他深色。
# 我这里暂时保留 'white'，您可以根据您的系统主题调整。如果Text控件背景是默认的白色，'white'前景将不可见。
# 建议将 'white' 改为 'black' 或其他对比度高的颜色。例如：'digit': ('black', "数字数量：")

def analyze_clipboard_content(content: str) -> dict:
    """
    分析给定的文本内容，返回包含各项统计数据的字典。
    """
    analysis = {}
    analysis['total_characters'] = len(content)
    analysis['num_chinese_characters'] = len(re.findall(r'[\u4e00-\u9fff]', content))
    analysis['num_english_words'] = len(re.findall(r'\b[A-Za-z]+\b', content))
    analysis['num_digits'] = len(re.findall(r'\d', content))
    analysis['num_symbols'] = sum(not char.isalnum() and not char.isspace() for char in content)
    analysis['num_lines_all'] = content.count('\n') + 1 if content else 0
    analysis['num_lines_pure'] = sum(1 for line in content.splitlines() if line.strip()) if content else 0
    return analysis

def on_escape(event=None, root_window=None):
    """关闭窗口的回调函数"""
    if root_window:
        root_window.destroy()

def center_window(win):
    """将窗口居中显示"""
    win.update_idletasks()  # 确保获取到正确的窗口尺寸
    width = win.winfo_width()
    height = win.winfo_height()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    # 将窗口置于屏幕中央偏上一些（约1/3处）
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 3) - (height // 2)
    win.geometry(f'{width}x{height}+{x}+{y}')

def create_and_run_gui(clipboard_content: str):
    """
    创建并运行Tkinter GUI来显示剪贴板分析结果。
    """
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.lift()  # 将窗口置于顶层
    root.focus_force() # 强制窗口获取焦点

    # 设置字体
    custom_font = Font(family=FONT_FAMILY, size=FONT_SIZE)

    # 创建 Text 控件来显示信息
    # 注意：Text控件的width和height单位是字符。
    # width=15 对于某些标签+数字可能略窄，尤其是字体较大时。
    # 我已将其增加到 TEXT_WIDGET_WIDTH (20)，您可以按需调整。
    text_widget = tk.Text(root, font=custom_font, height=TEXT_WIDGET_HEIGHT, width=TEXT_WIDGET_WIDTH, wrap=tk.WORD)
    text_widget.pack(pady=10, padx=10, fill="both", expand=True)

    # 分析剪贴板内容
    analysis_results = analyze_clipboard_content(clipboard_content)

    # 定义显示项目及其顺序、标签和对应的结果键
    display_items_config = [
        ('total', 'total_characters'),
        ('chinese', 'num_chinese_characters'),
        ('english', 'num_english_words'),
        ('digit', 'num_digits'),
        ('symbol', 'num_symbols'),
        ('line', 'num_lines_all'),
        ('pure_line', 'num_lines_pure'),
    ]

    # 配置颜色标签
    for tag_key, (color, _) in COLOR_TAGS.items():
        text_widget.tag_configure(tag_key + "_color", foreground=color) # 给tag名称加上后缀以示区分

    # 插入文本并设置样式
    for tag_key, result_key in display_items_config:
        color_name, label_text = COLOR_TAGS[tag_key]
        value = analysis_results.get(result_key, 0) # 从分析结果中获取值
        
        # 插入标签文本
        text_widget.insert('end', label_text + " ")
        # 插入值并应用颜色标签
        text_widget.insert('end', f"{value}\n\n", tag_key + "_color")


    # 禁止 Text 控件的编辑功能
    text_widget.config(state='disabled')

    # 绑定 Esc 键到 on_escape 函数
    # 使用 lambda 传递 root 窗口实例给 on_escape
    root.bind('<Escape>', lambda event, r=root: on_escape(event, r))

    # 窗口居中
    center_window(root)

    # 运行 Tkinter 事件循环
    root.mainloop()

def main():
    """
    主函数，获取剪贴板内容并启动GUI。
    """
    try:
        clipboard_content = pyperclip.paste()
        if not clipboard_content:
            # 如果剪贴板为空，可以提示用户或直接显示全0的结果
            print("剪贴板为空。") # 命令行提示
            # 你也可以在这里用tkinter弹窗提示
            # messagebox.showinfo("提示", "剪贴板为空。")
            # 为空也继续显示，各项统计为0
    except pyperclip.PyperclipException as e:
        # 处理pyperclip可能发生的错误，例如无法访问剪贴板
        print(f"无法访问剪贴板: {e}")
        messagebox.showerror("错误", f"无法访问剪贴板: {e}\n请确保已安装剪贴板工具 (如 xclip 或 xsel on Linux)。")
        return # 无法获取内容则退出

    create_and_run_gui(clipboard_content)

if __name__ == "__main__":
    main()