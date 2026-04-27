import os
import re
import glob
import math
import platform
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from PIL import Image


# ================= 配置区域 =================

USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
DOWNLOADS_DIR = os.path.join(USER_HOME, "Downloads")

NEWS_DIRECTORY = os.path.join(BASE_CODING_DIR, "News")
IMAGE_DIR = os.path.join(DOWNLOADS_DIR, "news_images")

# ===========================================


MAJOR_SITES = {s.upper() for s in (
    'FT',
    'WSJ',
    'BLOOMBERG',
    'REUTERS',
    'NYTIMES',
    'WASHINGTONPOST',
    'ECONOMIST',
    'TECHNOLOGYREVIEW',
    'WSJCN',
    'RFI',
    'DW',
    'BBC',
    'OTHER'
)}


def find_all_news_files(directory):
    pattern = os.path.join(directory, "News_*.txt")
    return sorted(glob.glob(pattern))


def get_pdf_path(txt_path):
    directory = os.path.dirname(txt_path)
    filename = os.path.basename(txt_path)
    pdf_filename = os.path.splitext(filename)[0] + ".pdf"
    return os.path.join(directory, pdf_filename)


def needs_conversion(txt_path, pdf_path):
    if not os.path.exists(pdf_path):
        return True

    txt_mtime = os.path.getmtime(txt_path)
    pdf_mtime = os.path.getmtime(pdf_path)

    return txt_mtime > pdf_mtime


def extract_site_name(url):
    try:
        url = re.sub(r'^https?://(www\.)?', '', url.lower())

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
        elif 'bbc.com' in url:
            return 'BBC'

        domain = url.split('/')[0]
        parts = domain.split('.')

        if len(parts) >= 2:
            main_domain = parts[-2]
            site_name = main_domain.upper()
        else:
            site_name = parts[0].upper()

        return site_name

    except Exception as e:
        print(f"提取网站名称时出错 ({url}): {str(e)}")
        return "OTHER"


def parse_article_copier(file_path):
    url_images = {}
    current_url = None
    valid_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"警告: article_copier 文件未找到: {file_path}")
        return {}

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
                if url in article_url or article_url in url:
                    print(f"Matched with: {article_url}")
                    print(f"Images found: {images}")
                    article_images.append((article, images))
                    break

    return article_images


def distribute_images_in_content(content, url_images):
    if not url_images:
        return content

    article_images = find_images_for_content(content, url_images)

    print("\n开始分布图片:")
    print(f"找到 {len(article_images)} 篇文章需要处理")

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

    processed_content = []

    for article in all_articles:
        lines = article.strip().split('\n')

        url_match = re.search(r'(https?://[^\s]+)', article)
        url_line = url_match.group(1) if url_match else ''

        if not url_line:
            processed_content.append(article)
            continue

        site_name = extract_site_name(url_line)

        article_with_images = None

        for art, imgs in article_images:
            art_url_match = re.search(r'(https?://[^\s]+)', art)
            art_url = art_url_match.group(1) if art_url_match else ''

            if art_url == url_line:
                article_with_images = (art, imgs)
                break

        processed_content.append(f"{site_name}\n")

        if article_with_images:
            art, imgs = article_with_images
            content_lines = [
                line for line in lines
                if line != url_line and line.strip()
            ]

            new_content = [url_line]

            if imgs:
                new_content.append(f"--IMAGE_PLACEHOLDER_{imgs[0]}--")

            remaining_images = imgs[1:] if len(imgs) > 1 else []

            if remaining_images and content_lines:
                segment_size = max(
                    1,
                    len(content_lines) // (len(remaining_images) + 1)
                )

                current_segment = []
                image_index = 0

                for i, line in enumerate(content_lines):
                    current_segment.append(line)

                    if (
                        (
                            len(current_segment) >= segment_size
                            or i == len(content_lines) - 1
                        )
                        and image_index < len(remaining_images)
                    ):
                        new_content.extend(current_segment)
                        new_content.append(
                            f"--IMAGE_PLACEHOLDER_{remaining_images[image_index]}--"
                        )
                        current_segment = []
                        image_index += 1

                if current_segment:
                    new_content.extend(current_segment)

                while image_index < len(remaining_images):
                    new_content.append(
                        f"--IMAGE_PLACEHOLDER_{remaining_images[image_index]}--"
                    )
                    image_index += 1
            else:
                new_content.extend(content_lines)

            processed_content.append('\n'.join(new_content))

        else:
            processed_content.append(article)

    if processed_content and processed_content[-1].strip() in {
        'FT',
        'WSJ',
        'BLOOMBERG',
        'REUTERS',
        'NYTIMES',
        'WASHINGTONPOST',
        'ECONOMIST',
        'TECHNOLOGYREVIEW',
        'WSJCN',
        'RFI',
        'DW',
        'OTHER'
    }:
        processed_content[-1] = processed_content[-1].strip()

    return '\n'.join(processed_content)


def clean_and_format_text(txt_path, article_copier_path, image_dir):
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        print(f"\n处理文件: {txt_path}")

        url_images = parse_article_copier(article_copier_path)
        cleaned_content = distribute_images_in_content(content, url_images)

        unique_image_paths = set()

        print("\n找到的图片占位符:")

        all_placeholders = []

        for img_placeholder in re.finditer(
            r'--IMAGE_PLACEHOLDER_(.*?)--(?:\n|$)',
            cleaned_content
        ):
            img_name = img_placeholder.group(1).strip()
            img_path = os.path.join(image_dir, img_name)
            all_placeholders.append(img_name)

            print(f"Image placeholder: {img_name}")
            print(f"Full path: {img_path}")
            print(f"Exists: {os.path.exists(img_path)}")

            if os.path.exists(img_path):
                unique_image_paths.add(img_path)
            else:
                cleaned_content = cleaned_content.replace(
                    f"--IMAGE_PLACEHOLDER_{img_name}--",
                    ""
                )
                print(f"警告: 图片 {img_name} 不存在，已从内容中移除其占位符")

        placeholder_counts = {}

        for placeholder in all_placeholders:
            if placeholder in placeholder_counts:
                placeholder_counts[placeholder] += 1
            else:
                placeholder_counts[placeholder] = 1

        duplicates = [
            p for p, count in placeholder_counts.items()
            if count > 1
        ]

        if duplicates:
            print("\n警告: 发现重复的图片占位符:")

            for dup in duplicates:
                print(f"  - {dup} 出现 {placeholder_counts[dup]} 次")

        images = list(unique_image_paths)

        print(f"\n实际找到的有效图片数量: {len(images)}")
        print(f"占位符总数: {len(all_placeholders)}")
        print(f"唯一占位符数: {len(placeholder_counts)}")

        cleaned_content = re.sub(
            r'^\s*\ufeff?https?://[^\n]+\n?',
            '',
            cleaned_content,
            flags=re.MULTILINE
        )

        cleaned_content = re.sub(r'\n{3,}', '\n\n', cleaned_content)

        return cleaned_content.strip(), images

    except Exception as e:
        print(f"处理文本时出现错误: {str(e)}")
        return None, []


def get_font_path():
    system = platform.system()

    if system == 'Darwin':
        candidates = [
            '/System/Library/Fonts/PingFang.ttc',
            '/Library/Fonts/FangZhengHeiTiJianTi-1.ttf',
            '/System/Library/Fonts/STHeiti Light.ttc'
        ]
    elif system == 'Windows':
        candidates = [
            r'C:\Windows\Fonts\msyh.ttc',
            r'C:\Windows\Fonts\msyh.ttf',
            r'C:\Windows\Fonts\simhei.ttf'
        ]
    else:
        candidates = [
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
        ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def split_text_for_display(text, font_name, font_size, max_width, pdf_canvas):
    lines = []
    remaining_text = text

    while remaining_text:
        current_line = ""
        i = 0
        last_space_idx = -1

        while i < len(remaining_text):
            if remaining_text[i] == ' ':
                last_space_idx = i

            test_line = current_line + remaining_text[i]

            if pdf_canvas.stringWidth(test_line, font_name, font_size) < max_width:
                current_line = test_line
                i += 1
            else:
                break

        if current_line and last_space_idx > 0 and i < len(remaining_text) and last_space_idx < i:
            back_chars = i - last_space_idx - 1

            if back_chars > 0:
                i = last_space_idx + 1
                current_line = current_line[:-back_chars]

        if not current_line and i == 0:
            current_line = remaining_text[0]
            i = 1

        lines.append(current_line)
        remaining_text = remaining_text[i:]

    return lines


def txt_to_pdf_with_formatting(txt_path, pdf_path, article_copier_path, image_dir):
    try:
        content, images = clean_and_format_text(
            txt_path,
            article_copier_path,
            image_dir
        )

        if not content:
            return False

        print(f"\n开始创建PDF: {pdf_path}")
        print(f"图片数量: {len(images)}")

        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4

        def draw_black_background():
            c.setFillColor(colors.black)
            c.rect(0, 0, width, height, fill=1)
            c.setFillColor(colors.HexColor('#D3D3D3'))

        font_path = get_font_path()
        font_name = 'CustomChineseFont'
        font_size = 40

        try:
            if font_path:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                print(f"成功加载字体: {font_path}")
            else:
                raise Exception("未找到适合的中文字体文件")
        except Exception as e:
            print(f"无法加载中文字体：{e}，使用默认字体")
            font_name = 'Helvetica'
            font_size = 14

        def set_font():
            c.setFont(font_name, font_size)
            c.setFillColor(colors.HexColor('#D3D3D3'))

        draw_black_background()
        set_font()

        x = 20
        y = height - 30
        line_height = 60

        paragraphs = content.splitlines()

        for paragraph in paragraphs:
            if '--IMAGE_PLACEHOLDER_' in paragraph:
                img_filename = (
                    paragraph
                    .replace('--IMAGE_PLACEHOLDER_', '')
                    .replace('--', '')
                    .strip()
                )

                img_path = os.path.join(image_dir, img_filename)

                if os.path.exists(img_path):
                    try:
                        img = Image.open(img_path)
                        img_width, img_height = img.size

                        aspect = img_width / float(img_height)

                        if img_width > width:
                            img_width = width
                            img_height = img_width / aspect

                        if y < img_height + 80:
                            c.showPage()
                            draw_black_background()
                            set_font()
                            y = height - 30

                        img_x = (width - img_width) / 2

                        c.drawImage(
                            img_path,
                            img_x,
                            y - img_height + 20,
                            width=img_width,
                            height=img_height
                        )

                        description = os.path.splitext(img_filename)[0]

                        c.setFont(font_name, font_size * 0.6)
                        c.setFillColor(colors.white)

                        desc_font_size = font_size * 0.6
                        max_desc_width = width - 80

                        desc_words = split_text_for_display(
                            description,
                            font_name,
                            desc_font_size,
                            max_desc_width,
                            c
                        )

                        desc_total_height = len(desc_words) * (desc_font_size + 2)

                        desc_y = y - img_height - 10

                        for line in desc_words:
                            line_width = c.stringWidth(
                                line,
                                font_name,
                                desc_font_size
                            )
                            desc_x = (width - line_width) / 2
                            c.drawString(desc_x, desc_y, line)
                            desc_y -= desc_font_size + 4

                        set_font()

                        min_spacing = 50

                        if len(desc_words) > 1:
                            extra_spacing = 10 * math.log2(len(desc_words))
                        else:
                            extra_spacing = 0

                        total_spacing = min_spacing + desc_total_height + extra_spacing

                        y -= img_height + total_spacing

                    except Exception as e:
                        print(f"处理图片时出错: {str(e)}")

            else:
                text = paragraph.strip()
                text = text.lstrip('\ufeff').lstrip("：:。.，,")
                upper = text.upper()

                if any(upper.startswith(site) for site in MAJOR_SITES):
                    current_font_size = font_size

                    c.setFont(font_name, font_size * 1.5)
                    c.setFillColor(colors.HexColor('#4169E1'))

                    x_left = 20

                    if y < 30:
                        c.showPage()
                        draw_black_background()
                        set_font()
                        y = height - 40

                    c.drawString(x_left, y, text)

                    c.setFont(font_name, current_font_size)
                    c.setFillColor(colors.HexColor('#D3D3D3'))

                    y -= line_height * 1.5

                else:
                    max_width = width - 30

                    while text:
                        line = ''
                        i = 0

                        while i < len(text):
                            if c.stringWidth(line + text[i], font_name, font_size) < max_width:
                                line += text[i]
                                i += 1
                            else:
                                break

                        if not line:
                            line = text[0]
                            i = 1

                        if y < 30:
                            c.showPage()
                            draw_black_background()
                            set_font()
                            y = height - 40

                        c.drawString(x, y, line)
                        y -= line_height

                        text = text[i:]

                    y -= 10

        c.save()
        return True

    except Exception as e:
        print(f"转换过程中出现错误: {str(e)}")
        return False


def process_all_files(directory, article_copier_path, image_dir):
    """
    将 directory 下所有 News_*.txt 文件转换为 PDF。
    不移动源文件。
    """

    txt_files = find_all_news_files(directory)

    if not txt_files:
        print(f"在 {directory} 目录下没有找到以 News_ 开头的 txt 文件")
        return True

    converted = 0
    skipped = 0
    failed = 0

    for txt_file in txt_files:
        pdf_file = get_pdf_path(txt_file)

        try:
            if needs_conversion(txt_file, pdf_file):
                print(f"正在处理: {os.path.basename(txt_file)}")

                if txt_to_pdf_with_formatting(
                    txt_file,
                    pdf_file,
                    article_copier_path,
                    image_dir
                ):
                    print(
                        f"成功转换: {os.path.basename(txt_file)} -> {os.path.basename(pdf_file)}"
                    )
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

    print("\n处理总结:")
    print(f"  成功转换: {converted} 个文件")
    print(f"  跳过处理: {skipped} 个文件")
    print(f"  转换失败: {failed} 个文件")

    return failed == 0


def main():
    today = datetime.now().strftime("%y%m%d")

    news_directory = NEWS_DIRECTORY
    article_copier_path = os.path.join(NEWS_DIRECTORY, f"article_copier_{today}.txt")
    image_dir = IMAGE_DIR

    print("=" * 10 + " 开始 TXT 转 PDF 处理 " + "=" * 10)

    success = process_all_files(
        news_directory,
        article_copier_path,
        image_dir
    )

    print("=" * 10 + " 完成 TXT 转 PDF 处理 " + "=" * 10)

    if success:
        print("\nPDF 转换流程执行完成。")
    else:
        print("\n错误：PDF 转换过程中有失败项目，请检查日志。")
        raise SystemExit(1)


if __name__ == "__main__":
    main()