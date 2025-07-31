import os
import sys
import threading
import subprocess
from tkinter import Tk, filedialog, Text, Scrollbar, Button, Entry, Label, Toplevel

# 初始化Tkinter，隐藏主窗口
root = Tk()
root.withdraw()

# 弹出选择文件夹对话框
searchFolder = filedialog.askdirectory(
    title="选择要检索的文件夹",
    mustexist=True
)
if not searchFolder:
    root.destroy()
    sys.exit(0)

def open_file(file_path):
    try:
        # 在Unix-like系统中，使用默认程序打开文件
        subprocess.call(["open", file_path])
    except Exception as e:
        print(f"无法打开文件 {file_path}: {e}")

def window_center(win, width, height):
    # 获取屏幕宽度和高度
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    # 计算窗口位置
    x = int((screen_width - width) / 2)
    y = int((screen_height - height) / 2)
    # 设置窗口大小和位置
    win.geometry(f'{width}x{height}+{x}+{y}')

# 自定义输入窗口
def custom_input_window(prompt, callback):
    input_window = Toplevel(root)  # 使用 Toplevel 而不是新的 Tk 实例
    input_window.title("输入")

    # 窗口居中显示相关
    input_window_width = 300
    input_window_height = 100
    window_center(input_window, input_window_width, input_window_height)

    def on_ok():
        keyword = entry.get()
        input_window.destroy()
        callback(keyword)  # 回调函数处理关键词搜索

    def on_cancel():
        input_window.destroy()
        sys.exit(0)

    def on_esc(event):
        on_cancel()

    def on_enter(event):
        on_ok()  # 绑定回车键到 on_ok 函数

    Label(input_window, text=prompt).pack()
    entry = Entry(input_window)
    entry.pack()
    entry.focus_set()  # 激活输入框
    Button(input_window, text="取消", command=on_cancel).pack(side="right")
    Button(input_window, text="确定", command=on_ok).pack(side="right")

    entry.bind('<Return>', on_enter)  # 绑定回车键
    input_window.bind('<Escape>', on_esc)  # 绑定ESC键

# 搜索包含所有特定关键词的文件
def search_files(directory, keywords):
    matched_files = []
    keywords_lower = [keyword.strip().lower() for keyword in keywords.split()]  # 将关键字转化为小写

    for root, dirs, files in os.walk(directory):
        for dir_name in dirs:
            if dir_name.endswith('.workflow'):
                handle_workflow_dir(root, dir_name, keywords_lower, matched_files)

        for name in files:
            handle_file(root, name, keywords_lower, matched_files)

    return matched_files

def handle_workflow_dir(root, dir_name, keywords_lower, matched_files):
    workflow_path = os.path.join(root, dir_name)
    try:
        wflow_path = os.path.join(workflow_path, 'contents/document.wflow')
        with open(wflow_path, 'r') as file:
            content = file.read().lower()
        if all(keyword_lower in content for keyword_lower in keywords_lower):
            matched_files.append(workflow_path)
    except Exception as e:
        print(f"Error reading {wflow_path}: {e}")

def handle_file(root, name, keywords_lower, matched_files):
    item_path = os.path.join(root, name)
    if item_path.endswith('.scpt'):
        try:
            content = subprocess.check_output(['osadecompile', item_path], text=True).lower()
            if all(keyword_lower in content for keyword_lower in keywords_lower):
                matched_files.append(item_path)
        except Exception as e:
            print(f"Error decompiling {item_path}: {e}")
    elif item_path.endswith(('.txt', '.py', '.json', '.js', '.css', '.html', '.csv')):
        try:
            with open(item_path, 'r') as file:
                content = file.read().lower()
            if all(keyword_lower in content for keyword_lower in keywords_lower):
                matched_files.append(item_path)
        except Exception as e:
            print(f"Error reading {item_path}: {e}")

# 自定义消息框展示结果
def show_results(results):
    # 新建窗口
    result_window = Toplevel(root)
    result_window.title("搜索结果")

    # 将窗口居中放置
    window_center(result_window, 700, 600)  # 假设您想让窗口大小为 700x600
    
    # 创建滚动条
    scrollbar = Scrollbar(result_window)
    scrollbar.pack(side="right", fill="y")
    
    # 创建文本框用于显示结果，设置宽度加倍
    text = Text(result_window, width=150, height=25, yscrollcommand=scrollbar.set)
    text.pack(side="left", fill="both")

    # 定义文本样式标签
    text.tag_configure('directory_tag', foreground='yellow', font=('Helvetica', '24', 'bold'))  # 用于目录的标签
    text.tag_configure('file_tag', foreground='orange', font=('Helvetica', '20'))  # 用于文件的标签
    text.tag_configure('clicked', foreground='grey', underline=False)  # 用于已点击文件的标签
    
    # 将滚动条关联到文本框
    scrollbar.config(command=text.yview)

    # 清除文本框中的旧内容
    text.delete(1.0, "end")

    # 绑定 ESC 键到关闭窗口和结束程序的函数
    result_window.bind('<Escape>', lambda e: (result_window.destroy(), sys.exit(0)))

    # 定义打开文件并更改标签颜色的函数
    def open_file_and_change_tag_color(path, tag_name):
        open_file(path)  # 调用原有的打开文件函数
        text.tag_configure(tag_name, foreground='grey', underline=False)  # 更改标签颜色为灰色，并去除下划线
    
    # 插入文本到文本框
    if results:
        directory = os.path.dirname(results[0])  # 假设所有文件都在同一个目录下
        text.insert("end", directory + "\n", 'directory_tag')  # 以橙色加粗字体插入目录路径
        
        for file_path in results:
            file_name = os.path.basename(file_path)  # 提取文件名
            tag_name = "clickable_" + str(hash(file_path))  # 生成一个基于文件路径的唯一标签名
            text.insert("end", file_name + "\n", ('file_tag', tag_name))  # 插入文件名，并附上标签
            text.tag_bind(tag_name, "<Button-1>", lambda event, path=file_path, tag=tag_name: open_file_and_change_tag_color(path, tag))  # 为标签绑定点击事件
            text.tag_configure(tag_name, foreground='orange', underline=True)  # 设置标签样式为可点击链接的样式
    else:
        text.insert("end", "没有找到包含关键词的文件。", 'file_tag')

def threaded_search_files(directories, keywords, callback):
    results = search_files(directories, keywords)
    root.after(0, callback, results)

custom_input_window("请输入要检索的字符串内容：", 
                    lambda keyword: threading.Thread(target=threaded_search_files, args=(searchFolder, keyword, show_results)).start())

root.mainloop()  # 最后，启动主事件循环