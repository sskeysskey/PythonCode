import os
import re
import sys
import time
import tempfile
import subprocess
import webbrowser
from datetime import datetime

import pyautogui
import pyperclip
import tkinter as tk
from tkinter import messagebox
from bs4 import BeautifulSoup

# ================= 配置区域 (跨平台) =================

INJECT_MARK = "news-tools"   # 用于标记“由本脚本注入的 style / script”

USER_HOME = os.path.expanduser("~")
BASE_CODING_DIR = os.path.join(USER_HOME, "Coding")
NEWS_DIR = os.path.join(BASE_CODING_DIR, "News")
WEBSITE_NEWS_DIR = os.path.join(BASE_CODING_DIR, "Website", "news")

if os.name == 'nt':
    TEMP_DIR = tempfile.gettempdir()
else:
    TEMP_DIR = "/tmp"

TODAY_CHN_TXT = os.path.join(NEWS_DIR, "today_chn.txt")
TODAY_ALL_HTML = os.path.join(NEWS_DIR, "today_all.html")
TODAY_ENG_HTML = os.path.join(NEWS_DIR, "today_eng.html")
TODAY_WSJ_HTML = os.path.join(NEWS_DIR, "today_wsjcn.html")
TODAY_DW_HTML = os.path.join(NEWS_DIR, "today_dwcn.html")
TODAY_RFI_HTML = os.path.join(NEWS_DIR, "today_rficn.html")
TODAY_BBC_HTML = os.path.join(NEWS_DIR, "today_bbccn.html")

PROCESS_ENG_TXT = os.path.join(NEWS_DIR, "today_eng.txt")
PROCESS_JPN_TXT = os.path.join(NEWS_DIR, "today_jpn.txt")
RESULT_ENG_HTML = os.path.join(NEWS_DIR, "today_eng.html")
RESULT_JPN_HTML = os.path.join(NEWS_DIR, "today_jpn.html")

CHINESE_NEWS_FILES = [TODAY_WSJ_HTML, TODAY_DW_HTML, TODAY_RFI_HTML, TODAY_BBC_HTML]

MINIMAL_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Today News</title></head>
<body><table border="1"><thead><tr><th>site</th><th>Title</th></tr></thead><tbody></tbody></table></body>
</html>"""

# ================= JS 定义 =================
js_script = """
document.addEventListener('DOMContentLoaded', function() {
    const btn = document.createElement('button');
    btn.className = 'floating-btn';
    btn.innerText = '导出已选文章 (0)';
    document.body.appendChild(btn);

    const checkboxes = document.querySelectorAll('.news-checkbox');

    function updateCount() {
        const count = document.querySelectorAll('.news-checkbox:checked').length;
        btn.innerText = `导出已选文章 (${count})`;
    }

    checkboxes.forEach(cb => {
        cb.addEventListener('change', updateCount);
    });

    btn.addEventListener('click', function() {
        const checkedBoxes = document.querySelectorAll('.news-checkbox:checked');
        if (checkedBoxes.length === 0) {
            alert('请先勾选文章！');
            return;
        }

        let selectedData = [];
        checkedBoxes.forEach(cb => {
            const tr = cb.closest('tr');
            const linkTag = tr.querySelector('a');
            if (linkTag) {
                selectedData.push({
                    title: linkTag.innerText.trim(),
                    url: linkTag.href,
                    eng_title: tr.querySelector('.title-eng') ? tr.querySelector('.title-eng').innerText.trim() : ''
                });
            }
        });

        const jsonString = JSON.stringify(selectedData, null, 2);

        navigator.clipboard.writeText(jsonString).catch(err => {
            console.error('剪贴板复制失败:', err);
        });

        const blob = new Blob([jsonString], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = "__FILENAME_PLACEHOLDER__.json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        alert(`已成功复制到剪贴板，并触发下载 [__FILENAME_PLACEHOLDER__.json]！\\n（注意：文件通常保存在浏览器的“下载”文件夹中）`);
    });
});
"""

# ================= CSS 定义 =================
css = """
/* 全局字体和背景 */
body {
    font-size: 18px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #333;
    background: #f9f9f9;
    margin: 0;
    padding: 1rem;
    line-height: 1.6;
}
.container {
    max-width: 960px;
    margin: 0 auto;
    background: #fff;
    padding: 1.5rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    border-radius: 4px;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
}
th, td {
    padding: .75rem .5rem;
    border: 1px solid #ddd;
    text-align: left;
}
thead th {
    background: #4a90e2;
    color: #fff;
    text-transform: uppercase;
    font-size: .875rem;
}
tbody tr:nth-child(even) {
    background: #f2f2f2;
}
tbody tr:hover {
    background: #e6f7ff;
}
a {
    color: #4a90e2;
    text-decoration: none;
}
a:hover, a:focus {
    text-decoration: none;
}
td.title-eng {
    color: #666;
    font-size: 0.9em;
}
.checkbox-cell {
    text-align: center;
    width: 40px;
}
.news-checkbox {
    width: 18px;
    height: 18px;
    cursor: pointer;
}
.floating-btn {
    position: fixed;
    bottom: 30px;
    right: 30px;
    padding: 12px 24px;
    background-color: #4a90e2;
    color: white;
    border: none;
    border-radius: 5px;
    font-size: 16px;
    cursor: pointer;
    box-shadow: 0 4px 6px rgba(0,0,0,0.2);
    transition: background 0.3s;
}
.floating-btn:hover {
    background-color: #357abd;
}
"""

# ================= 通用小工具 =================

def show_error(message):
    """跨平台错误弹窗（mac 用原生对话框）"""
    print(message)
    root = tk.Tk()
    root.withdraw()
    if sys.platform == 'darwin':
        try:
            safe_msg = message.replace('"', "'")
            applescript_code = f'display dialog "{safe_msg}" buttons {{"OK"}} default button "OK"'
            subprocess.run(['osascript', '-e', applescript_code], check=True)
        except Exception:
            messagebox.showerror("错误", message)
    else:
        messagebox.showerror("错误", message)
    root.destroy()


def delete_done_txt_files(directory):
    if not os.path.exists(directory):
        return
    try:
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if filename.startswith("done_") and filename.endswith(".txt"):
                os.remove(filepath)
                print(f"已删除文件：{filename}")
    except Exception as e:
        print(f"在删除文件时发生错误：{e}")


def safe_remove(path):
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        pass


# ================= 幂等化处理的核心工具 =================

def cells(tr):
    """只取当前行的直接子单元格，避免嵌套表格干扰"""
    return tr.find_all(['td', 'th'], recursive=False)


def remove_injected_assets(soup):
    """删除本脚本以前注入过的 style / script（含没有标记的历史文件）"""
    for tag in soup.find_all('style'):
        content = tag.string or ''
        if tag.get('data-injected') == INJECT_MARK or '.floating-btn' in content:
            tag.decompose()
    for tag in soup.find_all('script'):
        content = tag.string or ''
        if tag.get('data-injected') == INJECT_MARK or 'floating-btn' in content:
            tag.decompose()
    # 运行期生成的按钮理论上不会被保存，保险起见也清一下
    for btn in soup.find_all(class_='floating-btn'):
        btn.decompose()


def strip_checkbox_cells(scope):
    """去掉所有已存在的勾选框列（表头和内容行都清），保证不会重复插入"""
    if scope is None:
        return
    for cell in scope.find_all(['td', 'th']):
        classes = cell.get('class') or []
        if 'checkbox-cell' in classes:
            cell.decompose()
    for cb in scope.find_all('input'):
        classes = cb.get('class') or []
        if 'news-checkbox' in classes:
            cb.decompose()


def split_header_and_rows(table):
    """
    把表格拆成 (表头行, 内容行列表)。
    - 凡是含 <th> 的行都视为表头；只保留第一个，其余全部丢弃（解决 <th>site</th> 出现两次）
    - 返回的 Tag 全部已从原文档 extract 出来
    """
    if table is None:
        return None, []
    header = None
    body = []
    for tr in table.find_all('tr'):
        if tr.find('th') is not None:
            if header is None:
                header = tr
            else:
                tr.extract()          # 多余的表头行直接扔掉
        else:
            body.append(tr)
    if header is not None:
        header = header.extract()
    body = [tr.extract() for tr in body]
    return header, body


def row_signature(tr):
    """用于去重：优先用链接 href，其次用整行文本"""
    a = tr.find('a')
    href = a.get('href') if a else None
    if href:
        return ('href', href.strip())
    return ('text', tr.get_text(strip=True))


def ensure_head(soup):
    if soup.head:
        return soup.head
    head = soup.new_tag('head')
    if soup.html:
        soup.html.insert(0, head)
    else:
        soup.insert(0, head)
    return head


def ensure_body(soup):
    if soup.body:
        return soup.body
    body = soup.new_tag('body')
    if soup.html:
        soup.html.append(body)
    else:
        soup.append(body)
    return body


def add_css_to_soup(soup, css_string):
    head = ensure_head(soup)
    style_tag = soup.new_tag("style")
    style_tag['data-injected'] = INJECT_MARK
    style_tag.string = css_string
    head.append(style_tag)


def render_document(soup, table, header_row, rows, output_path):
    """
    统一渲染出口（幂等）：
    去重 -> 补齐列 -> 重建 thead/tbody -> 加勾选框 -> 注入 CSS/JS -> 写盘
    """
    # 1. 去重（同一 href 只保留第一次出现的，通常是已翻译的老行）
    seen = set()
    unique_rows = []
    for tr in rows:
        sig = row_signature(tr)
        if sig in seen:
            continue
        seen.add(sig)
        unique_rows.append(tr)

    # 2. 兜底表头
    if header_row is None:
        header_row = soup.new_tag('tr')
        for name in ('site', 'Title'):
            th = soup.new_tag('th')
            th.string = name
            header_row.append(th)

    # 3. 再次清干净勾选框（关键：防止重复）
    strip_checkbox_cells(header_row)
    for tr in unique_rows:
        strip_checkbox_cells(tr)

    # 4. 列数对齐（中文行 2 列 / 英文行 3 列，统一补齐）
    col_counts = [len(cells(tr)) for tr in unique_rows] + [len(cells(header_row))]
    max_cols = max(col_counts) if col_counts else 2

    while len(cells(header_row)) < max_cols:
        th = soup.new_tag('th')
        th.string = 'Title_eng' if len(cells(header_row)) == 2 else ''
        header_row.append(th)

    for tr in unique_rows:
        while len(cells(tr)) < max_cols:
            tr.append(soup.new_tag('td'))

    # 5. 重建表格结构（thead + tbody，保证 CSS 隔行变色生效）
    table.clear()
    if not table.get('border'):
        table['border'] = '1'
    thead = soup.new_tag('thead')
    thead.append(header_row)
    table.append(thead)

    tbody = soup.new_tag('tbody')
    for tr in unique_rows:
        tbody.append(tr)
    table.append(tbody)

    # 6. 插入勾选框列（此时全表一定没有勾选框，插一次绝不重复）
    th_select = soup.new_tag('th')
    th_select['class'] = 'checkbox-cell'
    th_select.string = '选择'
    header_row.insert(0, th_select)

    for tr in unique_rows:
        td_select = soup.new_tag('td')
        td_select['class'] = 'checkbox-cell'
        checkbox = soup.new_tag('input')
        checkbox['type'] = 'checkbox'
        checkbox['class'] = 'news-checkbox'
        td_select.append(checkbox)
        tr.insert(0, td_select)

    # 7. 注入 CSS / JS（先删旧的再加新的）
    remove_injected_assets(soup)
    add_css_to_soup(soup, css)

    body = ensure_body(soup)
    script_tag = soup.new_tag("script")
    script_tag['data-injected'] = INJECT_MARK
    base_name = os.path.splitext(os.path.basename(output_path))[0]
    script_tag.string = js_script.replace('__FILENAME_PLACEHOLDER__', base_name)
    body.append(script_tag)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(str(soup))

    print(f"已写入：{output_path}（共 {len(unique_rows)} 条，去重丢弃 {len(rows) - len(unique_rows)} 条）")


# ================= 业务逻辑 =================

def load_translations():
    """读取 today_chn.txt，复制到剪贴板并返回行列表（保持你原来的行为）"""
    with open(TODAY_CHN_TXT, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    non_empty_lines = [line for line in lines if line.strip()]
    content_to_copy = ''.join(non_empty_lines).rstrip('\n')
    pyperclip.copy(content_to_copy)

    data = pyperclip.paste() or ''
    return [line for line in data.splitlines() if line.strip() != '']


def read_source_html():
    """优先 today_all.html，其次 today_eng.html"""
    if os.path.exists(TODAY_ALL_HTML):
        with open(TODAY_ALL_HTML, 'r', encoding='utf-8') as f:
            return f.read()
    print(f"未找到 {os.path.basename(TODAY_ALL_HTML)}，尝试 {os.path.basename(TODAY_ENG_HTML)}")
    with open(TODAY_ENG_HTML, 'r', encoding='utf-8') as f:
        return f.read()


def apply_translations(soup, links, translated_texts):
    """把中文回填到 <a>，并在行尾追加 title-eng 列"""
    for i, link in enumerate(links):
        eng_text = link.get_text(strip=True)
        chn_text = re.sub(r'^\d+[、.。\s：:\)）]+\s*', '', translated_texts[i])
        link.string = chn_text

        parent_td = link.find_parent('td')
        if parent_td:
            parent_tr = parent_td.find_parent('tr')
            if parent_tr:
                new_td = soup.new_tag('td')
                new_td.string = eng_text
                new_td['class'] = 'title-eng'
                parent_tr.append(new_td)


def collect_chinese_rows():
    """读取 WSJ / DW / RFI / BBC 中文文件的内容行，读完删除源文件"""
    cn_rows = []
    for cn_file in CHINESE_NEWS_FILES:
        if not os.path.exists(cn_file):
            continue
        try:
            print(f"读取并合并中文文件: {os.path.basename(cn_file)}")
            with open(cn_file, 'r', encoding='utf-8') as f:
                cn_soup = BeautifulSoup(f.read(), 'html.parser')
            table_cn = cn_soup.find('table')
            if table_cn is None:
                continue
            strip_checkbox_cells(table_cn)
            _, rows = split_header_and_rows(table_cn)
            cn_rows.extend(rows)
            safe_remove(cn_file)
        except Exception as e:
            print(f"处理文件 {os.path.basename(cn_file)} 时出错: {e}")
    return cn_rows


def open_in_browser(path):
    print(f"准备在浏览器中打开文件: {path}")
    real_path = os.path.realpath(path)
    if os.name == 'nt':
        url = 'file:///' + real_path.replace('\\', '/')
    else:
        url = 'file://' + real_path
    webbrowser.open(url, new=2)
    time.sleep(0.5)
    try:
        modifier = 'command' if sys.platform == 'darwin' else 'ctrl'
        for _ in range(4):
            pyautogui.hotkey(modifier, '=')
            time.sleep(0.2)
    except Exception:
        pass


def main():
    has_eng_source = os.path.exists(TODAY_ALL_HTML) or os.path.exists(TODAY_ENG_HTML)
    has_chn_txt = os.path.exists(TODAY_CHN_TXT)
    has_cn_files = any(os.path.exists(f) for f in CHINESE_NEWS_FILES)

    new_soup = None
    new_header = None
    new_rows = []

    if has_eng_source and not has_chn_txt:
        show_error(f"检测到英文源文件，但未找到翻译结果：{TODAY_CHN_TXT}，流程中止。")
        return

    if has_eng_source and has_chn_txt:
        translated_texts = load_translations()
        html_content = read_source_html()

        new_soup = BeautifulSoup(html_content, 'html.parser')
        target_links = [a for a in new_soup.find_all('a') if a.get('target') == '_blank']

        if len(target_links) != len(translated_texts):
            show_error(
                f"翻译完的内容行数与原英文链接的数量不匹配，请检查。"
                f"当前HTML中有 {len(target_links)} 个链接，但是翻译文本有 {len(translated_texts)} 行。"
            )
            return

        apply_translations(new_soup, target_links, translated_texts)

        new_table = new_soup.find('table')
        if new_table is None:
            show_error("英文源文件中未找到 <table>，流程中止。")
            return
        strip_checkbox_cells(new_table)
        new_header, new_rows = split_header_and_rows(new_table)
        print(f"本次新增英文（已翻译）条目：{len(new_rows)}")
    else:
        if not has_cn_files:
            show_error("既没有可用的英文/翻译文件，也没有中文新闻文件，流程中止。")
            return
        print("⚠️ 未检测到英文/翻译文件，进入纯中文合并模式。")

    # ---------- 确定目标文件 & 容器 ----------
    time_str = datetime.now().strftime("%y%m%d")
    base_filename = f"TodayCNH_{time_str}"
    target_path = os.path.join(NEWS_DIR, base_filename + ".html")

    container_soup = None
    container_table = None
    old_header = None
    old_rows = []

    if os.path.exists(target_path):
        print(f"找到已存在的文件：{target_path}，将进行合并（幂等重建）。")
        with open(target_path, 'r', encoding='utf-8') as f:
            container_soup = BeautifulSoup(f.read(), 'html.parser')
        remove_injected_assets(container_soup)
        container_table = container_soup.find('table')
        if container_table is not None:
            strip_checkbox_cells(container_table)      # ★ 关键：先把老的勾选框全部去掉
            old_header, old_rows = split_header_and_rows(container_table)
            print(f"已存在条目：{len(old_rows)}")
        else:
            container_soup = None

    if container_table is None:
        if new_soup is not None:
            container_soup = new_soup
            container_table = new_soup.find('table')
        else:
            container_soup = BeautifulSoup(MINIMAL_HTML, 'html.parser')
            container_table = container_soup.find('table')

    header_row = old_header if old_header is not None else new_header

    # ---------- 中文站点合并 ----------
    cn_rows = collect_chinese_rows()
    print(f"本次新增中文条目：{len(cn_rows)}")

    # 顺序：新中文 -> 旧内容 -> 新英文
    all_rows = cn_rows + old_rows + new_rows

    # ---------- 统一渲染 ----------
    render_document(container_soup, container_table, header_row, all_rows, target_path)

    # ---------- 清理临时文件 ----------
    for f in (TODAY_ALL_HTML, TODAY_CHN_TXT, PROCESS_ENG_TXT, PROCESS_JPN_TXT,
              RESULT_ENG_HTML, RESULT_JPN_HTML):
        safe_remove(f)
    delete_done_txt_files(TEMP_DIR)
    print("临时文件已清理。")

    # ---------- 打开 ----------
    if os.path.exists(target_path):
        open_in_browser(target_path)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        show_error(f"流程发生错误：{e}")