import re
import pyperclip  # 用于处理剪贴板内容

def clean_article_text(text):
    """
    清理文章文本，只保留中文新闻内容部分
    
    Args:
        text (str): 原始文本
    Returns:
        str: 清理后的文本
    """
    if not text:
        return None
        
    try:
        # 删除从Close开始到WSJ链接结束的所有内容
        pattern_url = r'Close.*?https://cn\.wsj\.com.*?\n'
        text = re.sub(pattern_url, '', text, flags=re.DOTALL)
        
        # 删除版权信息及之后的所有内容
        pattern_end = r'Copyright ©.*$'
        text = re.sub(pattern_end, '', text, flags=re.DOTALL)
        
        # 清理多余的空行
        text = re.sub(r'\n{3,}', '\n\n', text.strip())
        
        return text
        
    except Exception as e:
        print(f"处理文本时发生错误: {str(e)}")
        return None

def main():
    try:
        # 获取剪贴板内容
        clipboard_text = pyperclip.paste()
        
        # 清理文本
        cleaned_text = clean_article_text(clipboard_text)
        
        if cleaned_text:
            # 将清理后的文本复制回剪贴板
            pyperclip.copy(cleaned_text)
            print("文本已清理并复制到剪贴板！")
        else:
            print("处理文本失败！")
            
    except Exception as e:
        print(f"程序执行出错: {str(e)}")

if __name__ == "__main__":
    main()