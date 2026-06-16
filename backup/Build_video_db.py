# build_video_db.py
# 用法：python3 build_video_db.py
# 每次更新 OVideos.json / url_mapping.json 后执行一次

import os, json, sqlite3

# 直接写死你的 Mac 本地路径
OVIDEO_DIR = "/Users/yanzhang/Coding/LocalServer/Resources/OVideo"
DB_PATH = os.path.join(OVIDEO_DIR, "ovideo.db")


def build():
    video_file = os.path.join(OVIDEO_DIR, "OVideos.json")
    mapping_file = os.path.join(OVIDEO_DIR, "url_mapping.json")

    with open(video_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    valid_urls = set()
    if os.path.exists(mapping_file):
        with open(mapping_file, "r", encoding="utf-8") as f:
            valid_urls = set(json.load(f).keys())

    # 写到临时库，最后原子替换，避免运行期间被读到半成品
    tmp_path = DB_PATH + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            category TEXT,
            seq INTEGER,
            name TEXT,
            region TEXT,
            types_text TEXT,
            best_rating REAL,
            release_sort_key TEXT,
            update_sort_key TEXT,
            list_json TEXT,          -- 轻字段（不含 playlist）
            detail_json TEXT         -- 仅 playlist
        )
    ''')
    c.execute('CREATE TABLE categories (name TEXT PRIMARY KEY, ord INTEGER)')

    total = 0
    for ord_idx, (category, items) in enumerate(data.items()):
        c.execute('INSERT OR REPLACE INTO categories VALUES (?,?)', (category, ord_idx))
        seq = 0
        for item in items:
            # 1. 过滤 playlist（与原 /videos 逻辑一致，并写入 episode_order）
            new_item = dict(item)
            filtered_playlist = []
            for channel in item.get('playlist', []):
                eps = {}
                order = []
                for ep_name, ep_url in channel.get('episodes', {}).items():
                    if ep_url in valid_urls or '.m3u8' in ep_url.lower():
                        eps[ep_name] = ep_url
                        order.append(ep_name)
                if eps:
                    nc = dict(channel)
                    nc['episodes'] = eps
                    nc['episode_order'] = order
                    filtered_playlist.append(nc)
            new_item['playlist'] = filtered_playlist
            
            # detail：只放 playlist，进详情页才拉
            detail_json = json.dumps({"playlist": filtered_playlist}, ensure_ascii=False)

            # list：去掉 playlist 的轻量版本
            list_item = dict(new_item)
            list_item.pop('playlist', None)
            list_json = json.dumps(list_item, ensure_ascii=False)

            # 2. 排序键（与 Swift 端 performSort 完全一致）
            update_sort = item.get('update') or ''
            raw_date = item.get('date') or ''
            release_sort = raw_date.split('(')[0] if raw_date else ''

            ratings = item.get('评分') or {}
            best_rating = 0.0
            for v in ratings.values():
                try:
                    best_rating = max(best_rating, float(v))
                except (TypeError, ValueError):
                    pass

            # 3. 类型文本（用于按关键词子串屏蔽）
            types = item.get('类型') or []
            if isinstance(types, str):
                types = [types]
            types_text = ('|' + '|'.join(types) + '|') if types else ''

            region = item.get('地区') or ''

            c.execute('''INSERT INTO videos
                (url, category, seq, name, region, types_text,
                 best_rating, release_sort_key, update_sort_key, list_json, detail_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (item.get('url', ''), category, seq, item.get('name', ''),
                 region, types_text, best_rating, release_sort, update_sort,
                 list_json, detail_json))
            seq += 1
            total += 1

    # 索引：覆盖三种排序 + 分类
    c.execute('CREATE INDEX idx_url ON videos(url)')
    c.execute('CREATE INDEX idx_cat_seq ON videos(category, seq)')
    c.execute('CREATE INDEX idx_cat_update ON videos(category, update_sort_key)')
    c.execute('CREATE INDEX idx_cat_release ON videos(category, release_sort_key)')
    c.execute('CREATE INDEX idx_cat_rating ON videos(category, best_rating, release_sort_key)')

    conn.commit()
    conn.close()

    # 原子替换
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    os.rename(tmp_path, DB_PATH)
    print(f"✅ 建库完成：{total} 条，输出 {DB_PATH}")


if __name__ == '__main__':
    build()