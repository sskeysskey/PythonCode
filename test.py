def backup_news_assets(local_dir): # <--- 修改函数签名
    
    
    # 源目录和备份目录
    src_dir = "/Users/yanzhang/Downloads/news_images"
    backup_dir = "/Users/yanzhang/Downloads/backup"
    
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(local_dir, exist_ok=True)
    
    if os.path.exists(src_dir):
        # 1) 备份到 Downloads/backup
        backup_img_target = os.path.join(backup_dir, f"news_images_{timestamp}")
        if os.path.exists(backup_img_target):
            shutil.rmtree(backup_img_target)
        shutil.copytree(src_dir, backup_img_target)
        print(f"图片目录已备份到: {backup_img_target}")
        
        # 2) 备份到 LocalServer
        local_img_target = os.path.join(local_dir, f"news_images_{timestamp}")
        if os.path.exists(local_img_target):
            shutil.rmtree(local_img_target)
        shutil.copytree(src_dir, local_img_target)
        print(f"图片目录也已备份到: {local_img_target}")
        
        # 3) 删除原目录
        shutil.rmtree(src_dir)
        print(f"已删除原始图片目录: {src_dir}")
    else:
        print(f"未找到源图片目录: {src_dir}")
    
    # --------- 备份 onews.json 文件 ---------
    src_file = "/Users/yanzhang/Coding/News/onews.json"
    backup_file_dir = "/Users/yanzhang/Coding/News/done"
    
    os.makedirs(backup_file_dir, exist_ok=True)
    
    if os.path.exists(src_file):
        # 1) 备份到 Coding/News/done
        backup_file_target = os.path.join(backup_file_dir, f"onews_{timestamp}.json")
        shutil.copy2(src_file, backup_file_target)
        print(f"JSON文件已备份到: {backup_file_target}")
        
        # 2) 备份到 LocalServer
        local_file_target = os.path.join(local_dir, f"onews_{timestamp}.json")
        shutil.copy2(src_file, local_file_target)
        print(f"JSON文件也已备份到: {local_file_target}")
        
        # 3) 删除原文件
        os.remove(src_file)
        print(f"已删除原始JSON文件: {src_file}")
    else:
        print(f"未找到源JSON文件: {src_file}")
    
    # --------- 更新 version.json ---------
    update_version_json(local_dir, timestamp)