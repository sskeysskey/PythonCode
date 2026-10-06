import pyperclip
import re

def clean_ft_clipboard():
    # 获取剪贴板内容
    clipboard_content = pyperclip.paste()
    
    # ------------------ 新增规则 ------------------
    # 如果出现了 "This article is up-to-date as"
    if "This article is up-to-date as" in clipboard_content:
        # 推荐方案：清除它及前面的所有内容，并且把该行剩余的内容（如 " of October 4 2026."）和紧随其后的换行符一起删掉
        # ^.* 匹配开头到该短语的所有内容，[^\n]*\s* 匹配该行剩余字符及后面的空行
        uptodate_pattern = r'^.*?This article is up-to-date as[^\n]*\s*'
        clipboard_content = re.sub(uptodate_pattern, '', clipboard_content, flags=re.DOTALL)
        
        # 【备选方案】：如果你严格只要删到 "This article is up-to-date as" 为止（保留后面的日期），取消下面这行注释即可：
        # clipboard_content = re.sub(r'^.*?This article is up-to-date as', '', clipboard_content, flags=re.DOTALL).lstrip()
    # ----------------------------------------------
    
    # 原有逻辑：移除版权声明
    copyright_pattern = r'Please use the sharing tools.*?More information can be found at[^\n]*\s*'
    cleaned_content = re.sub(copyright_pattern, '', clipboard_content, flags=re.DOTALL)
    
    # 去除首尾多余的空白/换行
    cleaned_content = cleaned_content.strip()
    
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