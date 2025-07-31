import os
import shutil
import glob

def move_and_record_images():
    """
    移动多种格式图片并记录到article_copier.txt
    """
    source_dir = "/Users/yanzhang/Downloads"
    today = datetime.now().strftime("%y%m%d")
    target_dir = f"/Users/yanzhang/Downloads/news_image_{today}"
    record_file = f"/Users/yanzhang/Coding/News/article_copier_{today}.txt"
    
    # 支持的图片格式
    image_formats = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.avif", "*.gif"]

    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(os.path.dirname(record_file), exist_ok=True)

    # 获取所有图片文件
    image_files = []
    for format in image_formats:
        image_files.extend(glob.glob(os.path.join(source_dir, format)))
    moved_files = []

    # 移动文件
    for image_file in image_files:
        filename = os.path.basename(image_file)
        target_path = os.path.join(target_dir, filename)
        shutil.move(image_file, target_path)
        moved_files.append(filename)

    # 写入记录文件，无论是否有移动文件都写入URL
    if moved_files:
        content = "\n".join(moved_files) + "\n\n"
    
    with open(record_file, 'a', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':    
    move_and_record_images()