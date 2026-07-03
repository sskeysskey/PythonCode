import json
import os
import shutil
from datetime import datetime

BASE = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo"
WHITELIST = "/Users/yanzhang/Coding/python_code/OVideo"
OVIDEOS_PATH = os.path.join(BASE, "OVideos.json")
MAPPING_PATH = os.path.join(BASE, "url_mapping.json")
WHITELIST_PATH = os.path.join(WHITELIST, "huxitech_whitelist.json")

HUX = "huxitech.com"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def backup(path):
    if os.path.exists(path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(path, f"{path}.{ts}.bak")


def is_urlx_key(k):
    # 匹配 "url" 或 "url1" "url2" ...
    return k == "url" or (k.startswith("url") and k[3:].isdigit())


def get_hux_urlx(item):
    """返回该项目中 urlX 里所有 huxitech 链接的 (key, value) 列表"""
    result = []
    for k, v in item.items():
        if is_urlx_key(k) and isinstance(v, str) and HUX in v:
            result.append((k, v))
    return result


def is_hux_channel(channel):
    if not isinstance(channel, dict):
        return False
    if channel.get("name") == "huxitech":
        return True
    eps = channel.get("episodes", {})
    if isinstance(eps, dict):
        for u in eps.values():
            if isinstance(u, str) and HUX in u:
                return True
    return False


def main():
    data = load_json(OVIDEOS_PATH, {})
    mapping = load_json(MAPPING_PATH, {})
    whitelist = load_json(WHITELIST_PATH, [])
    whitelist_set = set(whitelist)

    changed = False

    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue

            name = item.get("name", "<未知>")
            playlist = item.get("playlist", [])
            if not isinstance(playlist, list):
                continue

            hux_urlx = get_hux_urlx(item)

            # 1. 白名单检查
            if any(v in whitelist_set for _, v in hux_urlx):
                print(f"[跳过-白名单] {category} / {name}")
                continue

            # 2. 判断 playlist 渠道
            hux_channels = [c for c in playlist if is_hux_channel(c)]
            other_channels = [c for c in playlist if not is_hux_channel(c)]

            if not hux_channels:
                continue  # 没有 huxitech 渠道，不处理

            if not other_channels:
                print(f"[跳过-仅huxitech] {category} / {name}")
                continue  # 只有 huxitech，保留不动

            # 3. 执行删除
            # 3a. 收集 huxitech 渠道里的所有 episode url
            hux_ep_urls = []
            for c in hux_channels:
                eps = c.get("episodes", {})
                if isinstance(eps, dict):
                    hux_ep_urls.extend([u for u in eps.values() if isinstance(u, str)])

            # 3b. 从 playlist 删除 huxitech 渠道
            item["playlist"] = other_channels

            # 3c. 删除 urlX 里的 huxitech 链接（原地删除），并加入白名单
            for k, v in hux_urlx:
                del item[k]
                whitelist_set.add(v)

            # 3d. 删除 url_mapping 里命中的条目
            for u in hux_ep_urls:
                if u in mapping:
                    del mapping[u]
                    print(f"    - 删除 mapping: {u}")

            print(f"[已处理] {category} / {name}")
            changed = True

    # 保存
    if changed:
        backup(OVIDEOS_PATH)
        backup(MAPPING_PATH)
        save_json(OVIDEOS_PATH, data)
        save_json(MAPPING_PATH, mapping)

    backup(WHITELIST_PATH)
    save_json(WHITELIST_PATH, sorted(whitelist_set))

    print("\n完成。白名单当前条目数：", len(whitelist_set))


if __name__ == "__main__":
    main()