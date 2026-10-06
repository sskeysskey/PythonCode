/*
 * pys_extract.js
 * 由 Downie_transfer.scpt 通过 Chrome「execute javascript」注入到 pys 播放页（顶层页面）。
 * 输出 4 行文本：
 *   第 1 行 状态：OK（播放器内真实地址） | FALLBACK（页面变量中的地址） | WAIT（尚未就绪） | ERR
 *   第 2 行 媒体地址（.m4u / .m3u8 / .mp4）
 *   第 3 行 顶层页面标题
 *   第 4 行 详情（来源 / 等待原因）
 * 可直接粘贴到 pys 播放页 DevTools Console 中测试。
 */
(function () {
  'use strict';

  var MEDIA_RE = /^https?:\/\/[^\s"'<>]+?\.(?:m3u8|m4u|mp4)(?:[?#][^\s"'<>]*)?$/i;
  var NET_MEDIA_RE = /\.(?:m3u8|m4u)(?:[?#]|$)/i;
  var INFO_MENU_RE = /video\s*info|视频统计|统计信息|视频信息/i;
  var MAX_DEPTH = 4;

  function clean(s) {
    return String(s == null ? '' : s).replace(/[\r\n\t]+/g, ' ').trim();
  }

  function media(u) {
    u = clean(u);
    return MEDIA_RE.test(u) ? u : '';
  }

  function out(status, url, title, detail) {
    return [status, clean(url), clean(title), clean(detail)].join('\n');
  }

  // 广度遍历所有同源 window（顶层 + 嵌套 iframe），跨域 iframe 自动跳过
  function listWindows(root) {
    var result = [];
    var queue = [{ w: root, d: 0, path: 'top' }];
    while (queue.length) {
      var cur = queue.shift();
      var doc = null;
      try { doc = cur.w.document; } catch (e) { doc = null; }
      if (!doc) continue;
      result.push(cur);
      if (cur.d >= MAX_DEPTH) continue;
      var frames = [];
      try { frames = doc.querySelectorAll('iframe, frame'); } catch (e) { frames = []; }
      for (var i = 0; i < frames.length; i++) {
        try {
          var cw = frames[i].contentWindow;
          if (cw) {
            queue.push({
              w: cw,
              d: cur.d + 1,
              path: cur.path + '>' + (frames[i].id || frames[i].name || ('iframe' + i))
            });
          }
        } catch (e) { /* ignore */ }
      }
    }
    return result;
  }

  // 1) DPlayer 信息面板（用户截图中的位置）
  function fromInfoPanel(doc) {
    try {
      var el = doc.querySelector('.dplayer-info-panel-item-url .dplayer-info-panel-item-data');
      return el ? media(el.textContent) : '';
    } catch (e) { return ''; }
  }

  function isPlayerLike(v) {
    try {
      return !!(v && typeof v === 'object' && v.options && v.options.video &&
        typeof v.options.video.url === 'string');
    } catch (e) { return false; }
  }

  // 2) DPlayer 实例 options.video.url
  function fromPlayerInstance(win) {
    var names = ['dp', 'player', 'dplayer', 'DP', 'videoPlayer'];
    for (var i = 0; i < names.length; i++) {
      try {
        var v = win[names[i]];
        if (isPlayerLike(v)) {
          var u = media(v.options.video.url);
          if (u) return u;
        }
      } catch (e) { /* ignore */ }
    }
    var keys = [];
    try { keys = Object.keys(win); } catch (e) { keys = []; }
    for (var j = 0; j < keys.length && j < 3000; j++) {
      try {
        var o = win[keys[j]];
        if (isPlayerLike(o)) {
          var u2 = media(o.options.video.url);
          if (u2) return u2;
        }
      } catch (e) { /* ignore */ }
    }
    return '';
  }

  // 3a) <video> / <source> 标签（跳过 blob:）
  function fromVideoTags(doc) {
    try {
      var nodes = doc.querySelectorAll('video, video source');
      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        var s = n.currentSrc || n.src || n.getAttribute('src') || '';
        if (/^blob:/i.test(s)) continue;
        var u = media(s);
        if (u) return u;
      }
    } catch (e) { /* ignore */ }
    return '';
  }

  // 3b) 网络资源记录（hls.js 拉取的播放列表）
  function fromPerformance(win) {
    try {
      var list = win.performance.getEntriesByType('resource');
      for (var i = list.length - 1; i >= 0; i--) {
        var name = list[i].name || '';
        if (NET_MEDIA_RE.test(name)) {
          var u = media(name);
          if (u) return u;
        }
      }
    } catch (e) { /* ignore */ }
    return '';
  }

  // 5) MacCMS 页面变量（兜底）
  function decodeMacUrl(url, enc) {
    url = String(url || '');
    enc = String(enc == null ? '0' : enc);
    try {
      if (enc === '1') return unescape(url);
      if (enc === '2') return unescape(atob(url));
    } catch (e) { /* ignore */ }
    return url;
  }

  function fromMacVars(win) {
    try {
      if (win.MacPlayer && win.MacPlayer.PlayUrl) {
        var u = media(decodeURIComponentSafe(win.MacPlayer.PlayUrl));
        if (u) return u;
      }
    } catch (e) { /* ignore */ }
    try {
      var p = win.player_aaaa;
      if (p && p.url) {
        var u2 = media(decodeMacUrl(p.url, p.encrypt));
        if (u2) return u2;
      }
    } catch (e) { /* ignore */ }
    return '';
  }

  function decodeURIComponentSafe(s) {
    s = String(s || '');
    if (/^https?%3A/i.test(s)) {
      try { return decodeURIComponent(s); } catch (e) { return s; }
    }
    return s;
  }

  // 4) 信息面板为空时，模拟点击右键菜单「视频统计信息」，触发 DPlayer 填充面板（每个 window 只尝试一次）
  function tryOpenInfoPanel(win, doc) {
    try {
      if (win.__pysInfoPanelTried) return;
      var panel = doc.querySelector('.dplayer-info-panel');
      if (!panel) return;
      var items = doc.querySelectorAll('.dplayer-menu-item');
      if (!items.length) return;
      win.__pysInfoPanelTried = true;
      if (!panel.classList.contains('dplayer-info-panel-hide')) return; // 已显示，无需再点
      for (var i = 0; i < items.length; i++) {
        if (INFO_MENU_RE.test(items[i].textContent || '')) {
          items[i].click();
          return;
        }
      }
    } catch (e) { /* ignore */ }
  }

  try {
    var wins = listWindows(window);
    var hasPlayer = false;
    var primary = '', pSrc = '';
    var fallback = '', fSrc = '';

    for (var i = 0; i < wins.length; i++) {
      var w = wins[i].w;
      var doc = w.document;
      var path = wins[i].path;
      var u = '';

      try {
        if (doc.querySelector('.dplayer, .MacPlayer, #playleft') || w.MacPlayer || w.player_aaaa) {
          hasPlayer = true;
        }
      } catch (e) { /* ignore */ }

      if (!primary) {
        u = fromInfoPanel(doc);
        if (u) { primary = u; pSrc = 'info-panel@' + path; }
      }
      if (!primary) {
        u = fromPlayerInstance(w);
        if (u) { primary = u; pSrc = 'dplayer-instance@' + path; }
      }
      if (!primary) {
        u = fromVideoTags(doc);
        if (u) { primary = u; pSrc = 'video-tag@' + path; }
      }
      if (!primary) {
        u = fromPerformance(w);
        if (u) { primary = u; pSrc = 'network@' + path; }
      }
      if (!fallback) {
        u = fromMacVars(w);
        if (u) { fallback = u; fSrc = 'maccms-var@' + path; }
      }
    }

    if (!primary) {
      for (var k = 0; k < wins.length; k++) {
        tryOpenInfoPanel(wins[k].w, wins[k].w.document);
      }
    }

    var title = '';
    try { title = document.title; } catch (e) { title = ''; }

    if (primary) return out('OK', primary, title, pSrc);
    if (fallback) return out('FALLBACK', fallback, title, fSrc);
    return out('WAIT', '', title,
      (hasPlayer ? 'player-loading' : 'no-player') +
      ';ready=' + document.readyState + ';frames=' + wins.length);
  } catch (e) {
    return out('ERR', '', '', String((e && e.message) || e));
  }
})();