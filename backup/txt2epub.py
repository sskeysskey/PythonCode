from ebooklib import epub
import re
import os
import glob

def clean_and_format_text(txt_path):
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 按行分割内容
        lines = content.split('\n')
        cleaned_lines = []
        current_text = []
        
        for line in lines:
            # 跳过空行
            if not line.strip():
                if current_text:
                    cleaned_lines.append('\n'.join(current_text))
                    current_text = []
                continue
                
            # 如果是URL行
            if line.startswith('http'):
                # 处理不同格式的URL
                source = None
                if 'cn.wsj.com' in line:
                    source = 'CN.WSJ'
                elif 'www.ft.com' in line:
                    source = 'FT'
                elif 'www.wsj.com' in line:
                    source = 'WSJ'
                elif 'www.economist.com' in line:
                    source = 'ECONOMIST'
                elif 'ww.bloomberg.com' in line:
                    source = 'BLOOMBERG'
                elif 'www.technologyreview.com' in line:
                    source = 'TechnologyReview'
                
                if source:
                    if current_text:
                        cleaned_lines.append('\n'.join(current_text))
                        current_text = []
                    current_text.append(source.upper())  # 转换为大写
                continue
            
            # 普通文本行
            current_text.append(line)
        
        # 添加最后一段文本
        if current_text:
            cleaned_lines.append('\n'.join(current_text))
        
        # 合并所有处理后的内容
        final_content = '\n\n'.join(cleaned_lines)
        
        # 确保段落之间的空行得以保留
        final_content = re.sub(r'\n{3,}', '\n\n', final_content)
        
        return final_content.strip()
        
    except Exception as e:
        print(f"处理文本时出现错误: {str(e)}")
        return None

def txt_to_epub_with_formatting(txt_path, epub_path):
    try:
        # 获取清理后的内容
        content = clean_and_format_text(txt_path)
        if not content:
            return False
            
        # 创建epub书籍
        book = epub.EpubBook()
        
        # 设置元数据
        book.set_identifier('id123456')
        book.set_title(os.path.splitext(os.path.basename(txt_path))[0])
        book.set_language('zh-CN')
        
        # 将换行转换为HTML段落标签
        html_content = ''
        for paragraph in content.split('\n\n'):
            if paragraph.strip():
                html_content += f'<p>{paragraph.replace("\n", "<br/>")}</p>\n'
        
        # 创建章节
        chapter = epub.EpubHtml(title='Content',
                               file_name='content.xhtml',
                               lang='zh-CN')
        
        # 添加CSS样式以确保正确的段落间距
        style = '''
            p {
                margin: 1em 0;
                line-height: 1.5;
            }
        '''
        css = epub.EpubItem(uid="style",
                           file_name="style.css",
                           media_type="text/css",
                           content=style)
        
        book.add_item(css)
        chapter.add_item(css)
        
        chapter.content = f'<html><head></head><body>{html_content}</body></html>'
        
        # 添加章节
        book.add_item(chapter)
        
        # 创建目录
        book.toc = (epub.Link('content.xhtml', 'Content', 'content'),)
        
        # 添加导航
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        # 定义阅读顺序
        book.spine = ['nav', chapter]
        
        # 生成epub
        epub.write_epub(epub_path, book, {})
        
        return True
        
    except Exception as e:
        print(f"转换过程中出现错误: {str(e)}")
        return False

def find_all_news_files(directory):
    pattern = os.path.join(directory, "News_*.txt")
    # pattern = os.path.join(directory, "Play*.txt")
    return sorted(glob.glob(pattern))

def get_epub_path(txt_path):
    # 获取目录路径和文件名
    directory = os.path.dirname(txt_path)
    filename = os.path.basename(txt_path)
    
    # 将.txt替换为.epub
    epub_filename = os.path.splitext(filename)[0] + '.epub'
    
    return os.path.join(directory, epub_filename)

def needs_conversion(txt_path, epub_path):
    # 如果epub文件不存在，需要转换
    if not os.path.exists(epub_path):
        return True
    
    # 如果txt文件比epub文件新，需要转换
    txt_mtime = os.path.getmtime(txt_path)
    epub_mtime = os.path.getmtime(epub_path)
    return txt_mtime > epub_mtime

def process_all_files(directory):
    # 获取所有News_开头的txt文件
    txt_files = find_all_news_files(directory)
    
    if not txt_files:
        print(f"在 {directory} 目录下没有找到以News_开头的txt文件")
        return
    
    # 统计处理结果
    converted = 0
    skipped = 0
    failed = 0
    
    # 处理每个文件
    for txt_file in txt_files:
        epub_file = get_epub_path(txt_file)
        
        try:
            if needs_conversion(txt_file, epub_file):
                print(f"正在处理: {os.path.basename(txt_file)}")
                if txt_to_epub_with_formatting(txt_file, epub_file):
                    print(f"成功转换: {os.path.basename(txt_file)} -> {os.path.basename(epub_file)}")
                    converted += 1
                else:
                    print(f"转换失败: {os.path.basename(txt_file)}")
                    failed += 1
            else:
                print(f"跳过已存在的文件: {os.path.basename(txt_file)}")
                skipped += 1
                
        except Exception as e:
            print(f"处理 {os.path.basename(txt_file)} 时出错: {str(e)}")
            failed += 1
    
    # 打印统计信息
    print("\n处理完成:")
    print(f"成功转换: {converted} 个文件")
    print(f"跳过处理: {skipped} 个文件")
    print(f"转换失败: {failed} 个文件")

def move_cnh_file(source_dir):
    """
    移动第一个找到的TodayCNH_文件到backup目录
    
    Args:
        source_dir (str): 源目录路径
        
    Returns:
        bool: 移动是否成功
    """
    try:
        # 构建源文件搜索模式
        cnh_pattern = os.path.join(source_dir, "TodayCNH_*.html")
        cnh_files = glob.glob(cnh_pattern)
        
        if not cnh_files:
            print("没有找到TodayCNH_开头的文件")
            return False
            
        # 获取第一个匹配的文件
        source_file = cnh_files[0]
        
        # 构建目标目录路径
        backup_dir = os.path.join(source_dir, "backup", "backup")
        
        # 确保目标目录存在
        os.makedirs(backup_dir, exist_ok=True)
        
        # 构建目标文件路径
        target_file = os.path.join(backup_dir, os.path.basename(source_file))
        
        # 移动文件
        os.rename(source_file, target_file)
        print(f"成功移动文件: {os.path.basename(source_file)} -> {backup_dir}")
        return True
        
    except Exception as e:
        print(f"移动文件时出错: {str(e)}")
        return False

if __name__ == "__main__":
    news_directory = "/Users/yanzhang/Coding/News/"
    # news_directory = "/Users/yanzhang/Coding"
    
    # 处理epub转换
    process_all_files(news_directory)
    
    # 移动TodayCNH_文件
    move_cnh_file(news_directory)