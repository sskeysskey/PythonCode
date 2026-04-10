import pyperclip
import re

def clean_clipboard():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()
    
    # 修改正则表达式：
    # 使用 (?:更多阅读|延伸阅读) 来匹配两种情况之一
    # ^ 匹配行首，.* 匹配该行后面的所有字符，(?:\r?\n|$) 匹配换行符或文本末尾
    pattern = r'^(?:更多阅读|延伸阅读|相关阅读|拓展阅读).*(?:\r?\n|$)'
    
    # 使用 re.sub 移除匹配的内容 (使用 re.MULTILINE 让 ^ 匹配每一行的开头)
    cleaned_content = re.sub(pattern, '', clipboard_content, flags=re.MULTILINE)
    
    # 将处理后的内容写回剪贴板
    pyperclip.copy(cleaned_content)
    
    return cleaned_content

# 运行程序
if __name__ == "__main__":
    try:
        cleaned_text = clean_clipboard()
        print("剪贴板内容已清理完成 (已移除“更多阅读”和“延伸阅读”)!")
    except Exception as e:
        print(f"发生错误: {str(e)}")