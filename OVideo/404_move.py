import os
import json
import re
import sys

MAPPING_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
BLACKLIST_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'


def main():
    # ============ 1. 读取 url_mapping.json ============
    if not os.path.exists(MAPPING_FILE):
        print(f"ERROR: 映射文件不存在：{MAPPING_FILE}")
        sys.exit(1)

    with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # ============ 2. 查找"值为空"的那一行（即当前失败的链接）============
    empty_line_idx = -1
    extracted_url = ""

    for i, line in enumerate(lines):
        # 去掉尾部换行/逗号/空格后，判断是否以 "" 结尾（值为空）
        stripped = line.rstrip('\n').rstrip().rstrip(',').rstrip()
        if stripped.endswith('""'):
            # 用正则提取冒号左边的 URL
            match = re.search(r'"([^"]+)"\s*:\s*""', line)
            if match:
                empty_line_idx = i
                extracted_url = match.group(1)
                break

    if empty_line_idx == -1 or not extracted_url:
        # 没有空值行说明没有需要处理的失败链接，直接安全退出（不报错，避免 AppleScript 中断）
        print("未在 url_mapping.json 中找到值为空的行，无需拉黑，直接结束。")
        return

    print(f"检测到待拉黑的链接: {extracted_url}")

    # ============ 3. 从 url_mapping.json 删除该空值行 ============
    del lines[empty_line_idx]

    # 修复 JSON 格式：删掉行后，处理可能出现的"末尾多余逗号"
    for j in range(len(lines) - 1, -1, -1):
        if '}' in lines[j]:
            for k in range(j - 1, -1, -1):
                if lines[k].strip():
                    stripped_k = lines[k].rstrip('\n\r ')
                    if stripped_k.endswith(','):
                        lines[k] = stripped_k[:-1] + '\n'
                    break
            break

    with open(MAPPING_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"✅ 已从 url_mapping.json 删除该行: {extracted_url}")

    # ============ 4. 写入 blacklist_url.json ============
    blacklist_data = {}
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                blacklist_data = json.load(f)
        except json.JSONDecodeError:
            # 文件损坏或为空时，用空字典兜底
            blacklist_data = {}

    # 与 write.py 的黑名单格式保持一致：{ url: [说明, url] }
    # 由于失败场景没有下载文件名，这里用一个说明字段占位；
    # read.py 只用 key（即 url）做判断，value 不影响过滤。
    blacklist_data[extracted_url] = ["ignore/404 自动拉黑", extracted_url]

    with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(blacklist_data, f, ensure_ascii=False, indent=4)
    print(f"✅ 已加入 blacklist_url.json: {extracted_url}")

    print("✅ 拉黑任务完成！")


if __name__ == '__main__':
    main()