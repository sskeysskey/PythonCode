import os
import pyperclip

def truncate_at_newline(file_path, max_length):
    # 检查文件是否存在
    if not os.path.isfile(file_path):
        print("整个字幕文件翻译完毕。")
        return

    # 读取文件内容
    with open(file_path, 'r', encoding='utf-8') as file:
        file_contents = file.read()

    text_length = len(file_contents)
    
    if text_length > max_length:
        initial_extract = file_contents[:max_length]
        nearest_newline = initial_extract.rfind('\n')
        
        if nearest_newline != -1:
            clipboard_content = file_contents[:nearest_newline]
            remaining_text = file_contents[nearest_newline + 1:]
        else:
            clipboard_content = initial_extract
            remaining_text = file_contents[max_length:]
        
        pyperclip.copy(clipboard_content)

        # 更新文件内容
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(remaining_text)
    else:
        # 如果文本长度小于或等于 3500，直接复制到剪贴板，并删除文件
        pyperclip.copy(file_contents)
        os.remove(file_path)

# 主程序
file_path = "/tmp/newstitle.txt"
max_length = 3500
truncate_at_newline(file_path, max_length)