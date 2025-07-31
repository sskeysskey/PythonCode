import pyperclip

def remove_duplicates_from_clipboard():
    # 从剪贴板获取内容
    clipboard_content = pyperclip.paste()
    
    # 按行分割内容，并转换为集合去重
    lines = clipboard_content.split('\n')
    unique_lines = set(lines)
    
    # 将去重后的内容转换回字符串
    new_content = '\n'.join(unique_lines)
    
    # 将新内容写回剪贴板
    pyperclip.copy(new_content)

# 调用函数执行
remove_duplicates_from_clipboard()