def choice():
    print("--- 新闻与图片合并工具 ---")
    print("1: 退出程序")
    print("2: 合并最新的 2 份新闻和图片")
    print("3: 合并最新的 3 份新闻和图片")
    
    choice = input("请输入您的选择 (1, 2, or 3): ")
    
    if choice == '1':
        print("已选择退出，程序结束。")
        return
        
    elif choice in ['2', '3']:
        num_to_merge = int(choice)
        print(f"\n您已选择合并最新的 {num_to_merge} 份内容。")
        
        # --- 步骤 1: 处理 JSON 文件 ---
        print("\n--- 正在处理JSON文件... ---")
        json_sources = find_latest_sources(JSON_DIR, 'onews_', '.json', num_to_merge)
        
        if len(json_sources) < num_to_merge:
            print(f"警告：只找到了 {len(json_sources)} 个带时间戳的JSON文件，少于您希望合并的 {num_to_merge} 个。")
        
        if not json_sources:
            print("错误：在目录下未找到任何匹配的 'onews_YYMMDD.json' 文件。")
        else:
            print(f"找到以下 {len(json_sources)} 个最新的JSON文件进行合并:")
            for src in json_sources:
                print(f"  - {os.path.basename(src)}")
            target_json_file = os.path.join(JSON_DIR, 'onews.json')
            merge_json_files(json_sources, target_json_file)

        # --- 步骤 2: 处理图片目录 ---
        print("\n--- 正在处理图片目录... ---")
        # 图片目录没有后缀，所以 suffix 参数传空字符串 ''
        image_sources = find_latest_sources(IMAGE_BACKUP_DIR, 'news_images_', '', num_to_merge)

        if len(image_sources) < num_to_merge:
            print(f"警告：只找到了 {len(image_sources)} 个带时间戳的图片目录，少于您希望合并的 {num_to_merge} 个。")

        if not image_sources:
            print("错误：在目录下未找到任何匹配的 'news_images_YYMMDD' 目录。")
        else:
            print(f"找到以下 {len(image_sources)} 个最新的图片目录进行合并:")
            for src in image_sources:
                print(f"  - {os.path.basename(src)}")
            target_image_dir = os.path.join(IMAGE_BACKUP_DIR, 'news_images')
            merge_image_dirs(image_sources, target_image_dir)
            
        print("\n所有操作已完成。")

    else:
        print("无效输入。请输入 1, 2, 或 3。")