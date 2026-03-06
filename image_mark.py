from PIL import Image, ImageDraw, ImageFont
import os

def add_watermark_bottom(input_image_path, output_image_path, text):
    # 1. 打开图片
    img = Image.open(input_image_path)
    width, height = img.size
    
    # 2. 裁切掉顶部 13%
    top_crop_height = int(height * 0.13)
    img = img.crop((0, top_crop_height, width, height))
    
    # 裁切后重新获取新的尺寸
    width, height = img.size
    
    # 3. 新增：在底部增加 4% 的白边
    border_height = max(1, int(height * 0.04)) # 计算 5% 的高度
    new_height = height + border_height
    
    # 创建一个新的白色背景图片 (RGBA模式)
    new_img = Image.new('RGBA', (width, new_height), (255, 255, 255, 255))
    
    # 将裁切后的原图贴到新图的顶部 (0, 0) 位置
    new_img.paste(img.convert('RGBA'), (0, 0))
    
    # 将 img 替换为加了白边的新图，并更新尺寸变量
    img = new_img
    width, height = img.size
    
    # 4. 准备添加水印
    draw = ImageDraw.Draw(img)
    
    # 设置字体和大小
    try:
        font_size = max(20, int(width / 25))
        # Mac 通常在 /System/Library/Fonts/STHeiti Light.ttc
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Light.ttc", font_size)
    except IOError:
        font = ImageFont.load_default()
        print(f"警告: 未找到指定字体，{input_image_path} 将使用默认字体（可能不支持中文）")

    # 5. 获取文字大小以计算位置
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # 6. 设置文字位置（底部居中）
    # 这里的 height 已经是包含白边的新高度了，所以水印会自动往下移
    x = (width - text_width) / 2
    y = height - text_height - 20 # 距离最底部20像素
    
    # 7. 画一个半透明的黑色背景条让文字更清晰
    overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle(
        [(0, y - 10), (width, y + text_height + 10)],
        fill=(0, 0, 0, 128) # 半透明黑色
    )
    img = Image.alpha_composite(img, overlay)
    
    # 重新获取draw对象
    draw = ImageDraw.Draw(img)
    
    # 8. 写入文字 (白色)
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    
    # 9. 转回 RGB 并保存
    img.convert('RGB').save(output_image_path, quality=95)
    print(f"处理完成: {os.path.basename(output_image_path)}")


# 使用示例：批量处理当前目录下所有的jpg/png图片
if __name__ == "__main__":
    # 配置信息
    text_to_add = "想看更多？苹果store下载“国外消息”应用"
    
    # 1. 定义目标文件夹路径
    target_folder = "/Users/yanzhang/Downloads/"
    
    # 检查文件夹是否存在
    if not os.path.exists(target_folder):
        print(f"错误：找不到目录 {target_folder}")
    else:
        # 2. 遍历指定文件夹下的文件
        for filename in os.listdir(target_folder):
            # 处理 jpg, png, jpeg 格式
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                # 排除已经是 watermarked_ 开头的文件，防止重复处理
                if filename.startswith('watermarked_'):
                    continue
                
                input_path = os.path.join(target_folder, filename)
                output_name = f"watermarked_{filename}"
                output_path = os.path.join(target_folder, output_name)
                
                try:
                    add_watermark_bottom(input_path, output_path, text_to_add)
                except Exception as e:
                    print(f"处理文件 {filename} 时出错: {e}")