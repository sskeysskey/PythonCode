import pyperclip
import re

def clean_ft_clipboard():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()
    
    # 1. 移除版权声明的正则表达式
    # 匹配从 "Please use the sharing tools" 开始
    # 一直到 "More information can be found at" 以及该行后面的所有非换行字符和紧接着的空白/换行符
    copyright_pattern = r'Please use the sharing tools.*?More information can be found at[^\n]*\s*'
    
    # 使用re.sub移除版权声明 (使用 re.DOTALL 让 . 匹配换行符)
    cleaned_content = re.sub(copyright_pattern, '', clipboard_content, flags=re.DOTALL)
    
    # 2. 移除以“更多阅读”、“延伸阅读”或“拓展阅读”开头的段落
    # ^ 匹配行首
    # (?:更多阅读|延伸阅读|拓展阅读) 匹配这三个词中的任意一个
    # .* 匹配该行后面的所有字符
    # (?:\r?\n|$) 匹配换行符或文本末尾，连同换行符一起删掉
    more_reading_pattern = r'^(?:更多阅读|延伸阅读|拓展阅读).*(?:\r?\n|$)'
    
    # 使用re.sub移除这些段落 (使用 re.MULTILINE 让 ^ 匹配每一行的开头)
    cleaned_content = re.sub(more_reading_pattern, '', cleaned_content, flags=re.MULTILINE)
    
    # 将处理后的内容写回剪贴板
    pyperclip.copy(cleaned_content)
    
    return cleaned_content

# 运行程序
if __name__ == "__main__":
    try:
        cleaned_text = clean_ft_clipboard()
        print("剪贴板内容已清理完成!")
    except Exception as e:
        print(f"发生错误: {str(e)}")