"""
将当前失败的链接从 url_mapping.json 移入 blacklist_url.json。

用法：
    python3 404_move.py [--url <播放页URL>] [--reason <原因>]

拉黑对象的优先级：
    1) --url 显式传入（AppleScript 传入当前轮次的 URL，最精确）
    2) /tmp/downie_current_url.txt（read.py 记录的当前 URL，值为空才采用）
    3) 兜底：url_mapping.json 中第一个值为空的条目（旧行为）

blacklist 写入格式：
    "<url>": ["<url>", "404 自动拉黑（原因） | [分类] 项目名 / 渠道名 / 集名"]
"""
import os
import sys
import json
import stat
import argparse
import tempfile

MAPPING_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/url_mapping.json'
BLACKLIST_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/blacklist_url.json'
OVIDEOS_FILE = '/Users/yanzhang/Coding/LocalServer/Resources/OVideo/OVideos.json'
CURRENT_URL_FILE = '/tmp/downie_current_url.txt'

REASON_PREFIX = '404 自动拉黑'
LABEL_MAX_MATCHES = 3  # 同一 URL 出现在多个项目/渠道时，最多列出几处


# ==========================================================
# 基础工具
# ==========================================================
def fail(msg, code=1):
    """以非 0 退出码终止：AppleScript 会捕获并安全停止，绝不带病继续"""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json_strict(path, desc, default=None):
    """
    读取 JSON：
      - 文件不存在：有 default 则返回 default，否则终止
      - 文件损坏：一律终止（旧版会用 {} 覆盖黑名单，导致整个黑名单丢失）
    """
    if not os.path.exists(path):
        if default is not None:
            return default
        fail(f"{desc}不存在：{path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        fail(f"{desc}读取/解析失败（{e}），为防止覆盖损坏数据已终止：{path}")


def atomic_write_json(path, data):
    """原子写入并保留原文件权限（与 write.py / read.py 一致）"""
    dir_name = os.path.dirname(path) or '.'
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_current_url():
    try:
        with open(CURRENT_URL_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def clear_current_url_if(key):
    """只有状态文件记录的正是本次拉黑的 key 时才清除，避免误删"""
    if read_current_url() == key:
        try:
            os.remove(CURRENT_URL_FILE)
        except OSError:
            pass


# ==========================================================
# 在 OVideos.json 中查找 URL 对应的「项目 / 渠道 / 集」
# ==========================================================
def lookup_episode_labels(target_url):
    if not os.path.exists(OVIDEOS_FILE):
        return []
    try:
        with open(OVIDEOS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  OVideos.json 读取失败，无法补充项目信息：{e}")
        return []
    if not isinstance(data, dict):
        return []

    labels, seen = [], set()
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_name = item.get('name') or item.get('title') or '未命名项目'
            for pl in item.get('playlist', []) or []:
                if not isinstance(pl, dict):
                    continue
                channel = str(pl.get('name') or '').strip() or '未命名渠道'
                eps = pl.get('episodes', {}) or {}
                if isinstance(eps, dict):
                    pairs = eps.items()
                elif isinstance(eps, list):
                    pairs = ((f"第{i}条", u) for i, u in enumerate(eps, 1))
                else:
                    continue
                for ep_name, ep_url in pairs:
                    if ep_url == target_url:
                        label = f"[{category}] {item_name} / {channel} / {ep_name}"
                        if label not in seen:
                            seen.add(label)
                            labels.append(label)
    return labels


def build_note(url, reason):
    head = REASON_PREFIX + (f"（{reason}）" if reason else "")
    labels = lookup_episode_labels(url)
    if not labels:
        return f"{head} | 未在 OVideos.json 中找到对应项目"
    text = "；".join(labels[:LABEL_MAX_MATCHES])
    if len(labels) > LABEL_MAX_MATCHES:
        text += f"；等共 {len(labels)} 处"
    return f"{head} | {text}"


# ==========================================================
# 确定拉黑目标
# ==========================================================
def resolve_target(mapping, explicit_url):
    if explicit_url:
        return explicit_url, '参数 --url'
    cur = read_current_url()
    if cur:
        if mapping.get(cur) == "":
            return cur, '当前 URL 状态文件'
        print(f"⚠️  状态文件记录的 URL 不是待填写状态，回退为第一个空值条目：{cur}")
    for k, v in mapping.items():
        if v == "":
            return k, '第一个空值条目（兜底）'
    return None, None


def main():
    p = argparse.ArgumentParser(description='将失败链接从 url_mapping 移入 blacklist')
    p.add_argument('--url', default='', help='要拉黑的播放页 URL（mapping key）')
    p.add_argument('--reason', default='', help='拉黑原因（写入 blacklist 备注）')
    args = p.parse_args()

    mapping = load_json_strict(MAPPING_FILE, "映射文件")
    if not isinstance(mapping, dict):
        fail(f"映射文件结构异常（非对象），已终止：{MAPPING_FILE}")

    key, source = resolve_target(mapping, (args.url or '').strip())
    if not key:
        print("未找到需要拉黑的链接（无 --url、无状态文件、无空值条目），直接结束。")
        return 0

    print(f"检测到待拉黑的链接: {key}（来源：{source}）")

    # 防误删：已有映射值的条目说明下载成功过，拒绝拉黑
    if key in mapping and mapping[key] != "":
        print(f"ℹ️  该 key 已有映射值，不予拉黑（防误删）：{key}")
        return 0

    blacklist = load_json_strict(BLACKLIST_FILE, "黑名单文件", default={})
    if not isinstance(blacklist, dict):
        fail(f"黑名单文件结构异常（非对象），已终止：{BLACKLIST_FILE}")

    note = build_note(key, (args.reason or '').strip())

    # 先写黑名单再删 mapping：任何一步中断都不会丢数据
    blacklist[key] = [key, note]
    atomic_write_json(BLACKLIST_FILE, blacklist)
    print(f"✅ 已加入 blacklist_url.json: {key}")
    print(f"   备注: {note}")

    if key in mapping:
        del mapping[key]
        atomic_write_json(MAPPING_FILE, mapping)
        print(f"✅ 已从 url_mapping.json 删除该条目: {key}")
    else:
        print("ℹ️  该 key 不在 url_mapping.json 中，仅写入 blacklist（防止 read.py 再次抓取）。")

    clear_current_url_if(key)
    print("✅ 拉黑任务完成！")
    return 0


if __name__ == '__main__':
    sys.exit(main())