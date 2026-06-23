// 这个函数会被注入到豆瓣页面里执行，必须是“自包含”的（不能引用外部变量）
function scrapeDoubanPage() {
  // 1. 日期：上映日期 / 首播 都用同一个属性 v:initialReleaseDate
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

  // 4. 最多 5 条短评（暂存，后续再用）
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
    name: extractName(),
    date: extractDate(),
    douban_rating: extractRating(),
    reviews: extractReviews(),
    url: location.href,
    grabbed_at: new Date().toISOString()
  };
}

function downloadResult(data) {
  const jsonStr = JSON.stringify(data, null, 2);
  const dataUrl = 'data:application/json;charset=utf-8,' + encodeURIComponent(jsonStr);
  chrome.downloads.download({
    url: dataUrl,
    filename: 'douban_result.json',
    conflictAction: 'overwrite',   // 始终覆盖同名文件，文件名保持不变
    saveAs: false
  });
}

chrome.commands.onCommand.addListener((command) => {
  if (command !== 'scrape-douban') return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs.length) return;
    chrome.scripting.executeScript(
      { target: { tabId: tabs[0].id }, func: scrapeDoubanPage },
      (results) => {
        if (chrome.runtime.lastError) {
          console.error(chrome.runtime.lastError);
          return;
        }
        if (results && results[0] && results[0].result) {
          downloadResult(results[0].result);
        }
      }
    );
  });
});