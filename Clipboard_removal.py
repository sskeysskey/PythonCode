import pyperclip
import re

def clean_ft_clipboard():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()
    
    # 优化后的正则表达式：
    # 匹配从 "Please use the sharing tools" 开始
    # 一直到 "More information can be found at" 以及该行后面的所有非换行字符和紧接着的空白/换行符
    copyright_pattern = r'Please use the sharing tools.*?More information can be found at[^\n]*\s*'
    
    # 使用re.sub移除版权声明
    cleaned_content = re.sub(copyright_pattern, '', clipboard_content, flags=re.DOTALL)
    
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
