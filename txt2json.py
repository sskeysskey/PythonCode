import re
import os
import hashlib
import glob
import shutil
import json
import html
import subprocess
import platform  # <--- 新增：用于判断操作系统
from urllib.parse import urlsplit, urlunsplit
# ------  整个pdf逻辑部分开始  ------#
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from PIL import Image
import math

# ================= 配置区域 =================

# 1. 动态获取当前用户的主目录
USER_HOME = os.path.expanduser("~")

# 2. 定义 Coding 根目录
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")

# 3. 定义 Downloads 目录
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

# 4. 定义 News 相关目录
NEWS_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
LOCAL_SERVER_DIR = os.path.join(BASE_CODING_DIR, "LocalServer", "Resources", "ONews")

# ===========================================

MAJOR_SITES = {s.upper() for s in (
    'FT','WSJ','BLOOMBERG','REUTERS','NYTIMES',
    'WASHINGTONPOST','ECONOMIST','TECHNOLOGYREVIEW', 'WSJCN', 'RFI', 'DW', 'OTHER'
)}

def alert_and_exit(message):
    """
    跨平台弹窗提醒；若失败则退回到打印。随后立即退出程序。
    """
    try:
        # <--- 修改：区分操作系统
        if platform.system() == 'Darwin':  # macOS
            subprocess.run([
                "osascript", "-e",
                f'display alert "缺少必要文件" message "{message}" as critical'
            ], check=False)
        else:
            # Windows/Linux 可以打印醒目日志，或者使用 ctypes (可选)
            print("\n" + "!" * 50)
            print(f"CRITICAL ERROR: {message}")
            print("!" * 50 + "\n")
    except Exception:
        pass
    
    # 无论如何都要打印并退出
    print(f"Alert: {message}")
    raise SystemExit(1)

def find_today_cnh_html(today, news_directory):
    """
    查找 backup/backup 目录 和 news_directory 根目录下的 TodayCNH_<today>.html。
    返回所有找到的文件路径列表。
    """
    paths = []
    
    # 1. 检查备份目录：News/backup/backup
    backup_dir = os.path.join(news_directory, "backup", "backup")
    candidate1 = os.path.join(backup_dir, f"TodayCNH_{today}.html")
    # 如果备份目录里有（可能是之前运行产生的），加上它
    if os.path.exists(candidate1):
        paths.append(candidate1)
    
    # 2. 检查根目录：News/ (这是当前最新的)
    candidate2 = os.path.join(news_directory, f"TodayCNH_{today}.html")
    # <--- 修改点：这里把 elif 改成了 if，确保即便备份存在，也会去读新的文件
    if os.path.exists(candidate2):
        paths.append(candidate2)
        
    # 额外：如果备份目录下有重命名过的文件（如 TodayCNH_260131_1.html），也可以尝试读取
    # 这样能保证一天内多次运行的所有元数据都被加载
    extra_backups = glob.glob(os.path.join(backup_dir, f"TodayCNH_{today}_*.html"))
    paths.extend(extra_backups)
    
    # 去重（防止路径重复）
    return list(set(paths))

def get_pdf_path(txt_path):
    directory = os.path.dirname(txt_path)
    filename = os.path.basename(txt_path)
    pdf_filename = os.path.splitext(filename)[0] + '.pdf'
    return os.path.join(directory, pdf_filename)

def needs_conversion(txt_path, pdf_path):
    if not os.path.exists(pdf_path):
        return True
    txt_mtime = os.path.getmtime(txt_path)
    pdf_mtime = os.path.getmtime(pdf_path)
    return txt_mtime > pdf_mtime

def find_images_for_content(content, url_images):
    article_images = []
    articles = []
    current_article = []
    lines = content.strip().split('\n')
    
    for line in lines:
        if line.startswith('http'):
            if current_article:
                articles.append('\n'.join(current_article))
                current_article = []
        current_article.append(line)
    
    if current_article:
        articles.append('\n'.join(current_article))
    
    print("\n找到的文章和URL:")
    for article in articles:
        url_match = re.search(r'(https?://[^\s]+)', article)
        if url_match:
            url = url_match.group(1)
            print(f"\nArticle URL: {url}")
            
            for article_url, images in url_images.items():
                # 使用更宽松的匹配，检查 URL 是否相互包含
                if url in article_url or article_url in url:
                    print(f"Matched with: {article_url}")
                    print(f"Images found: {images}")
                    article_images.append((article, images))
                    break # 找到匹配后即可停止内层循环

    return article_images

def distribute_images_in_content(content, url_images):
    if not url_images:
        return content
    
    article_images = find_images_for_content(content, url_images)
    
    print("\n开始分布图片:")
    print(f"找到 {len(article_images)} 篇文章需要处理")
    
    # 找出所有文章块，包括没有图片的文章
    all_articles = []
    current_article = []
    lines = content.strip().split('\n')
    
    for line in lines:
        if line.startswith('http') and current_article:
            all_articles.append('\n'.join(current_article))
            current_article = []
        current_article.append(line)
    
    if current_article:
        all_articles.append('\n'.join(current_article))
    
    # 处理所有文章，添加网站名称
    processed_content = []
    for article in all_articles:
        lines = article.strip().split('\n')
        # 用正则提取文章中第一个出现的 URL
        url_match = re.search(r'(https?://[^\s]+)', article)
        url_line = url_match.group(1) if url_match else ''
        if not url_line:
            processed_content.append(article)
            continue
            
        # 提取网站名称
        site_name = extract_site_name(url_line)
        
        # 查找这篇文章是否有图片
        article_with_images = None
        for art, imgs in article_images:
            art_url_match = re.search(r'(https?://[^\s]+)', art)
            art_url = art_url_match.group(1) if art_url_match else ''
            if art_url == url_line:
                article_with_images = (art, imgs)
                break
                
        # 先添加网站名称，然后再添加文章内容
        processed_content.append(f"{site_name}\n")
                
        if article_with_images:
            # 处理有图片的文章
            art, imgs = article_with_images
            content_lines = [line for line in lines if line != url_line and line.strip()]
            
            # 首先添加URL
            new_content = [url_line]
            if imgs:
                new_content.append(f"--IMAGE_PLACEHOLDER_{imgs[0]}--")
            
            # 处理剩余的图片
            remaining_images = imgs[1:] if len(imgs) > 1 else []
            
            if remaining_images and content_lines:
                # 根据剩余图片数量将内容均匀分段
                segment_size = max(1, len(content_lines) // (len(remaining_images) + 1))
                
                current_segment = []
                image_index = 0
                
                for i, line in enumerate(content_lines):
                    current_segment.append(line)
                    
                    # 当段落达到预期大小或是最后一行时插入图片
                    if (len(current_segment) >= segment_size or i == len(content_lines) - 1) and image_index < len(remaining_images):
                        # 添加当前段落内容，保持原有的换行
                        new_content.extend(current_segment)
                        # 添加图片占位符
                        new_content.append(f"--IMAGE_PLACEHOLDER_{remaining_images[image_index]}--")
                        # 重置当前段落
                        current_segment = []
                        image_index += 1
                
                # 添加剩余的段落内容
                if current_segment:
                    new_content.extend(current_segment)
                
                # 如果还有未使用的图片，在末尾添加
                while image_index < len(remaining_images):
                    new_content.append(f"--IMAGE_PLACEHOLDER_{remaining_images[image_index]}--")
                    image_index += 1
            else:
                # 如果没有剩余图片，直接添加所有内容行，保持原有换行
                new_content.extend(content_lines)
            
            processed_content.append('\n'.join(new_content))
        else:
            # 处理没有图片的文章，保持原样
            processed_content.append(article)
    
    # 移除最后一个网站名称标记的换行符（因为是最后一篇文章）
    if processed_content and processed_content[-1].strip() in {'FT','WSJ','BLOOMBERG','REUTERS','NYTIMES',
    'WASHINGTONPOST','ECONOMIST','TECHNOLOGYREVIEW', 'WSJCN', 'RFI', 'DW', 'OTHER'}:
        processed_content[-1] = processed_content[-1].strip()
    
    # 合并所有处理后的内容
    return '\n'.join(processed_content)

def clean_and_format_text(txt_path, article_copier_path, image_dir):
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        print(f"\n处理文件: {txt_path}")
        
        url_images = parse_article_copier(article_copier_path)
        cleaned_content = distribute_images_in_content(content, url_images)

        # 使用集合来存储唯一的图片路径，避免重复
        unique_image_paths = set()
        
        print("\n找到的图片占位符:")
        # 跟踪所有占位符，不论图片是否存在
        all_placeholders = []
        
        for img_placeholder in re.finditer(r'--IMAGE_PLACEHOLDER_(.*?)--(?:\n|$)', cleaned_content):
            img_name = img_placeholder.group(1).strip()
            # <--- 路径拼接
            img_path = os.path.join(image_dir, img_name)
            all_placeholders.append(img_name)
            
            print(f"Image placeholder: {img_name}")
            print(f"Full path: {img_path}")
            print(f"Exists: {os.path.exists(img_path)}")
            
            if os.path.exists(img_path):
                unique_image_paths.add(img_path)
            else:
                # 移除不存在图片的占位符
                cleaned_content = cleaned_content.replace(f"--IMAGE_PLACEHOLDER_{img_name}--", "")
                print(f"警告: 图片 {img_name} 不存在，已从内容中移除其占位符")
        
        # 检查是否有重复的占位符
        placeholder_counts = {}
        for placeholder in all_placeholders:
            if placeholder in placeholder_counts:
                placeholder_counts[placeholder] += 1
            else:
                placeholder_counts[placeholder] = 1
        
        # 打印重复的占位符
        duplicates = [p for p, count in placeholder_counts.items() if count > 1]
        if duplicates:
            print("\n警告: 发现重复的图片占位符:")
            for dup in duplicates:
                print(f"  - {dup} (出现 {placeholder_counts[dup]} 次)")
        
        # 将集合转换为列表
        images = list(unique_image_paths)
        
        print(f"\n实际找到的有效图片数量: {len(images)}")
        print(f"占位符总数: {len(all_placeholders)}")
        print(f"唯一占位符数: {len(placeholder_counts)}")
        
        cleaned_content = re.sub(r'^\s*\ufeff?https?://[^\n]+\n?', '', cleaned_content, flags=re.MULTILINE)
        cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)
        
        return cleaned_content.strip(), images
        
    except Exception as e:
        print(f"处理文本时出现错误: {str(e)}")
        return None, []

def get_font_path():
    """
    <--- 新增：跨平台获取中文字体路径
    """
    system = platform.system()
    if system == 'Darwin':
        # macOS 优先使用苹方，备选黑体
        candidates = [
            '/System/Library/Fonts/PingFang.ttc',
            '/Library/Fonts/FangZhengHeiTiJianTi-1.ttf',
            '/System/Library/Fonts/STHeiti Light.ttc'
        ]
    elif system == 'Windows':
        # Windows 优先使用微软雅黑
        candidates = [
            r'C:\Windows\Fonts\msyh.ttc',
            r'C:\Windows\Fonts\msyh.ttf',
            r'C:\Windows\Fonts\simhei.ttf'
        ]
    else: # Linux
        candidates = [
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'
        ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def txt_to_pdf_with_formatting(txt_path, pdf_path, article_copier_path, image_dir):
    try:
        content, images = clean_and_format_text(txt_path, article_copier_path, image_dir)
        if not content:
            return False
            
        print(f"\n开始创建PDF: {pdf_path}")
        print(f"图片数量: {len(images)}")
        
        # 创建PDF文档
        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4
        
        def draw_black_background():
            # 绘制黑色背景
            c.setFillColor(colors.black)
            c.rect(0, 0, width, height, fill=1)
            # 重置填充颜色
            c.setFillColor(colors.HexColor('#D3D3D3'))
        
        # <--- 修改：动态设置中文字体
        font_path = get_font_path()
        font_name = 'CustomChineseFont' # 自定义一个通用的内部名称
        font_size = 40
        
        try:
            if font_path:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                print(f"成功加载字体: {font_path}")
            else:
                raise Exception("未找到适合的中文字体文件")
        except Exception as e:
            print(f"无法加载中文字体 ({e})，使用默认字体")
            font_name = 'Helvetica'
            font_size = 14
            
        def set_font():
            c.setFont(font_name, font_size)
            c.setFillColor(colors.HexColor('#D3D3D3'))
            
        draw_black_background()  # 初始页面绘制黑色背景
        set_font()  # 初始设置字体
        
        x = 20  # 减小左边距，原来是50
        y = height - 30  # 减小上边距，原来是height - 50
        line_height = 60  # 减小行高，原来是20
        
        paragraphs = content.splitlines()
        
        for paragraph in paragraphs:
            if '--IMAGE_PLACEHOLDER_' in paragraph:
                img_filename = paragraph.replace('--IMAGE_PLACEHOLDER_', '').replace('--', '').strip()
                # <--- 路径拼接
                img_path = os.path.join(image_dir, img_filename)
                
                if os.path.exists(img_path):
                    try:
                        img = Image.open(img_path)
                        img_width, img_height = img.size
                        
                        # 调整图片大小以适应页面（调小左右边距）
                        aspect = img_width / float(img_height)
                        if img_width > width - 0:   # 调整边距，例如总边距为20
                            img_width = width - 0
                            img_height = img_width / aspect
                        
                        # 如果当前页空间不足，新建页面
                        if y < img_height + 80:  # 增加空间以容纳描述文字
                            c.showPage()
                            draw_black_background()  # 新页面时重新绘制黑色背景
                            set_font()
                            y = height - 30
                            
                        # 绘制图片
                        img_x = (width - img_width) / 2  # 图片水平居中
                        c.drawImage(img_path, img_x, y - img_height + 20, width=img_width, height=img_height)
                        
                        # 处理图片描述文字
                        description = os.path.splitext(img_filename)[0]  # 移除文件扩展名
                        c.setFont(font_name, font_size * 0.6)
                        c.setFillColor(colors.white)  # 确保描述文字为白色
                        
                        # 计算描述文字的行数和位置
                        desc_font_size = font_size * 0.6
                        max_desc_width = width - 80  # 留出左右边距

                        # 改进的文本分行处理，能更好地处理中英文混合文本
                        def split_text_for_display(text, font_name, font_size, max_width, canvas):
                            lines = []
                            remaining_text = text
                            
                            while remaining_text:
                                # 初始化当前行
                                current_line = ""
                                i = 0
                                last_space_idx = -1  # 用于记录上一个空格的位置
                                
                                # 逐字符添加，直到达到最大宽度
                                while i < len(remaining_text):
                                    # 记录空格的位置，用于英文单词的整体处理
                                    if remaining_text[i] == ' ':
                                        last_space_idx = i
                                    test_line = current_line + remaining_text[i]
                                    if canvas.stringWidth(test_line, font_name, font_size) < max_width:
                                        current_line = test_line
                                        i += 1
                                    else:
                                        break
                                # 处理英文单词切分的问题
                                # 如果当前行已有内容且找到了空格，则回退到最后一个空格处
                                if current_line and last_space_idx > 0 and i < len(remaining_text) and last_space_idx < i:
                                    # 计算需要回退的字符数
                                    back_chars = i - last_space_idx - 1
                                    if back_chars > 0:
                                        # 回退到最后一个空格
                                        i = last_space_idx + 1
                                        current_line = current_line[:-back_chars]
                                # 如果一个字符都放不下（极少数情况），强制添加一个字符
                                if not current_line and i == 0:
                                    current_line = remaining_text[0]
                                    i = 1
                                
                                lines.append(current_line)
                                remaining_text = remaining_text[i:]
                            
                            return lines

                        # 使用改进的函数处理描述文字
                        desc_words = split_text_for_display(description, font_name, desc_font_size, max_desc_width, c)

                        # 计算描述文字实际占用的总高度
                        desc_total_height = len(desc_words) * (desc_font_size + 2)  # 每行文字高度加行间距

                        # 绘制描述文字
                        desc_y = y - img_height - 10
                        for line in desc_words:
                            line_width = c.stringWidth(line, font_name, desc_font_size)
                            desc_x = (width - line_width) / 2  # 文字水平居中
                            c.drawString(desc_x, desc_y, line)
                            desc_y -= desc_font_size + 4  # 行间距
                        
                        set_font()  # 恢复原来的字体大小
                        # 动态计算需要的间距
                        min_spacing = 50  # 最小间距
                        # 使用对数函数来计算额外间距，这样行数越多，每行增加的间距越小
                        if len(desc_words) > 1:
                            extra_spacing = 10 * math.log2(len(desc_words))  # 可以调整这个系数(10)来控制间距增长速度
                        else:
                            extra_spacing = 0
                        total_spacing = min_spacing + desc_total_height + extra_spacing

                        # 更新y坐标
                        y -= (img_height + total_spacing)
                        
                    except Exception as e:
                        print(f"处理图片时出错: {str(e)}")
                        
            else:
                # 处理文本段落
                # text = paragraph.strip()
                # 处理文本段落
                text = paragraph.strip()
                # 去掉 BOM、常见中英文标点
                text = text.lstrip('\ufeff').lstrip("：:。.，,")
                upper = text.upper()

                # if text.upper() in {site.upper() for site in major_news_sites}:
                if any(upper.startswith(site) for site in MAJOR_SITES):
                    # 保存当前字体设置和颜色
                    current_font_size = font_size
                    
                    # 设置更大的字体和蓝色
                    c.setFont(font_name, font_size * 1.5)
                    c.setFillColor(colors.HexColor('#4169E1'))  # Royal Blue
                    
                    # 左对齐显示
                    x_left = 20  # 可以调整这个值来改变左边距
                    
                    # 检查是否需要换页
                    if y < 30:
                        c.showPage()
                        draw_black_background()
                        set_font()
                        y = height - 40
                        
                    # 绘制网站名称
                    c.drawString(x_left, y, text)
                    
                    # 恢复原来的字体设置和颜色
                    c.setFont(font_name, current_font_size)
                    # c.setFillColor(colors.white)  # 直接设置回白色
                    c.setFillColor(colors.HexColor('#D3D3D3'))  # 米色 浅灰色: '#E0E0E0' 暖灰色: '#D3D3D3' 象牙色: '#FFFFF0'
                    
                    # 更新y坐标
                    y -= line_height * 1.5
                else:
                    max_width = width - 30  # 减小文本区域边距，原来是100
                    
                    while text:
                        # 计算当前行可以容纳的文字
                        line = ''
                        i = 0
                        while i < len(text):
                            if c.stringWidth(line + text[i]) < max_width:
                                line += text[i]
                                i += 1
                            else:
                                break
                        
                        # 如果一个字符都放不下，强制换页
                        if not line:
                            line = text[0]
                            i = 1
                        
                        # 检查是否需要换页
                        if y < 30:  # 减小底部边距，原来是50
                            c.showPage()
                            draw_black_background()  # 新页面时重新绘制黑色背景
                            set_font()  # 新页面重新设置字体
                            y = height - 40
                        
                        # 绘制当前行
                        c.drawString(x, y, line)
                        y -= line_height
                        
                        # 更新剩余文本
                        text = text[i:]
                    
                    # 段落间距
                    y -= 10  # 减小段落间距，原来是10
        
        c.save()
        return True
        
    except Exception as e:
        print(f"转换过程中出现错误: {str(e)}")
        return False
    
def extract_site_name(url):
    try:
        # 移除 http:// 或 https:// 前缀
        url = re.sub(r'^https?://(www\.)?', '', url.lower())
        
        # 常见新闻网站的特殊处理
        if 'ft.com' in url:
            return 'FT'
        elif 'wsj.com' in url:
            return 'WSJ'
        elif 'rfi.fr' in url:
            return 'RFI'
        elif 'dw.com' in url:
            return 'DW'
        elif 'bloomberg.com' in url:
            return 'BLOOMBERG'
        elif 'reuters.com' in url:
            return 'REUTERS'
        elif 'nytimes.com' in url:
            return 'NYTIMES'
        elif 'washingtonpost.com' in url:
            return 'WASHINGTONPOST'
        elif 'economist.com' in url:
            return 'ECONOMIST'
        elif 'technologyreview.com' in url:
            return 'TECHNOLOGYREVIEW'
        
        # 对于其他网站，提取域名主体
        domain = url.split('/')[0]
        # 提取主域名
        parts = domain.split('.')
        if len(parts) >= 2:
            # 查找主域名（通常是倒数第二个部分）
            main_domain = parts[-2]
            site_name = main_domain.upper()
        else:
            # 否则只使用主域名
            site_name = parts[0].upper()
            
        return site_name
        
    except Exception as e:
        print(f"提取网站名称时出错 ({url}): {str(e)}")
        return "Other" # 出错时返回 Other

def process_all_files(directory, article_copier_path, image_dir):
    """
    仅将 News_*.txt 文件转换为 PDF，不移动源文件。
    """
    txt_files = find_all_news_files(directory)
    
    if not txt_files:
        print(f"在 {directory} 目录下没有找到以News_开头的txt文件")
        return
    
    converted = 0
    skipped = 0
    failed = 0
    
    for txt_file in txt_files:
        pdf_file = get_pdf_path(txt_file)
        
        try:
            if needs_conversion(txt_file, pdf_file):
                print(f"正在处理: {os.path.basename(txt_file)}")
                if txt_to_pdf_with_formatting(txt_file, pdf_file, article_copier_path, image_dir):
                    print(f"成功转换: {os.path.basename(txt_file)} -> {os.path.basename(pdf_file)}")
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
    
    print(f"\n处理总结:")
    print(f"  成功转换: {converted} 个文件")
    print(f"  跳过处理: {skipped} 个文件")
    print(f"  转换失败: {failed} 个文件")

    return failed == 0

# ------  整个pdf逻辑部分结束  ------#

# ---- 站点显示名称映射（不区分大小写） ----测试
SITE_DISPLAY_MAP = {
    'ft':             '伦敦金融时报',
    'nytimes':        '纽约时报',
    'washingtonpost': '华盛顿邮报',
    'economist':      '经济学人',
    'technologyreview': '麻省理工技术评论',
    'techreview':       '麻省理工技术评论',
    'wsj':            '华尔街日报',
    'rfi':            '法广头条',
    'dw':            '德国之声',
    'wsjcn':          '华尔街日报中文网',
    'reuters':        '路透社',
    'bloomberg':      '布隆伯格金融',
    'nikkeiasia':     '日经新闻亚洲版',
}

# ---- 新增：反向映射，用于生成 source_id ----
REVERSE_SITE_MAPPING = {
    "华尔街日报": "wsj",
    "华尔街日报中文网": "wsjcn",
    "伦敦金融时报": "ft",
    "法广头条": "rfi",
    "德国之声": "dw",
    "布隆伯格金融": "bloomberg",
    "路透社": "reuters",
    "经济学人": "economist",
    "日经新闻亚洲版": "nikkei",
    "华盛顿邮报": "washpost",
    "纽约时报": "nytimes",
    "麻省理工技术评论": "mittr"
}

def compute_md5(path):
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# --- 重要修改：backup_news_assets ---
def backup_news_assets(local_dir):
    timestamp = datetime.now().strftime("%y%m%d")
    
    # <--- 修改：使用动态路径
    src_img_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    src_json = os.path.join(NEWS_DIRECTORY, "onews.json")
    
    # 目标位置
    local_img_target = os.path.join(local_dir, f"news_images_{timestamp}")
    local_json_target = os.path.join(local_dir, f"onews_{timestamp}.json")
    
    # 备份目录位置
    backup_dir = os.path.join(DOWNLOADS_DIR, "backup")
    backup_file_dir = os.path.join(NEWS_DIRECTORY, "done")
    
    # 1) 合并图片目录
    if os.path.exists(src_img_dir):
        os.makedirs(local_img_target, exist_ok=True)
        # Python 3.8+ 支持 dirs_exist_ok
        shutil.copytree(src_img_dir, local_img_target, dirs_exist_ok=True)
        print(f"已将图片合并到: {local_img_target}")
        # 3) 删除原目录
        shutil.rmtree(src_img_dir)
        print(f"已删除原始图片目录: {src_img_dir}")
    else:
        print(f"未找到源图片目录: {src_img_dir}")
        
    # 1) 备份到 Downloads/backup
    backup_img_target = os.path.join(backup_dir, f"news_images_{timestamp}")
    if os.path.exists(backup_img_target):
        shutil.rmtree(backup_img_target)
    shutil.copytree(local_img_target, backup_img_target)
    print(f"图片目录已备份到: {backup_img_target}")
    
    # 2) 合并 JSON 文件
    if os.path.exists(src_json):
        tmp_json = os.path.join(local_dir, f"onews_{timestamp}_new.json")
        shutil.copy2(src_json, tmp_json)
        if os.path.exists(local_json_target):
            merge_json_groupwise(local_json_target, tmp_json)
            os.remove(tmp_json)
        else:
            os.rename(tmp_json, local_json_target)
            print(f"已备份 JSON 到: {local_json_target}")
        os.remove(src_json)
        print(f"已删除原始JSON文件: {src_json}")
    else:
        print(f"未找到源 JSON 文件: {src_json}")
        
    # 1) 备份到 Coding/News/done
    backup_file_target = os.path.join(backup_file_dir, f"onews_{timestamp}.json")
    shutil.copy2(local_json_target, backup_file_target)
    print(f"JSON文件已备份到: {backup_file_target}")
    
    update_version_json(local_dir, timestamp)

# ... (update_version_json, prune_old_assets, merge_json_groupwise, update_version_json_fake 等函数内部逻辑通用，只需确保调用时传入的路径是 os.path.join 生成的即可) ...

def update_version_json(local_dir, timestamp):
    version_path = os.path.join(local_dir, "version.json")
    if not os.path.exists(version_path):
        # 如果文件不存在，初始化一个基础结构，包含 update_time
        data = {
            "version": "1.0", 
            "files": [],
            "update_time": "" 
        }
    else:
        with open(version_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
    # 1. 更新现有文件的 MD5
    for item in data.get("files", []):
        if item.get("type") == "json":
            file_path = os.path.join(local_dir, item["name"])
            if os.path.isfile(file_path):
                new_md5 = compute_md5(file_path)
                if item.get("md5") != new_md5:
                    item["md5"] = new_md5
                    
    # 2. 准备添加新文件
    to_add = []
    json_name = f"onews_{timestamp}.json"
    json_path = os.path.join(local_dir, json_name)
    if os.path.isfile(json_path):
        to_add.append({
            "name": json_name,
            "type": "json",
            "md5": compute_md5(json_path)
        })
    img_name = f"news_images_{timestamp}"
    to_add.append({
        "name": img_name,
        "type": "images"
    })
    
    # 3. 确保 files 列表存在（兼容性处理）
    if "files" not in data:
        data["files"] = []

    # 4. 检查重复并添加
    existing_names = { item["name"] for item in data.get("files", []) }
    for e in to_add:
        if e["name"] not in existing_names:
            data["files"].append(e)
            print(f"已添加到 version.json: {e['name']}")

    # 5. 更新 update_time 为当前系统时间
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    data["update_time"] = current_time_str
    print(f"已更新 version.json 的 update_time 为: {current_time_str}")
            
    # 6. 保存文件
    with open(version_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"version.json 已更新")

def prune_old_assets(local_dir, days_to_keep):
    # 逻辑保持不变，路径拼接已在调用端处理
    version_path = os.path.join(local_dir, "version.json")
    if not os.path.exists(version_path): return
    print(f"\n开始清理超过 {days_to_keep} 天的旧资产...")
    with open(version_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    files_to_keep = []
    files_deleted_count = 0
    date_pattern = re.compile(r'_(\d{6})')
    for item in data.get("files", []):
        item_name = item.get("name", "")
        match = date_pattern.search(item_name)
        if not match:
            files_to_keep.append(item)
            continue
        try:
            file_date = datetime.strptime(match.group(1), "%y%m%d")
        except ValueError:
            files_to_keep.append(item)
            continue
            
        if file_date < cutoff_date:
            path_to_delete = os.path.join(local_dir, item_name)
            try:
                if item.get("type") == "json" and os.path.isfile(path_to_delete):
                    os.remove(path_to_delete)
                    files_deleted_count += 1
                    print(f"已删除: {item_name}")
                elif item.get("type") == "images" and os.path.isdir(path_to_delete):
                    shutil.rmtree(path_to_delete)
                    files_deleted_count += 1
                    print(f"已删除: {item_name}")
            except Exception as e:
                print(f"删除失败 {item_name}: {e}")
        else:
            files_to_keep.append(item)
            
    if files_deleted_count > 0:
        data["files"] = files_to_keep
        with open(version_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

def merge_json_groupwise(existing_path, new_path):
    # 逻辑保持不变
    with open(existing_path, 'r', encoding='utf-8') as f: data_old = json.load(f)
    with open(new_path, 'r', encoding='utf-8') as f: data_new = json.load(f)
    merged = {}
    for group, lst in {**data_old, **data_new}.items():
        a = data_old.get(group, [])
        b = data_new.get(group, [])
        combined = a + b
        seen = set()
        deduped = []
        for item in combined:
            key = (item.get("topic",""), item.get("url",""), item.get("article",""))
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        merged[group] = deduped
    with open(existing_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)

def find_all_news_files(directory):
    pattern = os.path.join(directory, "News_*.txt")
    return sorted(glob.glob(pattern))
    
def move_cnh_file(source_dir):
    try:
        # 只查找根目录下的文件
        cnh_pattern = os.path.join(source_dir, "TodayCNH_*.html")
        # 排除掉 backup 子目录（glob 有时会递归，虽然这里写法不会，但为了保险）
        cnh_files = [f for f in glob.glob(cnh_pattern) if os.path.dirname(f) == source_dir]
        
        if not cnh_files:
            print("没有找到需要移动的 TodayCNH_ 开头的文件")
            return False
            
        backup_dir = os.path.join(source_dir, "backup", "backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        moved_count = 0
        for source_file in cnh_files:
            filename = os.path.basename(source_file)
            target_file = os.path.join(backup_dir, filename)
            
            # <--- 修改点：如果目标存在，进行重命名，防止覆盖旧的备份 --->
            if os.path.exists(target_file):
                print(f"警告: 备份目录已存在 {filename}，正在重命名...")
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(target_file):
                    target_file = os.path.join(backup_dir, f"{base}_{counter}{ext}")
                    counter += 1
            
            os.rename(source_file, target_file)
            print(f"成功移动文件: {filename} -> {os.path.basename(target_file)}")
            moved_count += 1
            
        return moved_count > 0
        
    except Exception as e:
        print(f"移动文件时出错: {str(e)}")
        return False

def parse_article_copier(file_path):
    url_images = {}
    current_url = None
    valid_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')
    
    try: # 增加错误处理，防止文件不存在
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"警告: article_copier 文件未找到: {file_path}")
        return {} # 返回空字典
        
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('http'):
            current_url = line
            url_images[current_url] = []
        elif any(line.lower().endswith(ext) for ext in valid_extensions) and current_url:
            url_images[current_url].append(line)
    
    print("解析到的URL和图片映射:")
    for url, images in url_images.items():
        print(f"URL: {url}")
        print(f"Images: {images}")
        
    return url_images

def move_processed_txt_files(directory):
    """
    将所有 News_*.txt 文件移动到 'done' 子目录中。
    如果目标文件已存在，则重命名以避免覆盖。
    """
    done_dir = os.path.join(directory, "done")
    os.makedirs(done_dir, exist_ok=True)
    
    txt_files_to_move = find_all_news_files(directory)
    if not txt_files_to_move:
        print(f"在 {directory} 目录中没有找到需要移动的 News_*.txt 文件。")
        return
    
    print(f"准备移动 {len(txt_files_to_move)} 个 TXT 文件到 '{done_dir}' 目录...")
    
    moved_count = 0
    for source_path in txt_files_to_move:
        # 再次确认文件存在，以防万一
        if not os.path.exists(source_path):
            continue
        
        original_basename = os.path.basename(source_path)
        target_path = os.path.join(done_dir, original_basename)
        
        # 检查目标文件是否存在，如果存在则重命名
        if os.path.exists(target_path):
            print(f"警告: 文件 '{original_basename}' 已存在于 'done' 目录中。将重命名后移动。")
            base, ext = os.path.splitext(original_basename)
            counter = 1
            # 循环查找一个不重复的文件名
            while os.path.exists(target_path):
                target_path = os.path.join(done_dir, f"{base}_{counter}{ext}")
                counter += 1
        
        # 移动文件到最终确定的路径
        try:
            shutil.move(source_path, target_path)
            print(f"已移动: {original_basename} -> {os.path.basename(target_path)}")
            moved_count += 1
        except Exception as e:
            print(f"移动文件 {original_basename} 时出错: {e}")
            
    print(f"移动完成，共成功移动 {moved_count} 个文件。")

# --- 新增功能 1: 移动 article_copier 文件 ---
def move_article_copier_files(source_dir, backup_parent_dir):
    """
    将 source_dir 下所有 article_copier_*.txt 文件移动到 backup_parent_dir/backup 目录下。
    如果目标文件已存在，则重命名以避免覆盖。
    """
    backup_dir = os.path.join(backup_parent_dir, "backup") # 目标是 News/backup
    os.makedirs(backup_dir, exist_ok=True) # 确保 backup 目录存在
    
    pattern = os.path.join(source_dir, "article_copier_*.txt")
    files_to_move = glob.glob(pattern)
    
    if not files_to_move:
        print(f"在 {source_dir} 未找到 article_copier_*.txt 文件。")
        return
        
    print(f"\n--- 开始移动 article_copier 文件到 {backup_dir} ---")
    moved_count = 0
    for source_path in files_to_move:
        filename = os.path.basename(source_path)
        target_path = os.path.join(backup_dir, filename)
        
        # 检查重名冲突
        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(target_path):
            new_filename = f"{base}_copy_{counter}{ext}"
            target_path = os.path.join(backup_dir, new_filename)
            print(f"警告: 文件 {filename} 已存在于备份目录，尝试重命名为 {new_filename}")
            counter += 1
            
        # 移动文件
        try:
            shutil.move(source_path, target_path)
            print(f"成功移动: {filename} -> {os.path.basename(target_path)}")
            moved_count += 1
        except Exception as e:
            print(f"移动文件 {filename} 时出错: {str(e)}")
            
    print(f"--- 完成移动 article_copier 文件，共移动 {moved_count} 个文件 ---")

def normalize_url(u):
    """
    去掉 query 和 fragment，末尾去掉 '/'
    """
    parts = urlsplit(u)
    new = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
    return new

def split_zh_en(text):
    """
    将文章内容拆分为中文部分和英文部分。
    Strategy: 
    1. Iterate line by line.
    2. Look for a line that has English characters but NO Chinese characters.
    3. CRITICAL: This line must be preceded by an empty line (or be at start).
    4. SAFETY: The next few non-empty lines must also be English (no Chinese) to avoid splitting on isolated sentences.
    """
    lines = text.strip().split('\n')
    split_index = -1
    
    for i, line in enumerate(lines):
        line_strip = line.strip()
        if not line_strip:
            continue
            
        # Check language characteristics
        has_zh = bool(re.search(r'[\u4e00-\u9fff]', line_strip))
        has_en = bool(re.search(r'[a-zA-Z]', line_strip))
        
        # Candidate for start of English section:
        # - Has English
        # - Has NO Chinese
        if not has_zh and has_en:
            # Check 1: Preceded by empty line (or start of text)
            prev_is_empty = (i == 0) or (not lines[i-1].strip())
            
            if prev_is_empty:
                # Check 2: Check length to avoid bullet points like "1." 
                # (though "1." usually has no En chars if just numbers, but "FT" might)
                en_count = len(re.findall(r'[a-zA-Z]', line_strip))
                if en_count > 3:
                    # Check 3 (Lookahead): Ensure the next few lines are also not Chinese
                    # This prevents splitting on an isolated English sentence inside Chinese text.
                    is_english_block = True
                    checked_lines = 0
                    for k in range(i + 1, len(lines)):
                        next_line = lines[k].strip()
                        if not next_line:
                            continue
                        
                        if re.search(r'[\u4e00-\u9fff]', next_line):
                            is_english_block = False
                            break
                        
                        checked_lines += 1
                        if checked_lines >= 2: # Check next 2 non-empty lines is sufficient
                            break
                    
                    if is_english_block:
                        split_index = i
                        break
    
    if split_index != -1:
        # Found the split point
        zh_part = '\n'.join(lines[:split_index]).strip()
        en_part = '\n'.join(lines[split_index:]).strip()
        return zh_part, en_part
    
    # If no split found (e.g. WSJCN), return all as first part
    return text.strip(), ""

def generate_news_json(news_directory, today, cnh_html_paths=None):
    """
    扫描 News_*.txt、TodayCNH_*.html、article_copier_{today}.txt，

    新增: 若 cnh_html_paths 提供，则仅使用这些 HTML（通常是当天的唯一文件）。
    """
    # 1. 解析 TodayCNH_*.html -> { norm_url: (site, topic, original_url, topic_eng) }
    #    **改动**: 增加 parsing 逻辑以支持提取 title-eng
    cnh_map = {}
    if cnh_html_paths is None:
        # 兼容旧逻辑：遍历目录中所有 TodayCNH_*.html
        html_files = glob.glob(os.path.join(news_directory, f"TodayCNH_*.html"))
    else:
        # 只使用传入的（已确认存在的）路径
        html_files = cnh_html_paths
        
    for html_path in html_files:
        with open(html_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        # 使用更稳健的方式遍历表格行
        for tr_match in re.finditer(r"<tr>(.*?)</tr>", text, re.S):
            tr_content = tr_match.group(1)
            
            # 提取基础信息：站点和标题链接
            # 匹配 <td>SITE</td>...<a href="URL">TITLE</a>
            basic_match = re.search(
                r"<td>\s*([^<]+)\s*</td>.*?<a\s+href=\"([^\"]+)\"[^>]*>([^<]+)</a>", 
                tr_content, re.S
            )
            
            if basic_match:
                site = basic_match.group(1).strip()
                original_url = basic_match.group(2).strip()
                title_raw = basic_match.group(3).strip()
                
                # 尝试提取英文标题 (class="title-eng")
                topic_eng = ""
                eng_match = re.search(r"<td\s+class=\"title-eng\">\s*(.*?)\s*</td>", tr_content, re.S)
                if eng_match:
                    raw_eng = html.unescape(eng_match.group(1).strip())
                    # 清理标题：移除开头的箭头和多余空白
                    # 比如 "→\n Day two..." -> "Day two..."
                    topic_eng = re.sub(r'^[→\s]+', '', raw_eng).strip()
                    # 将内部的换行符替换为空格
                    topic_eng = re.sub(r'\s+', ' ', topic_eng)
                
                # 数据清洗
                nu = normalize_url(original_url)
                title_decoded = html.unescape(title_raw)
                
                # --- 修改点：移除 title_decoded 中间的所有换行和空格 ---
                title_decoded = re.sub(r'\s+', '', title_decoded)
                
                # 移除开头的数字序号
                topic = re.sub(r'^[0-9０-９]+[、,，.]\s*', '', title_decoded)
                
                # 存入 map
                cnh_map[nu] = (site, topic, original_url, topic_eng)

    # 2. 解析 article_copier_{today}.txt -> { norm_url: [img1, img2, ...] }
    copier_path = os.path.join(news_directory, f"article_copier_{today}.txt")
    url_images_raw = {}
    if os.path.exists(copier_path):
        url_images_raw = parse_article_copier(copier_path)
    # 归一化键
    url_images = {
        normalize_url(u): imgs
        for u, imgs in url_images_raw.items()
    }

    # 3. 组装 data
    data = {}
    for txt_path in glob.glob(os.path.join(news_directory, "News_*.txt")):
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        entries = []
        current_url = None
        buf = []

        for line in content.splitlines():
            raw = line.strip().lstrip('\ufeff')
            if raw.startswith("http"):
                if current_url is not None:
                    entries.append((current_url, "\n".join(buf).strip()))
                current_url = raw
                buf = []
            else:
                if current_url:
                    # 修改：保留所有行（即使是空行），以保留段落结构和中英文间的分隔
                    buf.append(raw)
                    
        if current_url is not None:
            entries.append((current_url, "\n".join(buf).strip()))

        for url, article_text in entries:
            nu = normalize_url(url)
            
            # 默认值
            topic_eng = ""
            article_eng = ""
            
            # 修改：优先使用 cnh_map 中的信息
            if nu in cnh_map:
                site_code, topic, original_url_from_map, topic_eng = cnh_map[nu]
                imgs = url_images.get(nu, [])
                display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)
            else:
                # 如果在 HTML 中找不到，尝试从 URL 推断站点信息
                site_code = extract_site_name(url)
                # 尝试从文章内容的第一行提取标题作为主题
                first_line = article_text.split('\n')[0].strip() if article_text else ""
                # 如果第一行太长，截取前100个字符
                topic = first_line[:100] + "..." if len(first_line) > 100 else first_line
                if not topic:
                    topic = "未知主题"
                
                original_url_from_map = url
                imgs = url_images.get(nu, [])
                display_site = SITE_DISPLAY_MAP.get(site_code.lower(), site_code)
                
                print(f"注意：URL {url} 未在 HTML 中找到，使用推断信息: 站点={site_code}, 主题={topic[:50]}...")
            
            # --- 分割中英文内容 ---
            article_zh, article_eng = split_zh_en(article_text)
            
            # --- 获取 source_id ---
            source_id = REVERSE_SITE_MAPPING.get(display_site, "unknown")
            
            data.setdefault(display_site, []).append({
                "source_id": source_id,
                "topic":   topic,
                "topic_eng": topic_eng, # 新增字段
                "url":     original_url_from_map,
                "article": article_zh, # 主要是中文部分
                "article_eng": article_eng, # 新增英文部分
                "images":  imgs
            })
            
    out_path = os.path.join(news_directory, f"onews.json")
    with open(out_path, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=4)
    print(f"\n已生成 JSON 文件: {out_path}")


if __name__ == "__main__":
    today = datetime.now().strftime("%y%m%d")
    
    # <--- 使用前面定义的动态路径常量
    news_directory = NEWS_DIRECTORY
    article_copier_path = os.path.join(NEWS_DIRECTORY, f"article_copier_{today}.txt")
    image_dir = os.path.join(DOWNLOADS_DIR, "news_images")
    downloads_path = DOWNLOADS_DIR
    local_server_dir = LOCAL_SERVER_DIR
    
    # 0. 先查找当天的 TodayCNH_<today>.html
    cnh_html_paths = find_today_cnh_html(today, news_directory)
    
    if not cnh_html_paths:
        # 两处都找不到 -> 弹窗并终止
        alert_and_exit(
            f"未找到当天的 TodayCNH_{today}.html。\n"
            f"请检查以下路径：\n"
            f"1) {os.path.join(news_directory, 'backup', 'backup')}\n"
            f"2) {news_directory}\n"
            f"找到后再重试。"
        )

    print("="*10 + " 1. 开始 TXT 转 PDF 处理 " + "="*10)
    # <--- 修改部分：捕获返回值 ---
    # pdf_conversion_successful = process_all_files(news_directory, article_copier_path, image_dir)
    # print("="*10 + " 完成 TXT 转 PDF 处理 " + "="*10)
    
    # <--- 修改部分：根据第一步的结果决定是否继续 ---
    # if pdf_conversion_successful:
    print("\nPDF转换成功，继续执行后续步骤...")

    # 2. 生成 JSON 汇总（使用已确认存在的当天 TodayCNH HTML 文件）
    print("\n" + "="*10 + " 2. 开始生成 JSON 汇总 " + "="*10)
    generate_news_json(news_directory, today, cnh_html_paths=cnh_html_paths)
    print("="*10 + " 完成生成 JSON 汇总 " + "="*10)

    # 3. 移动 TodayCNH 文件 (如果需要)
    print("\n" + "="*10 + " 3. 开始移动 TodayCNH 文件 " + "="*10)
    move_cnh_file(news_directory)
    print("="*10 + " 完成移动 TodayCNH 文件 " + "="*10)

    # 4. 清理 Downloads 目录下的 .html 文件
    print("\n" + "="*10 + " 4. 开始清理 Downloads 中的 HTML 文件 " + "="*10)
    html_files = [f for f in os.listdir(downloads_path) if f.endswith('.html')]
    if html_files:
        for file in html_files:
            file_path = os.path.join(downloads_path, file)
            try:
                os.remove(file_path)
                print(f'成功删除 HTML 文件: {file}')
            except OSError as e:
                print(f'删除 HTML 文件失败 {file}: {e}')
    else:
        print("Downloads 目录下没有找到 .html 文件。")
    print("="*10 + " 完成清理 Downloads 中的 HTML 文件 " + "="*10)

    # 5. 移动 article_copier 文件到 backup
    print("\n" + "="*10 + " 5. 开始移动 article_copier 文件 " + "="*10)
    move_article_copier_files(news_directory, news_directory)
    print("="*10 + " 完成移动 article_copier 文件 " + "="*10)

    # 6. 将所有处理过的 TXT 文件移动到 done 目录
    print("\n" + "="*10 + " 6. 开始移动已处理的 TXT 文件 " + "="*10)
    move_processed_txt_files(news_directory)
    print("="*10 + " 完成移动已处理的 TXT 文件 " + "="*10)

    # 7. 将news_images和onews.json备份到相应目录下并更新version.json
    print("\n" + "="*10 + " 7. 开始备份核心资产 " + "="*10)
    backup_news_assets(local_server_dir)
    print("="*10 + " 完成备份核心资产 " + "="*10)

    # 8. 清理超过10天的旧文件和目录
    print("\n" + "="*10 + " 8. 开始清理旧资产 " + "="*10)
    prune_old_assets(local_server_dir, days_to_keep=10)
    print("="*10 + " 完成清理旧资产 " + "="*10)

    # else:
    #     print("\n错误：PDF转换过程中出现失败，已终止后续所有任务。")
    #     print("请检查上面的日志以确定失败原因。")

    timestamp = datetime.now().strftime("%y%m%d")

    # 2. 然后，执行原有的 version.json 更新逻辑
    #    它会为所有 json 文件（包括刚刚被修改的）重新计算 MD5
    update_version_json(local_server_dir, timestamp)