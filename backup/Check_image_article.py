import os

def check_files():
    today = datetime.now().strftime("%y%m%d")
    image_dir = f'/Users/yanzhang/Downloads/news_image_{today}'
    txt_file = f"/Users/yanzhang/Documents/News/article_copier_{today}.txt"
    
    # 读取txt文件内容
    with open(txt_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 获取图片目录下所有文件
    image_files = os.listdir(image_dir)
    
    # 检查每个图片文件是否在txt内容中
    missing_files = []
    for img_file in image_files:
        if img_file not in content:
            missing_files.append(img_file)
    
    # 输出结果
    if missing_files:
        print("以下文件在txt中未找到：")
        for file in missing_files:
            print(file)
    else:
        print("所有文件都在txt中找到了")

if __name__ == "__main__":
    check_files()