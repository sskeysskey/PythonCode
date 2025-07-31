import os
import shutil
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.colors import black, white

def find_first_news_txt(directory):
    # 遍历指定目录，寻找以"News"开头的第一个txt文件
    for filename in os.listdir(directory):
        if filename.startswith("News") and filename.endswith(".txt"):
            return os.path.join(directory, filename)
    return None

def txt_to_pdf(txt_file, pdf_file):
    # 创建一个Canvas对象
    c = canvas.Canvas(pdf_file, pagesize=letter)
    width, height = letter

    # 指定中文字体文件路径
    font_path = '/System/Library/Fonts/STHeiti Medium.ttc'

    # 注册字体
    pdfmetrics.registerFont(TTFont('STHeiti', font_path))
    font_size = 24  # 设置字体大小为24
    c.setFont('STHeiti', font_size)

    # 设置背景颜色为黑色
    c.setFillColor(black)
    c.rect(0, 0, width, height, fill=1)

    # 设置字体颜色为白色
    c.setFillColor(white)

    # 打开TXT文件并读取内容
    with open(txt_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 设置初始Y坐标
    y = height - 40
    line_height = font_size + 8  # 增加行间距
    margin = 40
    max_width = (width - 2 * margin) * 3 / 4  # 将最大宽度设置为原来宽度的四分之三

    for line in lines:
        line = line.strip()
        while line:
            # 截取能够放入一行的文本
            text = line
            while c.stringWidth(text) > max_width:
                text = text[:-1]

            # 绘制文本行
            c.drawString(margin, y, text)

            # 更新Y坐标
            y -= line_height

            # 检查Y坐标是否需要新页面
            if y < margin:
                c.showPage()
                c.setFont('STHeiti', font_size)
                # 设置新页面背景颜色为黑色
                c.setFillColor(black)
                c.rect(0, 0, width, height, fill=1)
                # 设置字体颜色为白色
                c.setFillColor(white)
                y = height - margin

            # 更新剩余文本
            line = line[len(text):].strip()

    # 保存PDF文件
    c.save()

def main():
    directory = '/Users/yanzhang/Documents/News/'
    done_directory = '/Users/yanzhang/Documents/News/done'
    if not os.path.exists(done_directory):
        os.makedirs(done_directory)

    txt_file = find_first_news_txt(directory)
    if txt_file:
        pdf_file = txt_file.replace('.txt', '.pdf')
        txt_to_pdf(txt_file, pdf_file)
        print(f'文件已成功转换并保存为: {pdf_file}')

        # 移动TXT文件到done目录
        shutil.move(txt_file, os.path.join(done_directory, os.path.basename(txt_file)))
        print(f'{txt_file} 已移动到 {done_directory}')
    else:
        print('未找到以"News"开头的txt文件')

# 调用主函数
main()