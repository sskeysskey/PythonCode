// ================== 豆瓣页面抓取 ==================
function scrapeDoubanPage() {
  const info = document.querySelector('#info');

  // 通用：读取 #info 中某个 <span class="pl">标签</span> 后面直到 <br> 的纯文本
  function textAfterLabel(labels) {
    if (!info) return '';
    const wanted = labels.map(s => s.replace(/[:：\s]/g, ''));
    const pls = info.querySelectorAll('span.pl');
    for (const pl of pls) {
      const t = (pl.textContent || '').replace(/[:：\s]/g, '');
      if (wanted.includes(t)) {
        let node = pl.nextSibling;
        let text = '';
        while (node && node.nodeName !== 'BR') {
          if (node.nodeType === 3 || node.nodeType === 1) text += node.textContent || '';
          node = node.nextSibling;
        }
        return text.replace(/\s+/g, ' ').trim();
      }
    }
    return '';
  }

  // 1. 日期（完整保留页面展示，如：2026-09-09(西班牙网络)）
  function extractDate() {
    const spans = document.querySelectorAll('span[property="v:initialReleaseDate"]');
    for (const s of spans) {
      // 优先获取 visible textContent，而不是属性 content
      const text = (s.textContent || '').replace(/\s+/g, ' ').trim();
      if (/\d{4}-\d{2}-\d{2}/.test(text)) {
        return text;
      }
    }
    // 兜底：从「上映日期」或「首播」标签后抓取第一段
    const byLabel = textAfterLabel(['上映日期', '首播']);
    if (byLabel) {
      const parts = byLabel.split('/').map(p => p.trim()).filter(Boolean);
      for (const p of parts) {
        if (/\d{4}-\d{2}-\d{2}/.test(p)) return p;
      }
      return byLabel;
    }
    return '';
  }

  // 2. 豆瓣评分
  function extractRating() {
    const el = document.querySelector('strong.rating_num[property="v:average"]')
      || document.querySelector('strong.rating_num');
    return el ? el.textContent.trim() : '';
  }

  // 3. 页面上的影片名（用于回写时核对）
  function extractName() {
    const el = document.querySelector('span[property="v:itemreviewed"]')
      || document.querySelector('#content h1 span');
    if (el) return el.textContent.trim();
    return (document.title || '').replace(/\(豆瓣\)\s*$/, '').trim();
  }

  // 4. 年份
  function extractYear() {
    const el = document.querySelector('#content h1 span.year');
    if (!el) return '';
    const m = (el.textContent || '').match(/(\d{4})/);
    return m ? m[1] : '';
  }

  // 5. 主标题里的外文部分：「中文标题 + 空格 + 原文标题」
  //    中文标题可能自带空格（如「第二季」），所以从第 2 个 token 起找第一个含拉丁字母的词；
  //    纯日文/韩文原名（无拉丁字母）回退到第一个空格之后。
  function extractForeignTitle() {
    const el = document.querySelector('span[property="v:itemreviewed"]');
    let full = el ? (el.textContent || '').trim() : '';
    if (!full) return '';

    full = full.replace(/[\u3000\s]+/g, ' ').trim();
    const tokens = full.split(' ');
    if (tokens.length <= 1) return '';

    const hasLatin = /[A-Za-z\u00C0-\u024F]/;
    for (let i = 1; i < tokens.length; i++) {
      if (hasLatin.test(tokens[i])) return tokens.slice(i).join(' ');
    }
    const idx = full.indexOf(' ');
    return full.slice(idx + 1).trim();
  }

  // 6. 又名（整段 + 拆分数组）
  function extractAka() {
    return textAfterLabel(['又名']);
  }
  function splitAka(aka) {
    if (!aka) return [];
    return aka.split(/[\/／|｜]/)
      .map(s => s.replace(/\s+/g, ' ').trim())
      .filter(Boolean);
  }

  // 7. ★ IMDb ID：豆瓣 #info 里直接有 "IMDb: tt#######"
  function extractImdbId() {
    const byLabel = textAfterLabel(['IMDb', 'IMDB', 'IMDb链接', 'IMDb编号']);
    let m = byLabel.match(/tt\d{6,}/i);
    if (m) return m[0].toLowerCase();

    if (info) {
      m = (info.innerText || '').match(/tt\d{6,}/i);
      if (m) return m[0].toLowerCase();
    }
    const a = document.querySelector('a[href*="imdb.com/title/tt"]');
    if (a) {
      m = (a.getAttribute('href') || '').match(/tt\d{6,}/i);
      if (m) return m[0].toLowerCase();
    }
    return '';
  }

  // 8. 导演：rel="v:directedBy"，多个用 " / " 连接
  function extractDirector() {
    if (!info) return '';
    return Array.from(info.querySelectorAll('a[rel="v:directedBy"]'))
      .map(a => (a.textContent || '').trim())
      .filter(Boolean)
      .join(' / ');
  }

  // 9. 主演：rel="v:starring"
  function extractStarring() {
    if (!info) return [];
    return Array.from(info.querySelectorAll('a[rel="v:starring"]'))
      .map(a => (a.textContent || '').trim())
      .filter(Boolean);
  }

  // 10. 按 .pl 标签名提取其 .attrs 下所有链接文本（用于「编剧」）
  function extractByLabel(label) {
    if (!info) return [];
    const pls = info.querySelectorAll('span.pl');
    for (const pl of pls) {
      const t = (pl.textContent || '').replace(/[:：]/g, '').trim();
      if (t === label) {
        const wrap = pl.parentElement;
        const attrs = wrap ? wrap.querySelector('span.attrs') : null;
        if (attrs) {
          return Array.from(attrs.querySelectorAll('a'))
            .map(a => (a.textContent || '').trim())
            .filter(Boolean);
        }
      }
    }
    return [];
  }

  // 11. 类型：property="v:genre"
  function extractGenres() {
    if (!info) return [];
    return Array.from(info.querySelectorAll('span[property="v:genre"]'))
      .map(n => (n.textContent || '').trim())
      .filter(Boolean);
  }

  // 12. 短评
  function extractReviews() {
    const nodes = document.querySelectorAll('.short-content');
    const out = [];
    for (let i = 0; i < nodes.length && out.length < 5; i++) {
      let t = (nodes[i].innerText || nodes[i].textContent || '')
        .replace(/\u00a0/g, ' ')
        .replace(/\s+/g, ' ')
        .replace(/\(?\s*展开\s*\)?\s*$/, '')
        .trim();
      if (t) out.push(t);
    }
    return out;
  }

  // 13. 剧情简介
  function extractIntro() {
    const el = document.querySelector('span[property="v:summary"]');
    if (!el) return '';
    return (el.textContent || el.innerText || '').replace(/\s+/g, ' ').trim();
  }

  const aka = extractAka();

  return {
    type: 'douban',
    name: extractName(),
    year: extractYear(),
    aka: aka,
    aka_list: splitAka(aka),
    foreign_title: extractForeignTitle(),
    imdb_id: extractImdbId(),          // ★ 新增：直达 IMDb 的钥匙
    countries: textAfterLabel(['制片国家/地区']),
    languages: textAfterLabel(['语言']),
    episodes: textAfterLabel(['集数']),
    date: extractDate(),
    douban_rating: extractRating(),
    director: extractDirector(),
    screenwriters: extractByLabel('编剧'),
    starring: extractStarring(),
    genres: extractGenres(),
    reviews: extractReviews(),
    intro: extractIntro(),
    url: location.href,
    grabbed_at: new Date().toISOString()
  };
}

// ================== IMDb 页面抓取 ==================
function scrapeImdbPage() {
  // JSON-LD 兜底（IMDb 的 class 名是编译哈希，随时会变）
  function fromJsonLd() {
    const nodes = document.querySelectorAll('script[type="application/ld+json"]');
    for (const n of nodes) {
      try {
        const d = JSON.parse(n.textContent || '{}');
        if (d && (d.aggregateRating || d.name)) return d;
      } catch (e) { /* ignore */ }
    }
    return null;
  }
  const ld = fromJsonLd();

  function extractRating() {
    const el = document.querySelector('[data-testid="hero-rating-bar__aggregate-rating__score"] span')
      || document.querySelector('div[data-testid="hero-rating-bar__aggregate-rating__score"] span');
    if (el) {
      const m = (el.textContent || '').match(/(\d+(?:\.\d+)?)/);
      if (m) return m[1];
    }
    if (ld && ld.aggregateRating && ld.aggregateRating.ratingValue != null) {
      return String(ld.aggregateRating.ratingValue).trim();
    }
    // 最后兜底：页面上形如 8.4/10
    const m2 = (document.body.innerText || '').match(/\b(\d\.\d)\s*\/\s*10\b/);
    return m2 ? m2[1] : '';
  }

  function extractVotes() {
    if (ld && ld.aggregateRating && ld.aggregateRating.ratingCount != null) {
      return String(ld.aggregateRating.ratingCount);
    }
    return '';
  }

  function extractTitle() {
    const el = document.querySelector('h1[data-testid="hero__pageTitle"] span')
      || document.querySelector('h1 span')
      || document.querySelector('h1');
    if (el) return (el.textContent || '').trim();
    if (ld && ld.name) return String(ld.name).trim();
    return (document.title || '').replace(/\s*-\s*IMDb\s*$/i, '').trim();
  }

  function extractYear() {
    const m = (document.body.innerText || '').match(/\b(19|20)\d{2}\b/);
    return m ? m[0] : '';
  }

  function extractImdbId() {
    const m = location.pathname.match(/tt\d{6,}/i);
    return m ? m[0].toLowerCase() : '';
  }

  return {
    type: 'imdb',
    title: extractTitle(),
    year: extractYear(),
    imdb_id: extractImdbId(),
    imdb_rating: extractRating(),
    imdb_votes: extractVotes(),
    url: location.href,
    grabbed_at: new Date().toISOString()
  };
}

// ================== 下载 ==================
function downloadResult(data, filename) {
  const jsonStr = JSON.stringify(data, null, 2);
  const dataUrl = 'data:application/json;charset=utf-8,' + encodeURIComponent(jsonStr);
  chrome.downloads.download({
    url: dataUrl,
    filename: filename,
    conflictAction: 'overwrite',
    saveAs: false
  });
}

// ================== 命令入口：自动判断页面类型 ==================
chrome.commands.onCommand.addListener((command) => {
  if (command !== 'scrape-page') return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs.length) return;
    const tab = tabs[0];
    const url = tab.url || '';

    let func = null;
    let filename = '';
    if (url.includes('douban.com')) {
      func = scrapeDoubanPage;
      filename = 'douban_result.json';
    } else if (url.includes('imdb.com')) {
      func = scrapeImdbPage;
      filename = 'imdb_result.json';
    } else {
      console.warn('当前页面既不是豆瓣也不是IMDb，忽略。URL=', url);
      return;
    }

    chrome.scripting.executeScript(
      { target: { tabId: tab.id }, func: func },
      (results) => {
        if (chrome.runtime.lastError) {
          console.error(chrome.runtime.lastError);
          return;
        }
        if (results && results[0] && results[0].result) {
          downloadResult(results[0].result, filename);
        }
      }
    );
  });
});