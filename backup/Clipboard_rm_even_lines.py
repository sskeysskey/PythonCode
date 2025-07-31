import pyperclip

def remove_even_lines_from_clipboard():
    blacklist_file_path = "/Users/yanzhang/Documents/python_code/Resource/blacklist_topgainer.txt"
    
    # 从剪贴板获取内容
    clipboard_content = pyperclip.paste()
    
    # 按行分割内容成为一个列表
    lines = clipboard_content.split('\n')
    
    # 保留奇数行
    odd_lines = [line for index, line in enumerate(lines) if index % 2 == 0]

    # 读取黑名单文件的内容，并分割成行
    with open(blacklist_file_path, 'r') as file:
        blacklist = file.read().split('\n')

    # 移除与黑名单匹配的行
    filtered_lines = [line for line in odd_lines if line not in blacklist]
    
    # 将处理后的内容转换回字符串
    new_content = '\n'.join(filtered_lines)

    # 将新内容复制回剪贴板
    pyperclip.copy(new_content)

# 调用函数执行
remove_even_lines_from_clipboard()