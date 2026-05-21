import json
import os
from send2trash import send2trash

def clean_unused_images():
    # 定义路径
    json_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
    image_dir = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image'

    # 1. 收集 JSON 中所有被引用的图片名称
    referenced_images = set()
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 遍历所有分类 (Movie, Drama, Show, Anime)
            for category, items in data.items():
                if isinstance(items, list):
                    for item in items:
                        image_name = item.get('image')
                        if image_name:
                            referenced_images.add(image_name)
        
        print(f"成功从 JSON 中提取到 {len(referenced_images)} 个引用的图片。")
        
    except Exception as e:
        print(f"读取 JSON 失败: {e}")
        return

    # 2. 扫描目录并删除未引用的图片
    if not os.path.exists(image_dir):
        print(f"错误：找不到图片目录: {image_dir}")
        return

    deleted_count = 0
    all_files = os.listdir(image_dir)
    
    print("正在扫描并清理...")
    
    for filename in all_files:
        # 过滤：只处理图片文件，跳过系统文件
        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            if filename not in referenced_images:
                file_path = os.path.join(image_dir, filename)
                try:
                    # 将文件移动到垃圾箱
                    send2trash(file_path)
                    print(f"已移至垃圾箱: {filename}")
                    deleted_count += 1
                except Exception as e:
                    print(f"无法删除 {filename}: {e}")

    print(f"\n清理完成！共移动了 {deleted_count} 个文件到垃圾箱。")

if __name__ == '__main__':
    clean_unused_images()