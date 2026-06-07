# 你的原始数据（已自动修复格式）
data = {
"https://www.pys2.com/py/483804-1-32.html": [
        "https://vip.dytt-tvs.com/20260424/17741_87bcf871/index.m3u8",
        "《今夜喜友秀》 20260418afterparty - 综艺"
    ],
    "https://www.pys2.com/py/483804-1-33.html": [
        "https://vip.dytt-tvs.com/20260424/17719_e1c9f6b9/index.m3u8",
        "《今夜喜友秀》 20260424上 - 综艺"
    ],
    "https://www.pys2.com/py/483804-1-34.html": [
        "https://vip.dytt-tvs.com/20260424/17726_920ef47b/index.m3u8",
        "《今夜喜友秀》 20260424下 - 综艺"
    ],
    "https://www.pys2.com/py/483804-1-35.html": [
        "https://vip.dytt-tvs.com/20260425/17872_89c1df48/index.m3u8",
        "《今夜喜友秀》 20260424纯享 - 综艺"
    ],
    "https://www.pys2.com/py/483804-1-36.html": [
        "https://vip.dytt-tvs.com/20260425/17872_89c1df48/index.m3u8",
        "《今夜喜友秀》 20260425afterparty - 综艺"
    ],
}

# ===================== 【通用逻辑】完全按顺序替换 =====================
# 1. 把字典转成有序列表
items = list(data.items())
n_total = len(items)

# 2. 保存所有原始 value1（防止覆盖后丢失）
original_values = [item[1][0] for item in items]

# 3. 按你的通用规则处理
for i in range(n_total):
    key, value_list = items[i]
    
    if i == 0:
        # 第一个 → 置空
        value_list[0] = ""
    elif i == n_total - 1:
        # 最后一个 → 不动
        continue
    else:
        # 其他 → 用【前一个原始值】覆盖当前
        value_list[0] = original_values[i - 1]

# 4. 输出最终结果
print("处理完成，最终数据：\n")
for key, value in data.items():
    print(f'"{key}": [')
    print(f'    "{value[0]}",')
    print(f'    "{value[1]}"')
    print(f'],')