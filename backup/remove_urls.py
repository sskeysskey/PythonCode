import re
import sys
import tkinter as tk
from tkinter import filedialog

url_pattern = re.compile(
    r'(?:\s|^)([^ \n]*http[s]?://[^ \n]*(?=\s|$)|'
    r'[^ \n]*www\.[^ \n]*(?=\s|$)|'
    r'[^ \n]*E-mail[^ \n]*(?=\s|$)|'
    r'[^ \n]*\.(com|gov|org|edu|cn|us|html|htm|shtm|uk|xml|js|css|it)[^ \n]*(?=\s|$)|'
    r'[^ \n]+\.[^ \n]+\.[^ \n]+)(?=\s|$)'
)

# 初始化Tkinter，不显示主窗口
root = tk.Tk()
root.withdraw()

# 弹出文件选择对话框，选择源文件
source_file_path = filedialog.askopenfilename(
    title='选择要处理的文件',
    filetypes=[('Text files', '*.txt'), ('All files', '*.*')]
)

# 用户没有选择文件则退出
if not source_file_path:
    print('没有选择文件。')
    sys.exit()

# 读取文件内容
with open(source_file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# 替换掉所有的URL链接
clean_content = re.sub(url_pattern, '', content)

# 弹出文件保存对话框，选择目标文件
target_file_path = filedialog.asksaveasfilename(
    title='保存处理后的文件',
    filetypes=[('Text files', '*.txt'), ('All files', '*.*')]
)

# 用户没有选择文件则退出
if not target_file_path:
    print('没有选择保存的文件。')
    sys.exit()

# 将处理后的内容写入到用户选定的目标文件
with open(target_file_path, 'w', encoding='utf-8') as file:
    file.write(clean_content)

print('所有带有http://或https://前缀以及以www.开头的网址链接已从文件中删除。')