import json
import os

# 定义文件路径
json_file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'
mapping_file_path = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
log_file_path = '/Users/yanzhang/Downloads/a.txt'
dup_log_path = '/Users/yanzhang/Downloads/b.txt'


def load_json(path):
    """读取 json 文件，不存在则返回空字典"""
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # 文件为空或格式错误时，视为空字典
            return {}


def fix_url_mapping():
    # 检查 JSON 文件是否存在
    if not os.path.exists(json_file_path):
        print(f"找不到文件: {json_file_path}")
        return

    # 读取 blacklist_url.json
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 读取 url_mapping.json（用于去重判断和后续写入）
    mapping_data = load_json(mapping_file_path)

    fixed_count = 0        # 总共纠正的条数
    logged_count = 0       # 实际写入日志的条数（不含 % / ignore-404 的）
    log_messages = []

    # 待写入 url_mapping 的条目 {key: [url, desc]}
    entries_to_map = {}

    # 遍历 JSON 中的所有键值对
    for key, value in data.items():
        # 确保值是一个列表，并且至少包含两个元素
        if isinstance(value, list) and len(value) >= 2:
            item1, item2 = value[0], value[1]

            # 先判断 item1 和 item2 是不是字符串 (str)
            if isinstance(item1, str) and isinstance(item2, str):
                # 判断第一个元素是否不是链接，且第二个元素是链接
                if not item1.startswith('http') and item2.startswith('http'):
                    # 互换位置
                    data[key][0], data[key][1] = item2, item1
                    fixed_count += 1

                    # 规则1：如果待纠正的 url 中包含 "%"，则只纠正、不写日志
                    if '%' in item1 or '%' in item2:
                        continue

                    # 规则2（新增 a）：非 url 的 value 中包含 "ignore/404"，只纠正、不写日志
                    if 'ignore/404' in item1:
                        continue

                    logged_count += 1
                    # 记录日志信息（注意分隔线用 + 单独拼接）
                    log_messages.append(
                        f"【修正】键 (Key): {key}\n"
                        f"  -> 原顺序: [\n      \"{item1}\",\n      \"{item2}\"\n     ]\n"
                        f"  -> 新顺序: [\n      \"{item2}\",\n      \"{item1}\"\n     ]\n"
                        + "-" * 50 + "\n"
                    )

                    # 新增 b：既输出又纠正的完整条目，纳入待写入 url_mapping 的集合
                    # 此时 data[key] 已是 [item2(url), item1(desc)]，结构与 url_mapping 一致
                    entries_to_map[key] = data[key]


    # ===== 处理 url_mapping 的写入与去重 =====
    written_count = 0      # 实际写入 url_mapping 的条数
    dup_count = 0          # 因 key 重复而未写入的条数
    dup_messages = []      # 重复条目日志（写入 b.txt）

    for key, val in entries_to_map.items():
        if key in mapping_data:
            # 发现重复：不写入，记录到 b.txt（含待写入 + 已存在两部分）
            dup_count += 1
            dup_messages.append(
                f"【重复 · 未写入】键 (Key): {key}\n"
                f"  -> 待写入条目: [\n      \"{val[0]}\",\n      \"{val[1]}\"\n     ]\n"
                f"  -> 已存在条目: [\n      \"{mapping_data[key][0]}\",\n      \"{mapping_data[key][1]}\"\n     ]\n"
                + "=" * 50 + "\n"
            )
        else:
            # 无重复：写入 url_mapping
            mapping_data[key] = val
            written_count += 1
            
            # 【修改点】：成功进入 url_mapping 后，将其从 blacklist_url 的数据中删除，实现“移动”效果
            if key in data:
                del data[key]

    # 【修改点】：将修正后（且剔除了已移动条目）的数据写回 blacklist_url.json 文件
    # 注意：这个保存操作被移动到了 url_mapping 处理逻辑的后面
    with open(json_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # 将更新后的 mapping_data 写回 url_mapping.json
    with open(mapping_file_path, 'w', encoding='utf-8') as f:
        json.dump(mapping_data, f, ensure_ascii=False, indent=4)

    # 将修正日志写入到 a.txt
    with open(log_file_path, 'w', encoding='utf-8') as f:
        if fixed_count > 0:
            f.write(f"处理完成！共修正了 {fixed_count} 条顺序错误的记录，"
                    f"其中 {logged_count} 条已记录明细"
                    f"（{fixed_count - logged_count} 条因含有 '%' 或 'ignore/404' 未记录明细）。\n\n")
            f.writelines(log_messages)
        else:
            f.write("检查完毕，没有发现需要修正的记录。\n")

    # 将重复条目日志写入到 b.txt
    with open(dup_log_path, 'w', encoding='utf-8') as f:
        if dup_count > 0:
            f.write(f"共发现 {dup_count} 条 key 重复的条目（未写入 url_mapping），明细如下：\n\n")
            f.writelines(dup_messages)
        else:
            f.write("没有发现 key 重复的条目。\n")

    print(f"处理完成！共修正了 {fixed_count} 条记录（其中 {logged_count} 条写入了 a.txt 日志明细）。")
    print(f"url_mapping 新增写入 {written_count} 条（已从 blacklist_url 中移除），重复未写入 {dup_count} 条（保留在 blacklist_url 中）。")
    print(f"修正日志已保存至: {log_file_path}")
    print(f"重复条目日志已保存至: {dup_log_path}")


if __name__ == '__main__':
    fix_url_mapping()