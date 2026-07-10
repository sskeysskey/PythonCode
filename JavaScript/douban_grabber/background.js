// ================== 豆瓣页面抓取 ==================
function scrapeDoubanPage() {
  const info = document.querySelector('#info');

  // 1. 日期
  function extractDate() {
    const spans = document.querySelectorAll('span[property="v:initialReleaseDate"]');
    if (spans.length > 0) {
      const content = spans[0].getAttribute('content') || spans[0].textContent || '';
      const m = content.match(/(\d{4}-\d{2}-\d{2})/);
      if (m) return m[1];
    }
    // 兜底：直接在 #info 区域里找第一个日期
    const info = document.querySelector('#info');
    const txt = info ? (info.innerText || '') : '';
    const m2 = txt.match(/(\d{4}-\d{2}-\d{2})/);
    return m2 ? m2[1] : '';
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

  // 4. 外文标题（= alias）：豆瓣格式为「中文标题 + 空格 + 原文/外文标题」
  //    中文标题可能自带空格（如「第二季」「第一部」），因此不能简单取第一个空格之后。
  //    优先策略：外文标题一般从第一个含拉丁字母的 token 开始。
  //    兜底策略：纯日文/韩文等无拉丁字母的原名，回退到「第一个空格之后」。
  function extractForeignTitle() {
    const el = document.querySelector('span[property="v:itemreviewed"]');
    let full = el ? (el.textContent || '').trim() : '';
    if (!full) return '';

    // 规范空白：全角/多空格 => 单个半角空格
    full = full.replace(/\s+/g, ' ').trim();

    const tokens = full.split(' ');
    if (tokens.length <= 1) return '';        // 只有一段 => 纯中文标题，无外文标题

    // 从第 2 个 token 起（第 1 个必是中文标题），找第一个含拉丁字母的词
    const hasLatin = /[A-Za-z]/;
    for (let i = 1; i < tokens.length; i++) {
      if (hasLatin.test(tokens[i])) {
        return tokens.slice(i).join(' ');     // 从该词到结尾即为外文标题
      }
    }

    // 没有任何拉丁字母（如纯日文原名「ハイウェイの堕天使」）=> 回退到第一个空格之后
    const idx = full.indexOf(' ');
    return full.slice(idx + 1).trim();
  }

  // 5. 导演：rel="v:directedBy"，多个用 " / " 连接（返回单个字符串）
  function extractDirector() {
    if (!info) return '';
    const links = info.querySelectorAll('a[rel="v:directedBy"]');
    const arr = Array.from(links)
      .map(a => (a.textContent || '').trim())
      .filter(Boolean);
    return arr.join(' / ');
  }

  // 6. 主演：rel="v:starring"（返回数组）
  function extractStarring() {
    if (!info) return [];
    const links = info.querySelectorAll('a[rel="v:starring"]');
    return Array.from(links)
      .map(a => (a.textContent || '').trim())
      .filter(Boolean);
  }

  // 7. 按 .pl 标签名提取其 .attrs 下所有链接文本（用于「编剧」，因为它没有 rel 属性）
  function extractByLabel(label) {
    if (!info) return [];
    const pls = info.querySelectorAll('span.pl');
    for (const pl of pls) {
      const t = (pl.textContent || '').replace(/[:：]/g, '').trim();
      if (t === label) {
        const wrap = pl.parentElement;
        const attrs = wrap ? wrap.querySelector('span.attrs') : null;
        if (attrs) {
          const links = attrs.querySelectorAll('a');
          return Array.from(links)
            .map(a => (a.textContent || '').trim())
            .filter(Boolean);
        }
      }
    }
    return [];
  }

  // 8. 类型：property="v:genre"（返回数组）
  function extractGenres() {
    if (!info) return [];
    const nodes = info.querySelectorAll('span[property="v:genre"]');
    return Array.from(nodes)
      .map(n => (n.textContent || '').trim())
      .filter(Boolean);
  }

  // 9. 短评（保留）
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

  return {
    type: 'douban',
    name: extractName(),
    foreign_title: extractForeignTitle(),
    date: extractDate(),
    douban_rating: extractRating(),
    director: extractDirector(),
    screenwriters: extractByLabel('编剧'),
    starring: extractStarring(),
    genres: extractGenres(),
    reviews: extractReviews(),
    url: location.href,
    grabbed_at: new Date().toISOString()
  };
}

// ================== IMDb 页面抓取 ==================
function scrapeImdbPage() {
  function extractRating() {
    const el = document.querySelector('[data-testid="hero-rating-bar__aggregate-rating__score"] span')
      || document.querySelector('div[data-testid="hero-rating-bar__aggregate-rating__score"] span')
      || document.querySelector('span.sc-a30a09c4-1');
    return el ? el.textContent.trim() : '';
  }

  function extractTitle() {
    const el = document.querySelector('h1[data-testid="hero__pageTitle"] span')
      || document.querySelector('h1 span');
    return el ? el.textContent.trim() : (document.title || '').trim();
  }

  return {
    type: 'imdb',
    title: extractTitle(),
    imdb_rating: extractRating(),
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