import os
import pyperclip

file_path = '/tmp/article_bloomberg.txt'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()
pyperclip.copy(content)

# 删除文件
os.remove(file_path)