import json
import os

# 定义文件路径
json_path = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json"
log_path = "/Users/yanzhang/Downloads/a.txt"

# ===================== 白名单区域 =====================
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
# ====================================================

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


def analyze_movies(movies):
    """
    第一阶段：只分析不修改。
    返回一个“计划列表”，每个元素描述对某个 movie 的处理方案。
    plan 结构: {"action": "keep"/"white"/"move", "movie": <obj>, "target": .., "log": <str>}
    """
    plans = []
    for movie in movies:
        movie_name = movie.get("name", "未知名称")
        playlist = movie.get("playlist", [])

        # ---------- 白名单判断 ----------
        if movie_name in white_list_names:
            log_msg = f"【白名单跳过】项目: 《{movie_name}》 | 豁免筛选，保留在Movie分类"
            plans.append({"action": "white", "movie": movie, "log": log_msg})
            continue

        # ---------- 计算前两个渠道中剧集数最多的渠道 ----------
        channels_to_check = playlist[:2]
        max_ep_count = 0
        max_channel_name = "无渠道"
        for channel in channels_to_check:
            channel_name = channel.get("name", "未知渠道")
            episodes = channel.get("episodes", {})
            ep_count = len(episodes)
            if ep_count > max_ep_count:
                max_ep_count = ep_count
                max_channel_name = channel_name

        # ---------- 判断是否达到移动条件 ----------
        if max_ep_count >= 4:
            genres = movie.get("类型", [])
            actors = movie.get("主演", [])
            has_anime_genre = any("动画" in g or "动漫" in g for g in genres)
            is_actors_empty = not actors

            if has_anime_genre or is_actors_empty:
                target_category = "Anime"
                reason_details = []
                if has_anime_genre: reason_details.append("类型包含动画/动漫")
                if is_actors_empty: reason_details.append("主演字段为空")
                reason = " & ".join(reason_details)
            else:
                target_category = "Drama"
                reason = f"最大渠道剧集数({max_ep_count}集)>=4，且不满足Anime条件（类型无动画/动漫且主演不为空）"

            log_msg = (f"【移动成功】项目: 《{movie_name}》 | "
                       f"原分类: Movie -> 新分类: {target_category} | "
                       f"触发条件: 前两个渠道中剧集数最多的是【{max_channel_name}】共 {max_ep_count} 集 (>=4) | "
                       f"归入原因: [{reason}]")
            plans.append({"action": "move", "movie": movie,
                          "target": target_category, "log": log_msg})
        else:
            plans.append({"action": "keep", "movie": movie, "log": None})

    return plans


# ===================== 第一阶段：分析并预览 =====================
plans = analyze_movies(data["Movie"])

white_logs = [p["log"] for p in plans if p["action"] == "white"]
move_logs = [p["log"] for p in plans if p["action"] == "move"]
move_to_anime = sum(1 for p in plans if p["action"] == "move" and p["target"] == "Anime")
move_to_drama = sum(1 for p in plans if p["action"] == "move" and p["target"] == "Drama")

print("=" * 50)
print("开始扫描 Movie 分类（预览模式，未修改任何文件）...")
print("=" * 50)

if white_logs:
    print("\n--- 白名单跳过项目 ---")
    for msg in white_logs:
        print(msg)

if move_logs:
    print("\n--- 拟移动项目 ---")
    for msg in move_logs:
        print(msg)

print("\n--- 预览统计 ---")
print(f"白名单跳过: {len(white_logs)} 个")
print(f"拟移动到 Anime: {move_to_anime} 个")
print(f"拟移动到 Drama: {move_to_drama} 个")
print(f"拟移动总计: {len(move_logs)} 个")
print("-" * 16)

# 如果没有可移动项目，直接退出
if not move_logs:
    print("\n没有发现需要移动的项目，程序退出（文件未被修改）。")
    exit(0)

# ===================== 等待用户确认 =====================
print("=" * 50)
user_input = input("请核对上方预览日志。是否确认执行移动？(输入 y 确认，其他键取消并退出): ")

if user_input.strip().lower() != 'y':
    print("已取消操作，文件未被修改。")
    exit(0)

# ===================== 第二阶段：正式执行 =====================
print("\n开始正式执行移动...")

movies_to_keep = []
for p in plans:
    if p["action"] == "move":
        data[p["target"]].append(p["movie"])
    else:
        # keep 和 white 都保留在 Movie
        movies_to_keep.append(p["movie"])

data["Movie"] = movies_to_keep

# 写回 JSON 文件
try:
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print("JSON 数据更新成功！")
except Exception as e:
    print(f"写入 JSON 文件失败: {e}")
    exit(1)

# 写入日志文件（与终端预览内容一致）
try:
    with open(log_path, 'w', encoding='utf-8') as f:
        total_logs = []
        if white_logs:
            total_logs.extend(white_logs)
        if move_logs:
            total_logs.extend(move_logs)
        total_logs.append("")
        total_logs.append("--- 执行统计 ---")
        total_logs.append(f"白名单跳过: {len(white_logs)} 个")
        total_logs.append(f"移动到 Anime: {move_to_anime} 个")
        total_logs.append(f"移动到 Drama: {move_to_drama} 个")
        total_logs.append(f"移动总计: {len(move_logs)} 个")

        f.write("\n".join(total_logs) + "\n")
    print(f"白名单跳过 {len(white_logs)} 个项目，成功移动 {len(move_logs)} 个项目，日志已输出至: {log_path}")
except Exception as e:
    print(f"写入日志文件失败: {e}")