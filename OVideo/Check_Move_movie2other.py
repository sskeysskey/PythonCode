import json
import os

# 定义文件路径
json_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
log_path = "/Users/yanzhang/Downloads/a.txt"

# ===================== 新增白名单区域 =====================
# 把日志输出里所有需要豁免、不参与筛选的片名放这里
white_list_names = [
    "战争与和平",
    "海狼",
    "变形金刚：超能勇士崛起",
    "世界",
    "帝国的毁灭",
    "红番区",
    "欢迎来到雷克瑟姆 第五季",
    "波斯行",
    "人生不过几顿饭",
    "“皮行者牧场”的秘密 第七季",
    "风暴中心：追逐者 第一季"
]
# ==========================================================

# 确保日志目录存在
os.makedirs(os.path.dirname(log_path), exist_ok=True)

# 读取 JSON 数据
try:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception as e:
    print(f"读取 JSON 文件失败: {e}")
    exit(1)

# 初始化分类列表（防止 key 不存在）
if "Movie" not in data: data["Movie"] = []
if "Drama" not in data: data["Drama"] = []
if "Anime" not in data: data["Anime"] = []

movies_to_keep = []
moved_logs = []
skip_white_logs = []  # 记录白名单跳过的日志

# 遍历 Movie 列表
for movie in data["Movie"]:
    movie_name = movie.get("name", "未知名称")
    playlist = movie.get("playlist", [])

    # ========== 新增白名单判断逻辑 ==========
    if movie_name in white_list_names:
        movies_to_keep.append(movie)
        skip_msg = f"【白名单跳过】项目: 《{movie_name}》 | 豁免筛选，保留在Movie分类"
        skip_white_logs.append(skip_msg)
        continue  # 直接跳过后续剧集判断、移动逻辑
    # ========================================

    # 1. 获取前两个渠道
    channels_to_check = playlist[:2]
    
    # 找出前两个渠道中，剧集数量最多的那个渠道及其数量
    max_ep_count = 0
    max_channel_name = "无渠道"
    
    for channel in channels_to_check:
        channel_name = channel.get("name", "未知渠道")
        episodes = channel.get("episodes", {})
        ep_count = len(episodes)
        if ep_count > max_ep_count:
            max_ep_count = ep_count
            max_channel_name = channel_name
            
    # 2. 判断最大剧集数是否大于等于 4
    if max_ep_count >= 4:
        # 3. 决定移动到 Anime 还是 Drama
        genres = movie.get("类型", [])
        actors = movie.get("主演", [])
        
        # 判断类型是否包含“动画”或“动漫”
        has_anime_genre = any("动画" in g or "动漫" in g for g in genres)
        # 判断主演是否为空
        is_actors_empty = not actors  # 列表为空即为 True
        
        target_category = ""
        reason = ""
        
        if has_anime_genre or is_actors_empty:
            target_category = "Anime"
            reason_details = []
            if has_anime_genre: reason_details.append("类型包含动画/动漫")
            if is_actors_empty: reason_details.append("主演字段为空")
            reason = " & ".join(reason_details)
        else:
            target_category = "Drama"
            reason = f"最大渠道剧集数({max_ep_count}集)>=4，且不满足Anime条件（类型无动画/动漫且主演不为空）"
            
        # 执行移动
        data[target_category].append(movie)
        
        # 记录日志
        log_msg = (f"【移动成功】项目: 《{movie_name}》 | "
                   f"原分类: Movie -> 新分类: {target_category} | "
                   f"触发条件: 前两个渠道中剧集数最多的是【{max_channel_name}】共 {max_ep_count} 集 (>=4) | "
                   f"归入原因: [{reason}]")
        moved_logs.append(log_msg)
    else:
        # 最大剧集数不足 4，保留在 Movie 中
        movies_to_keep.append(movie)

# 更新 Movie 列表
data["Movie"] = movies_to_keep

# 将更新后的数据写回 JSON 文件
try:
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print("JSON 数据更新成功！")
except Exception as e:
    print(f"写入 JSON 文件失败: {e}")

# 写入日志文件
try:
    with open(log_path, 'w', encoding='utf-8') as f:
        total_logs = []
        # 先输出白名单跳过记录
        if skip_white_logs:
            total_logs.extend(skip_white_logs)
        # 再输出正常移动记录
        if moved_logs:
            total_logs.extend(moved_logs)
        
        if total_logs:
            f.write("\n".join(total_logs) + "\n")
            print(f"白名单跳过 {len(skip_white_logs)} 个项目，成功移动 {len(moved_logs)} 个项目，日志已输出至: {log_path}")
        else:
            f.write("本次运行未发现符合移动条件的项目，无白名单跳过项目。\n")
            print("未发现符合移动条件的项目，无白名单跳过项目。")
except Exception as e:
    print(f"写入日志文件失败: {e}")