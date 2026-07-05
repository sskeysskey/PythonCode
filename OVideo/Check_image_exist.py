import json
import os
from datetime import datetime

# ===================== 你只需要确认这两个路径 =====================
JSON_PATH = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
IMAGE_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/cover_image"
# ==================================================================

# 日志文件（会自动生成在当前目录）
LOG_FILE = f"缺失图片检查日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

# 存储结果
missing_images = []
all_images = []

try:
    # 1. 读取 JSON
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 2. 遍历所有分类（Movie / Drama / Show / Anime）
    for category, items in data.items():
        if not isinstance(items, list):
            continue

        for item in items:
            name = item.get("name", "未知名称")
            image = item.get("image", "").strip()

            # 只处理有 image 内容的项
            if image:
                all_images.append((category, name, image))
                image_path = os.path.join(IMAGE_DIR, image)

                # 检查文件是否存在
                if not os.path.exists(image_path):
                    missing_images.append((category, name, image))

    # 3. 输出控制台 + 写入日志
    log_content = []
    log_content.append("=" * 60)
    log_content.append(f"图片缺失检查报告 - {datetime.now()}")
    log_content.append("=" * 60)
    log_content.append(f"📂 图片目录：{IMAGE_DIR}")
    log_content.append(f"📄 检查JSON：{JSON_PATH}")
    log_content.append(f"🔍 共检查图片数量：{len(all_images)}")
    log_content.append(f"❌ 缺失图片数量：{len(missing_images)}")
    log_content.append("=" * 60)
    log_content.append("")

    if missing_images:
        log_content.append("【缺失图片列表】")
        log_content.append("-" * 50)
        for idx, (cate, name, img) in enumerate(missing_images, 1):
            log_content.append(f"{idx}. 分类：{cate}")
            log_content.append(f"   视频：{name}")
            log_content.append(f"   缺失图片：{img}")
            log_content.append("-" * 50)
    else:
        log_content.append("✅ 所有图片都存在！")

    # 打印控制台
    final_log = "\n".join(log_content)
    print(final_log)

    # 写入日志文件
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(final_log)

    print(f"\n📝 日志已保存到：{LOG_FILE}")

except Exception as e:
    print(f"❌ 出错：{str(e)}")