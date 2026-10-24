#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
News_AutoScroll.py
------------------
对当前 Chrome 中所有"目标新闻域名"的 tab：
  1. 逐个激活并缓慢滚动到【正文底部】，触发懒加载图片；
  2. 统计正文字数（中文按字、英文按词），过短的写入 article_short.html 并关闭该 tab；
     · 图集页（如 reuters.com/pictures/...）不按字数判断，而是以"是否滚到最后一张图 [N/N]"为准，
       图集页永远不会被当作"过短"关闭；未能确认滚到最后一张时保留 tab 并在结束弹窗中列出；
  3. 每个 tab 开始前（以及滚动过程中）检查停止文件，存在则立即停止；
  4. 全部完成后弹窗提示。

依赖：仅 Python 标准库 + macOS osascript。
前置：Chrome 菜单「显示 → 开发者 → 允许 Apple 事件中的 JavaScript」须勾选。
"""

import fcntl
import html
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import shutil
import argparse
from datetime import datetime
from urllib.parse import urlparse

# ============================ 配置区 ============================

TARGET_DOMAINS = [
    "nytimes.com", "nikkei.com", "bloomberg.com", "technologyreview.com",
    "economist.com", "hbr.org", "ft.com", "wsj.com", "reuters.com",
    "washingtonpost.com", "asia.nikkei.com", "rfi.fr", "dw.com", "bbc.com",
]

STOP_FILE = "/Users/yanzhang/Desktop/stop_scpt.txt"
SHORT_HTML = "/Users/yanzhang/Coding/News/article_short.html"
LOG_FILE = "/Users/yanzhang/Coding/News/article_autoscroll.log"
LOCK_FILE = "/tmp/news_autoscroll.lock"

# 正文过短阈值（中文/日文按字符数；英文按单词数）
MIN_CJK_CHARS = 250
MIN_EN_WORDS = 150

CLOSE_SHORT_TABS = True        # 过短的 tab 是否关闭
BRING_CHROME_TO_FRONT = True   # 处理时把 Chrome 提到前台（保证懒加载正常触发）
MAX_ROUNDS = 5                 # 处理完一轮后再扫描新打开的目标 tab，最多几轮

# 滚动参数（传入页面 JS）
SCROLL_CFG = {
    "step": 260,          # 每步滚动像素
    "interval": 230,      # 每步间隔毫秒（≈1100px/s，不会太快）
    "settle": 1500,       # 到达正文底部后等待毫秒，用于确认没有新内容撑开
    "bottomMargin": 160,  # 让正文底部停在视口底边以上多少像素
    "maxMs": 120000,      # 单页滚动最长时间
    "imgWaitMs": 8000,    # 滚到底后等待图片加载的最长时间
}

# ---- 图集页（按"是否滚到最后一张图"判断，而非字数）----
# (域名, 路径前缀)：域名匹配规则与 TARGET_DOMAINS 相同；路径为该前缀本身或以 "前缀/" 开头
GALLERY_RULES = [
    ("reuters.com", "/pictures"),
]
GALLERY_MIN_IMAGES = 3         # 页面上找不到 [n/N] 计数器时的兜底：滚到底且已加载大图 ≥ 此数视为正常
GALLERY_CFG = {
    # 计数器元素（如 " [24/24]"）；不写死随机哈希后缀，找不到时 JS 会自动全页扫描 "n/m" 文本兜底
    "counterSel": '[class*="caption-module__number"], [class*="caption-module__counter"] span',
    # 单张图片的容器
    "itemSel": '[data-testid="EventGalleryImage"]',
    "visibleRatio": 0.5,  # 图片至少有多少比例（相对 min(视口高, 图高)）进入视口才算"看到"
    "lastSettle": 1200,   # 看到最后一张后再等一下，确认没有新内容追加
}

PAGE_LOAD_TIMEOUT = 30         # 等待 document.readyState=complete 的秒数
EXTRA_WAIT_AFTER_LOAD = 1.2    # 加载完成后额外等待（等前端框架渲染）
POLL_INTERVAL = 0.6            # 轮询页面状态间隔（秒）
OSA_TIMEOUT = 25               # 单次 osascript 调用超时（秒）

# 各站正文选择器（尽力而为；失效时 JS 会自动回退到"段落密度"启发式算法）
SITE_SELECTORS = {
    "nytimes.com": ['section[name="articleBody"]', ".article-body", ".article-paragraph"],
    "wsj.com": ["section[subscriptionsection]", '[data-type="article-body"]',
                ".article-content", '[class*="ArticleBody"]'],
    "bloomberg.com": ['[class*="body-content"]', ".body-copy-v2", '[class*="ArticleBody"]'],
    "technologyreview.com": ["#content--body", '[class*="contentBody"]', ".gutenbergContent"],
    "economist.com": ['[data-test-id="Article"] section', ".article__body",
                      "section[data-body-id]", '[class*="article-text"]'],
    "hbr.org": [".article-body", '[class*="ArticleBody"]', ".standard-content"],
    "ft.com": ["#article-body", ".article__content-body", ".n-content-body"],
    "reuters.com": ['[data-testid="ArticleBody"]', '[class*="article-body__content"]'],
    "washingtonpost.com": ['[data-qa="article-body"]', ".article-body", ".grid-body"],
    "nikkei.com": ['[class*="articleBody"]', '[class*="ArticleBody"]', ".article-body", "#CONTENTS_MAIN"],
    "rfi.fr": [".t-content__body", ".article__text", '[class*="content__body"]'],
    "dw.com": [".rich-text", '[class*="rich-text"]', ".longText"],
    "bbc.com": ['[data-component="text-block"]', 'main [class*="RichText"]'],
}

# ============================ 页面 JS ============================

START_JS_TEMPLATE = r"""
(function () {
  var CFG = __CFG__;
  var SITES = __SITES__;
  var GC = CFG.gallery || {};
  // 若页面里还有上一次（例如 Python 被强杀后）残留的实例在跑，令其让位，避免读到旧状态
  var prev = window.__nas;
  if (prev && prev.running) prev.abort = true;
  var S = window.__nas = {running: true, done: false, abort: false, phase: 'init', mode: CFG.mode,
                          progress: 0, result: null, error: null};
  function halt() { return S.abort || window.__nas !== S; }

  var CJK = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/g;
  var WORD = /[A-Za-z0-9\u00C0-\u024F]+(?:['\u2019\-][A-Za-z0-9\u00C0-\u024F]+)*/g;
  var EXCLUDE = 'script,style,noscript,template,svg,figure,figcaption,aside,nav,button,form,iframe,' +
                '[role="complementary"],[class*="related"],[class*="Related"],[class*="recommend"],' +
                '[class*="Recommend"],[class*="newsletter"],[class*="Newsletter"],[class*="advert"],[class*="Advert"]';
  var NOISE = 'nav,aside,footer,figure,figcaption,form,button,[role="navigation"],[role="complementary"],' +
              '[class*="related"],[class*="Related"],[class*="recommend"],[class*="Recommend"],' +
              '[class*="comment"],[class*="Comment"],[class*="newsletter"],[class*="Newsletter"]';

  function cnt(s) {
    s = s || '';
    var c = (s.match(CJK) || []).length;
    var w = (s.replace(CJK, ' ').match(WORD) || []).length;
    return {cjk: c, words: w};
  }
  function sc(c) { return c.cjk + c.words * 2; }
  function visible(el) {
    if (!el || !el.getClientRects || el.getClientRects().length === 0) return false;
    var st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none';
  }
  function cleanCount(el) {
    var c = cnt(el.innerText);
    var subs = el.querySelectorAll(EXCLUDE);
    for (var i = 0; i < subs.length; i++) {
      var x = subs[i];
      if (!visible(x)) continue;
      var p = x.parentElement, nested = false;
      while (p && p !== el) { if (p.matches(EXCLUDE)) { nested = true; break; } p = p.parentElement; }
      if (nested) continue;
      var d = cnt(x.innerText);
      c.cjk -= d.cjk; c.words -= d.words;
    }
    c.cjk = Math.max(0, c.cjk); c.words = Math.max(0, c.words);
    return c;
  }
  function siteSelectors() {
    var h = location.hostname, best = null;
    for (var d in SITES) {
      if ((h === d || h.slice(-(d.length + 1)) === '.' + d) && (!best || d.length > best.length)) best = d;
    }
    return best ? SITES[best] : [];
  }
  function bySelectors() {
    var sels = siteSelectors();
    for (var i = 0; i < sels.length; i++) {
      var els;
      try { els = Array.prototype.slice.call(document.querySelectorAll(sels[i])).filter(visible); }
      catch (e) { continue; }
      els = els.filter(function (e) { return !els.some(function (o) { return o !== e && o.contains(e); }); });
      if (!els.length) continue;
      var c = {cjk: 0, words: 0};
      els.forEach(function (e) { var k = cleanCount(e); c.cjk += k.cjk; c.words += k.words; });
      if (sc(c) > 0) return {els: els, count: c, method: 'selector: ' + sels[i]};
    }
    return null;
  }
  function heuristic() {
    var ps = document.querySelectorAll('p');
    var scores = new Map();
    for (var i = 0; i < ps.length; i++) {
      var p = ps[i];
      if (p.closest(NOISE) || !visible(p)) continue;
      var s = sc(cnt(p.innerText));
      if (s < 20) continue;
      var a = p.parentElement, b = a && a.parentElement;
      if (a) scores.set(a, (scores.get(a) || 0) + s);
      if (b) scores.set(b, (scores.get(b) || 0) + s * 0.5);
    }
    var best = null, bestS = 0;
    scores.forEach(function (v, k) { if (v > bestS) { bestS = v; best = k; } });
    if (!best) return null;
    var c = {cjk: 0, words: 0}, last = null;
    var inner = best.querySelectorAll('p');
    for (var j = 0; j < inner.length; j++) {
      var q = inner[j];
      if (q.closest(NOISE) || !visible(q)) continue;
      var k = cnt(q.innerText);
      if (!k.cjk && !k.words) continue;
      c.cjk += k.cjk; c.words += k.words; last = q;
    }
    return {els: [last || best], count: c, method: 'heuristic'};
  }
  function locate() {
    var a = bySelectors(), b = heuristic();
    if (a && (!b || sc(a.count) >= sc(b.count) * 0.5)) return a;
    return b || a;
  }
  function bottomAbs(loc) {
    var m = 0;
    loc.els.forEach(function (e) { var r = e.getBoundingClientRect(); m = Math.max(m, r.bottom + window.scrollY); });
    return m;
  }
  function alive(loc) { return loc && loc.els.every(function (e) { return e.isConnected; }); }
  function targetY(loc) {
    var se = document.scrollingElement || document.documentElement;
    var maxY = Math.max(0, se.scrollHeight - window.innerHeight);
    return loc ? Math.min(maxY, bottomAbs(loc) - window.innerHeight + CFG.bottomMargin) : maxY;
  }
  function countPending() {
    var limit = window.scrollY + window.innerHeight + 300, n = 0;
    Array.prototype.forEach.call(document.images, function (i) {
      if (i.complete) return;
      var r = i.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      if (r.top + window.scrollY > limit) return;
      n++;
    });
    return n;
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ======================= 普通文章模式 =======================
  async function articleMain(t0) {
    var loc = locate(), iter = 0, noMove = 0;
    S.phase = 'scroll';
    while (!halt() && Date.now() - t0 < CFG.maxMs) {
      iter++;
      if ((loc && !alive(loc)) || (!loc && iter % 8 === 0)) loc = locate();
      var target = targetY(loc);
      var y = window.scrollY;
      S.progress = target > 0 ? Math.min(1, y / target) : 1;
      if (target - y > CFG.step) {
        window.scrollBy(0, CFG.step);
        await sleep(CFG.interval);
        if (Math.abs(window.scrollY - y) < 2) { if (++noMove >= 8) break; } else { noMove = 0; }
        continue;
      }
      if (target > y) window.scrollTo(0, target);
      await sleep(CFG.settle);
      loc = locate();
      if (targetY(loc) - window.scrollY > 80) continue;   // 内容被撑长，继续滚
      break;
    }
    if (noMove >= 8 && loc) {   // 页面主滚动被锁（内层容器滚动），兜底
      try { loc.els[loc.els.length - 1].scrollIntoView({block: 'end'}); } catch (e) {}
      await sleep(CFG.settle);
    }
    S.phase = 'images';
    var t1 = Date.now(), pending = 0;
    while (!halt() && Date.now() - t1 < CFG.imgWaitMs) {
      pending = countPending();
      if (!pending) break;
      await sleep(400);
    }
    return pending;
  }

  // ======================= 图集模式 =======================
  var COUNTER_RE = /^\s*\[?\s*(\d{1,4})\s*\/\s*(\d{1,4})\s*\]?\s*$/;
  var seen = {};   // k -> 0 未见 / 1 几何上在视口内但可能被遮挡 / 2 命中测试确认在最上层可见

  function scanGallery() {
    var nodes = [];
    try { nodes = Array.prototype.slice.call(document.querySelectorAll(GC.counterSel)); } catch (e) {}
    var hasCounter = nodes.some(function (n) { return COUNTER_RE.test(n.textContent || ''); });
    if (!hasCounter) {   // 选择器失效兜底：扫描所有只含 "n/m" 的叶子元素
      nodes = Array.prototype.filter.call(document.querySelectorAll('span,div,p'), function (e) {
        return e.childElementCount === 0 && (e.textContent || '').length <= 16;
      });
    }
    var byKey = {}, freq = {};
    nodes.forEach(function (n) {
      var m = COUNTER_RE.exec(n.textContent || '');
      if (!m) return;
      var k = +m[1], tot = +m[2];
      if (!tot || k < 1 || k > tot) return;
      freq[tot] = (freq[tot] || 0) + 1;
      var key = tot + ':' + k;
      if (byKey[key]) return;
      var box = null;
      try { box = GC.itemSel ? n.closest(GC.itemSel) : null; } catch (e) {}
      box = box || n.closest('figure') || n.parentElement;
      byKey[key] = {k: k, tot: tot, box: box};
    });
    var total = 0, best = 0;
    for (var t in freq) {   // 取出现次数最多的总数（并列取较大者）
      if (freq[t] > best || (freq[t] === best && +t > total)) { best = freq[t]; total = +t; }
    }
    var items = [];
    for (var key in byKey) if (byKey[key].tot === total) items.push(byKey[key]);
    items.sort(function (a, b) { return a.k - b.k; });
    var lastIt = items.length && items[items.length - 1].k === total ? items[items.length - 1] : null;
    return {total: total, items: items, last: lastIt};
  }
  function mediaOf(box) {
    var im = box && box.querySelector('img');
    return (im && im.getClientRects().length) ? im : box;
  }
  function imgOK(el) {
    return !el || el.tagName !== 'IMG' || (el.complete && el.naturalWidth > 0);
  }
  function visLevel(box) {
    if (!box || !box.isConnected) return 0;
    var el = mediaOf(box), r = el.getBoundingClientRect();
    var vh = window.innerHeight, vw = window.innerWidth;
    var top = Math.max(0, r.top), bot = Math.min(vh, r.bottom), visH = bot - top;
    if (r.width < 2 || visH <= 0 || r.right <= 0 || r.left >= vw) return 0;
    if (visH < Math.min(vh, r.height) * (GC.visibleRatio || 0.5)) return 0;
    var cx = Math.min(vw - 2, Math.max(1, (Math.max(0, r.left) + Math.min(vw, r.right)) / 2));
    var ys = [top + visH * 0.25, top + visH * 0.5, top + visH * 0.75];
    for (var i = 0; i < ys.length; i++) {
      var hit = document.elementFromPoint(cx, ys[i]);
      // 命中自身内部（含浮动图注），或命中其祖先（说明上面没有其他图层遮挡）
      if (hit && (box.contains(hit) || hit.contains(el))) return 2;
    }
    return 1;
  }
  function markSeen(g) {
    g.items.forEach(function (it) {
      var v = visLevel(it.box);
      if (v > (seen[it.k] || 0)) seen[it.k] = v;
    });
    if (g.total) {
      var n = 0;
      for (var k = 1; k <= g.total; k++) if (seen[k]) n++;
      S.progress = n / g.total;
    }
  }
  function bigImages() {
    var total = 0, loaded = 0;
    Array.prototype.forEach.call(document.images, function (i) {
      var r = i.getBoundingClientRect();
      if (r.width < 300 || r.height < 200) return;
      total++;
      if (i.complete && i.naturalWidth > 0) loaded++;
    });
    return {total: total, loaded: loaded};
  }

  async function galleryMain(t0) {
    var se = document.scrollingElement || document.documentElement;
    var g = scanGallery(), iter = 0, noMove = 0, atBottom = false;
    function lastOK() { return !!(g.last && (seen[g.total] || 0) >= (atBottom ? 1 : 2)); }
    S.phase = 'scroll';
    while (!halt() && Date.now() - t0 < CFG.maxMs) {
      iter++;
      if (iter % 5 === 0) g = scanGallery();
      markSeen(g);
      if (lastOK()) {                       // 已看到最后一张 [N/N]
        await sleep(GC.lastSettle || 1200);
        g = scanGallery(); markSeen(g);     // 确认总数没有因懒渲染而变化
        if (lastOK()) break;
        continue;
      }
      var y = window.scrollY, maxY = Math.max(0, se.scrollHeight - window.innerHeight);
      if (maxY - y > 2 && noMove < 8) {
        window.scrollBy(0, Math.min(CFG.step, maxY - y));
        await sleep(CFG.interval);
        if (Math.abs(window.scrollY - y) < 2) noMove++; else noMove = 0;
        continue;
      }
      if (noMove >= 8 && g.items.length) {   // 主滚动被锁（内层容器滚动），逐张 scrollIntoView 兜底
        for (var i = 0; i < g.items.length && !halt(); i++) {
          try { g.items[i].box.scrollIntoView({block: 'center'}); } catch (e) {}
          await sleep(CFG.interval * 2);
          markSeen(g);
        }
        atBottom = true;
        break;
      }
      atBottom = true;                      // 已到页面底部
      await sleep(CFG.settle);
      g = scanGallery(); markSeen(g);
      if (noMove < 8 && se.scrollHeight - window.innerHeight - window.scrollY > 80) {
        atBottom = false; continue;         // 内容被撑长，继续滚
      }
      break;
    }

    S.phase = 'images';
    var lastMedia = g.last ? mediaOf(g.last.box) : null;
    var t1 = Date.now(), pending = 0;
    while (!halt() && Date.now() - t1 < CFG.imgWaitMs) {
      pending = countPending();
      if (!pending && imgOK(lastMedia)) break;
      await sleep(400);
    }
    markSeen(g);

    var imgs = 0, imgsLoaded = 0, seenCnt = 0;
    g.items.forEach(function (it) {
      var im = it.box && it.box.querySelector('img');
      if (!im) return;
      imgs++;
      if (im.complete && im.naturalWidth > 0) imgsLoaded++;
    });
    for (var k = 1; k <= g.total; k++) if (seen[k]) seenCnt++;
    var big = bigImages();
    return {
      total: g.total, found: g.items.length, seen: seenCnt,
      lastSeen: lastOK(), lastHit: !!(g.last && seen[g.total] === 2),
      lastLoaded: !!(g.last && imgOK(lastMedia)),
      imgs: imgs, imgsLoaded: imgsLoaded,
      bigImgs: big.total, bigLoaded: big.loaded,
      atBottom: atBottom, pending: pending
    };
  }

  // ======================= 入口 =======================
  async function main() {
    var t0 = Date.now();
    try { document.querySelectorAll('img[loading="lazy"]').forEach(function (i) { i.loading = 'eager'; }); } catch (e) {}
    var gallery = null, pending = 0;
    if (CFG.mode === 'gallery') { gallery = await galleryMain(t0); pending = gallery.pending; }
    else { pending = await articleMain(t0); }
    S.phase = 'count';
    var loc = locate();
    var meta = document.querySelector('meta[property="og:title"]');
    var h1 = document.querySelector('h1');
    S.result = {
      mode: CFG.mode,
      count: loc ? loc.count : {cjk: 0, words: 0},
      method: loc ? loc.method : 'none',
      title: (meta && meta.content) || (h1 && h1.innerText.trim()) || document.title || '',
      href: location.href,
      pendingImages: pending,
      gallery: gallery,
      aborted: halt(),
      elapsedMs: Date.now() - t0
    };
  }
  main().catch(function (e) { S.error = String((e && e.stack) || e); })
        .then(function () { S.done = true; S.running = false; S.phase = 'done'; });
  return JSON.stringify({started: true, mode: CFG.mode});
})();
"""

POLL_JS = r"""
(function () {
  var S = window.__nas;
  if (!S) return 'null';
  return JSON.stringify({done: S.done, phase: S.phase, progress: S.progress, result: S.result, error: S.error});
})();
"""

ABORT_JS = "(function(){ if (window.__nas) window.__nas.abort = true; return 'ok'; })();"

# ============================ AppleScript ============================

NO_TAB = "__NAS_NO_TAB__"

AS_IS_RUNNING = 'return application "Google Chrome" is running'

AS_LIST_TABS = r'''
set sep to character id 9
set nl to character id 10
set out to ""
tell application "Google Chrome"
	set wins to every window
	repeat with w in wins
		set wid to id of w
		set tids to id of every tab of w
		set urls to URL of every tab of w
		repeat with i from 1 to count of tids
			set out to out & (wid as text) & sep & ((item i of tids) as text) & sep & (item i of urls) & nl
		end repeat
	end repeat
end tell
return out
'''

# 一次性批量取 tab id 列表，避免逐个 tab 发 Apple 事件（tab 多时明显更快）
AS_ACTIVATE = r'''
on run argv
	set tidText to (item 1 of argv) as text
	set bringFront to ((item 2 of argv) is "1")
	tell application "Google Chrome"
		repeat with w in windows
			set tids to id of every tab of w
			repeat with i from 1 to count of tids
				if ((item i of tids) as text) is tidText then
					try
						set minimized of w to false
					end try
					set active tab index of w to i
					set index of w to 1
					if bringFront then activate
					return "ok"
				end if
			end repeat
		end repeat
	end tell
	return "__NAS_NO_TAB__"
end run
'''

AS_EXEC_JS = r'''
on run argv
	set wid to (item 1 of argv) as integer
	set tid to (item 2 of argv) as integer
	set js to item 3 of argv
	tell application "Google Chrome"
		set found to false
		try
			set theTab to tab id tid of window id wid
			get id of theTab
			set found to true
		end try
		if not found then
			repeat with w in windows
				try
					set theTab to tab id tid of w
					get id of theTab
					set found to true
					exit repeat
				end try
			end repeat
		end if
		if not found then return "__NAS_NO_TAB__"
		set r to execute theTab javascript js
	end tell
	if r is missing value then return ""
	return r as text
end run
'''

AS_CLOSE = r'''
on run argv
	set tid to (item 1 of argv) as integer
	tell application "Google Chrome"
		repeat with w in windows
			try
				close (tab id tid of w)
				return "ok"
			end try
		end repeat
	end tell
	return "__NAS_NO_TAB__"
end run
'''

AS_DIALOG_CHROME = r'''
on run argv
	tell application "Google Chrome"
		activate
		with timeout of 86400 seconds
			display dialog (item 1 of argv) with title (item 2 of argv) buttons {"好"} default button 1 with icon note giving up after 3600
		end timeout
	end tell
end run
'''

AS_DIALOG_PLAIN = r'''
on run argv
	activate
	display dialog (item 1 of argv) with title (item 2 of argv) buttons {"好"} default button 1 with icon note giving up after 3600
end run
'''

# ============================ 基础工具 ============================

log = logging.getLogger("nas")


class OSAError(Exception):
    pass


class JSDisabled(Exception):
    pass


class NotAuthorized(Exception):
    pass


class TabGone(Exception):
    pass


class StopRequested(Exception):
    pass


def setup_logging():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


def osa(script, *args, timeout=OSA_TIMEOUT):
    p = subprocess.run(["osascript", "-e", script, *[str(a) for a in args]],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        if "JavaScript" in err and ("AppleScript" in err or "Apple" in err) and \
                ("turned off" in err or "关闭" in err or "Apple Events" in err or "Apple 事件" in err):
            raise JSDisabled(err)
        if "-1743" in err:
            raise NotAuthorized(err)
        raise OSAError(err)
    return p.stdout.rstrip("\n")


def dialog(msg, via_chrome=True):
    try:
        subprocess.run(["osascript", "-e", AS_DIALOG_CHROME if via_chrome else AS_DIALOG_PLAIN,
                        msg, "News AutoScroll"], capture_output=True, text=True)
    except Exception as e:  # noqa
        log.error("弹窗失败: %s", e)


def stop_requested():
    return os.path.exists(STOP_FILE)

CAFFEINATE = shutil.which("caffeinate") or "/usr/bin/caffeinate"

def start_keep_awake():
    """启动 caffeinate，阻止显示器和系统休眠；随本进程退出自动结束。"""
    try:
        # -d 防止显示器休眠  -i 防止空闲休眠  -m 防止磁盘休眠
        # -s 接电源时防止系统休眠  -u 声明用户活动
        # -w PID：本进程结束时 caffeinate 自动退出
        return subprocess.Popen(
            [CAFFEINATE, "-dimsu", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.warning("无法启动 caffeinate，运行期间可能休眠: %s", e)
        return None

def stop_keep_awake(p):
    if p and p.poll() is None:
        p.terminate()

def _host_match(host, domain):
    return host == domain or host.endswith("." + domain)


def is_target(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not url.lower().startswith(("http://", "https://")):
        return False
    return any(_host_match(host, d) for d in TARGET_DOMAINS)


def is_gallery(url):
    """是否为图集页（如 https://www.reuters.com/pictures/...）。"""
    try:
        u = urlparse(url)
        host, path = (u.hostname or "").lower(), (u.path or "/").lower()
    except Exception:
        return False
    for domain, prefix in GALLERY_RULES:
        prefix = prefix.rstrip("/").lower()
        if _host_match(host, domain) and (path == prefix or path.startswith(prefix + "/")):
            return True
    return False


def list_tabs():
    out = osa(AS_LIST_TABS)
    tabs = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            tabs.append({"wid": int(parts[0]), "tid": int(parts[1]), "url": parts[2]})
    return tabs


def js(t, code, timeout=OSA_TIMEOUT):
    r = osa(AS_EXEC_JS, t["wid"], t["tid"], code, timeout=timeout)
    if r == NO_TAB:
        raise TabGone()
    return r


def activate_tab(t):
    r = osa(AS_ACTIVATE, t["tid"], "1" if BRING_CHROME_TO_FRONT else "0")
    if r == NO_TAB:
        raise TabGone()


def close_tab(t):
    try:
        osa(AS_CLOSE, t["tid"])
    except Exception as e:
        log.warning("关闭 tab 失败: %s", e)


def wait_ready(t):
    end = time.time() + PAGE_LOAD_TIMEOUT
    while time.time() < end:
        if stop_requested():
            raise StopRequested()
        try:
            state = js(t, "document.readyState")
        except (OSAError, subprocess.TimeoutExpired):
            state = ""
        if state == "complete":
            break
        time.sleep(0.5)
    else:
        log.warning("  页面 %ss 内未完全加载，继续处理", PAGE_LOAD_TIMEOUT)
    time.sleep(EXTRA_WAIT_AFTER_LOAD)


# ============================ 输出 HTML ============================

MARKER = "<!--NAS_ENTRIES_START-->"
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>正文过短的文章</title>
<style>
  body { font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif; max-width: 980px;
         margin: 32px auto; padding: 0 16px; color: #222; }
  h1 { font-size: 22px; }
  .tip { color: #888; font-size: 13px; }
  ul { list-style: none; padding: 0; }
  li { padding: 10px 12px; border-bottom: 1px solid #eee; }
  li:hover { background: #fafafa; }
  a { color: #0b57d0; text-decoration: none; font-size: 15px; word-break: break-all; }
  a:visited { color: #7b1fa2; }
  .meta { color: #888; font-size: 12px; margin-top: 4px; }
</style>
</head>
<body>
<h1>正文过短的文章（待人工检查）</h1>
<p class="tip">由 News_AutoScroll.py 自动生成，最新的在最上面；已访问过的链接显示为紫色。</p>
<ul>
""" + MARKER + """
</ul>
</body>
</html>
"""


def append_short(url, title, desc, method):
    os.makedirs(os.path.dirname(SHORT_HTML), exist_ok=True)
    content = None
    if os.path.exists(SHORT_HTML):
        with open(SHORT_HTML, "r", encoding="utf-8") as f:
            content = f.read()
        if MARKER not in content:
            bak = SHORT_HTML + datetime.now().strftime(".bak_%Y%m%d_%H%M%S")
            shutil.copy(SHORT_HTML, bak)
            log.warning("article_short.html 格式不符，已备份为 %s 并重建", bak)
            content = None
    if content is None:
        content = HTML_TEMPLATE

    esc_url = html.escape(url, quote=True)
    if f'href="{esc_url}"' in content:
        return False
    host = urlparse(url).hostname or ""
    li = (f'<li><a href="{esc_url}" target="_blank" rel="noopener">{html.escape(title or url)}</a>'
          f'<div class="meta">{datetime.now():%Y-%m-%d %H:%M} · {html.escape(host)} · '
          f'{html.escape(desc)} · {html.escape(method)}</div></li>')
    content = content.replace(MARKER, MARKER + "\n" + li, 1)
    tmp = SHORT_HTML + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, SHORT_HTML)
    return True


# ============================ 核心流程 ============================

_SITES_JSON = json.dumps(SITE_SELECTORS)
_START_JS_CACHE = {}


def build_start_js(mode):
    if mode not in _START_JS_CACHE:
        cfg = dict(SCROLL_CFG, mode=mode, gallery=GALLERY_CFG)
        _START_JS_CACHE[mode] = (START_JS_TEMPLATE
                                 .replace("__SITES__", _SITES_JSON)
                                 .replace("__CFG__", json.dumps(cfg)))
    return _START_JS_CACHE[mode]


def judge_article(res):
    c = res.get("count") or {}
    cjk, words = int(c.get("cjk", 0)), int(c.get("words", 0))
    if cjk >= words:
        n, th, desc = cjk, MIN_CJK_CHARS, f"中/日文 {cjk} 字（阈值 {MIN_CJK_CHARS}）"
    else:
        n, th, desc = words, MIN_EN_WORDS, f"英文 {words} 词（阈值 {MIN_EN_WORDS}）"
    return ("short" if n < th else "ok"), desc


def judge_gallery(res):
    g = res.get("gallery") or {}
    total = int(g.get("total") or 0)
    if total > 0:
        img = f"图片加载 {g.get('imgsLoaded', 0)}/{g.get('imgs', 0)}"
        if g.get("lastSeen"):
            desc = f"图集已滚到最后一张 [{total}/{total}]，浏览 {g.get('seen', 0)}/{total} 张，{img}"
            if not g.get("lastHit"):
                desc += "（末张可能被浮层遮挡，按已到底判定）"
            if not g.get("lastLoaded"):
                desc += "（末张图片未加载完）"
            return "gallery_ok", desc
        return "gallery_fail", (f"图集未滚到最后一张：已见 {g.get('seen', 0)}/{total} 张，"
                                f"DOM 中找到 {g.get('found', 0)} 个计数器，{img}")
    big = int(g.get("bigLoaded") or 0)
    if g.get("atBottom") and big >= GALLERY_MIN_IMAGES:
        return "gallery_ok", f"未识别到 [n/N] 计数器，已滚到页面底部，按大图判定：已加载 {big} 张"
    return "gallery_fail", (f"未识别到 [n/N] 计数器，已加载大图 {big} 张（阈值 {GALLERY_MIN_IMAGES}），"
                            f"无法确认图集完整")


def judge(res):
    """返回 (status, desc)；status ∈ ok / short / gallery_ok / gallery_fail"""
    if res.get("mode") == "gallery":
        return judge_gallery(res)
    return judge_article(res)


def process_tab(t, mode):
    start_js = build_start_js(mode)
    activate_tab(t)
    wait_ready(t)
    js(t, start_js)

    deadline = time.time() + SCROLL_CFG["maxMs"] / 1000 + SCROLL_CFG["imgWaitMs"] / 1000 + 30
    restarts = 0
    while True:
        time.sleep(POLL_INTERVAL)
        if stop_requested():
            try:
                js(t, ABORT_JS)
            except Exception:
                pass
            raise StopRequested()
        # 先检查超时：原实现在轮询持续失败时会 continue 跳过此检查，导致死循环
        if time.time() > deadline:
            try:
                js(t, ABORT_JS)
            except Exception:
                pass
            raise TimeoutError("单页处理超时")
        try:
            raw = js(t, POLL_JS)
        except (OSAError, subprocess.TimeoutExpired) as e:
            log.warning("  轮询失败（将重试）: %s", e)
            continue
        st = None
        if raw and raw != "null":
            try:
                st = json.loads(raw)
            except ValueError:
                st = None
        if st is None:  # 页面被刷新/跳转，状态丢失
            if restarts >= 2:
                raise RuntimeError("页面状态多次丢失（可能在不断刷新/跳转）")
            restarts += 1
            log.info("  页面状态丢失，重新开始（第 %d 次）", restarts)
            wait_ready(t)
            js(t, start_js)
            continue
        if st.get("done"):
            break

    if st.get("error"):
        raise RuntimeError("页面脚本出错: " + st["error"][:300])
    return st.get("result") or {}


def main(quiet=False):
    lock_fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("已有一个实例在运行，退出。")
        return 1                                   # ← 改

    setup_logging()
    log.info("=" * 60)
    log.info("News AutoScroll 启动%s", "（静默模式）" if quiet else "")

    if stop_requested():
        dialog(f"检测到停止文件，未执行任何操作：\n{STOP_FILE}\n\n删除该文件后再按快捷键即可运行。",
               via_chrome=False)
        return 2                                   # ← 改

    try:
        if osa(AS_IS_RUNNING).strip() != "true":
            dialog("Google Chrome 没有运行。", via_chrome=False)
            return 1                               # ← 改
        all_tabs = list_tabs()
    except NotAuthorized:
        dialog("没有控制 Chrome 的权限。\n请到「系统设置 → 隐私与安全性 → 自动化」里，"
               "允许「终端」控制「Google Chrome」，然后重试。", via_chrome=False)
        return 1                                   # ← 改

    skipped = sum(1 for t in all_tabs if not is_target(t["url"]))
    processed = set()
    stats = {"ok": 0, "short": 0, "gallery": 0, "gallery_fail": 0, "error": 0, "gone": 0}
    errors = []
    stopped = False
    gone_streak = 0
    t_start = time.time()

    try:
        for rnd in range(1, MAX_ROUNDS + 1):
            tabs = all_tabs if rnd == 1 else list_tabs()
            todo = [t for t in tabs if t["tid"] not in processed and is_target(t["url"])]
            if not todo:
                break
            log.info("第 %d 轮：目标 tab %d 个", rnd, len(todo))
            for idx, t in enumerate(todo, 1):
                if stop_requested():
                    stopped = True
                    break
                processed.add(t["tid"])
                mode = "gallery" if is_gallery(t["url"]) else "article"
                log.info("[%d/%d]%s %s", idx, len(todo), " [图集模式]" if mode == "gallery" else "", t["url"])
                try:
                    res = process_tab(t, mode)
                except StopRequested:
                    stopped = True
                    break
                except TabGone:
                    stats["gone"] += 1
                    gone_streak += 1
                    log.info("  tab 已不存在，跳过")
                    done_any = stats["ok"] + stats["short"] + stats["gallery"] + stats["gallery_fail"]
                    if gone_streak >= 3 and done_any == 0:
                        dialog("连续 3 个 tab 无法被 AppleScript 定位，已中止。\n"
                               "没有任何页面被处理，请查看终端日志。", via_chrome=False)
                        return 1 
                    continue
                except (JSDisabled, NotAuthorized):
                    raise
                except Exception as e:
                    stats["error"] += 1
                    errors.append(t["url"])
                    log.error("  处理失败: %s", e)
                    continue
                gone_streak = 0

                if res.get("aborted"):
                    stopped = True
                    break
                status, desc = judge(res)
                log.info("  %s | 方法: %s | 未完成图片: %s | 用时 %.1fs",
                         desc, "gallery" if mode == "gallery" else res.get("method"),
                         res.get("pendingImages"), (res.get("elapsedMs") or 0) / 1000)
                if status == "short":
                    stats["short"] += 1
                    added = append_short(t["url"], res.get("title", ""), desc, res.get("method", ""))
                    log.info("  -> 正文过短，%s", "已写入 article_short.html" if added else "链接已存在于列表中")
                    if CLOSE_SHORT_TABS:
                        close_tab(t)
                        log.info("  -> 已关闭该 tab")
                elif status == "gallery_ok":
                    stats["gallery"] += 1
                elif status == "gallery_fail":
                    stats["gallery_fail"] += 1
                    errors.append(t["url"])
                    log.warning("  -> 图集未确认完整，tab 保留")
                else:
                    stats["ok"] += 1
            if stopped:
                break
    except JSDisabled:
        dialog("Chrome 未允许 AppleScript 执行 JavaScript。\n\n请在 Chrome 菜单栏：\n"
               "显示(View) → 开发者(Developer) → 勾选「允许 Apple 事件中的 JavaScript」\n然后重新运行。")
        return 1                                   # ← 改
    except NotAuthorized:
        dialog("没有控制 Chrome 的权限。\n请到「系统设置 → 隐私与安全性 → 自动化」里，"
               "允许「终端」控制「Google Chrome」。", via_chrome=False)
        return 1                                   # ← 改

    mins, secs = divmod(int(time.time() - t_start), 60)
    head = "⏹ 检测到停止文件，已中止。" if stopped else "✅ 全部滚屏完成！"
    msg = (f"{head}\n\n"
           f"正常文章：{stats['ok']} 个\n"
           f"图集完成：{stats['gallery']} 个\n"
           f"正文过短：{stats['short']} 个"
           f"{'（已关闭）' if CLOSE_SHORT_TABS and stats['short'] else ''}\n")
    if stats["gallery_fail"]:
        msg += f"图集未确认：{stats['gallery_fail']} 个（tab 保留）\n"
    msg += (f"处理出错：{stats['error']} 个\n"
            f"非目标域名跳过：{skipped} 个\n"
            f"用时：{mins} 分 {secs} 秒")
    if stats["short"]:
        msg += f"\n\n过短列表：{SHORT_HTML}"
    if errors:
        msg += ("\n\n出错/未确认的页面（tab 保留未关）：\n" + "\n".join(errors[:5])
                + ("\n…" if len(errors) > 5 else ""))
    if stopped:
        msg += f"\n\n提示：删除 {STOP_FILE} 后才能再次运行。"
    log.info(msg.replace("\n", " | "))
    if stopped:                 # 被停止文件中止：始终弹窗，并返回非 0，阻止后续 Engine
        dialog(msg)
        return 2
    if not quiet:               # 原快捷键：照旧弹窗
        dialog(msg)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-dialog", action="store_true",
                        help="完成后不弹汇总窗口（供串联 News_Engine 使用）")
    args = parser.parse_args()

    keep = start_keep_awake()
    try:
        sys.exit(main(quiet=args.no_dialog))
    except KeyboardInterrupt:
        print("用户中断")
        sys.exit(130)
    finally:
        stop_keep_awake(keep)