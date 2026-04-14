// 处理标题是否有效的函数
function isValidTitle_Bloomberg(titleText) {
    const invalidPhrases = [
        'Illustration:', '/Bloomberg', 'Getty Images', '/AP Photo', '/AP',
        'Photos:', 'Photo illustration', 'Source:', '/AFP', 'NurPhoto',
        'SOurce:', 'WireImage', 'Podcast:', 'Tiananmen', 'Xi Jinping'
    ];

    // 过滤掉仅包含 "LIVE" 的标题
    if (titleText.trim() === "LIVE") {
        return false;
    }

    // 过滤掉以 "Listen" 开头的标题
    if (titleText.trim().startsWith("Listen")) {
        return false;
    }

    if (invalidPhrases.some(phrase => titleText.includes(phrase))) {
        return false;
    }

    return titleText && !isTimeFormat(titleText);
}

// 判断是否为时间格式
function isTimeFormat(text) {
    if ((text.length === 4 || text.length === 5) && text.includes(':')) {
        const parts = text.split(':');
        return parts.every(part => !isNaN(parseInt(part)));
    }
    return false;
}

// 生成HTML内容
function generateHTML(data, source) {
    let html = `
<html>
<body>
  <table border='1'>
    <tr><th>Date</th><th>Title</th></tr>
`;

    data.forEach(row => {
        const clickableTitle = `<a href='${row[2]}' target='_blank'>${row[1]}</a>`;
        html += `<tr><td>${row[0]}</td><td>${clickableTitle}</td></tr>\n`;
    });

    html += `</table></body></html>`;
    return html;
}

// Bloomberg 抓取函数
function scrapeBloomberg() {
    const now = new Date();
    // 动态获取当前年份 (例如 2026)
    const currentYear = now.getFullYear();
    const currentDatetime = `${now.getFullYear()}_${String(now.getMonth() + 1).padStart(2, '0')}_${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}`;

    // 使用 currentYear 变量替换写死的 /2026
    const links = document.querySelectorAll(`a[href*='/${currentYear}']`);

    const newRows = [];
    const seen = new Set(); // 新增：用于去重

    links.forEach(link => {
        const href = link.href;

        // 【新增修改】：如果 URL 中包含 "/audio/"，直接跳过
        if (href.includes('/audio/')) {
            return;
        }

        // 【修改点 1】：排除包含图片说明 (figcaption)、图片 (picture/img) 的链接
        if (link.querySelector('figcaption') || link.querySelector('picture') || link.querySelector('img')) {
            return;
        }

        // 过滤视频链接时也使用动态年份
        if (href.includes(`/videos/${currentYear}`) || href.includes('/podcast')) {
            return;
        }

        // 新增：去重逻辑
        if (seen.has(href)) return;

        // 【修改点 2】：优先尝试获取标准的标题元素
        const headlineEl = link.querySelector('[data-testid="headline"], [data-component="headline"]');
        let titleText = '';

        if (headlineEl) {
            titleText = headlineEl.textContent.trim();
        } else {
            // 兜底方案：只有当前面没有标点符号时，才添加句号
            titleText = link.innerText.replace(/([^\.\?\!])[\n\r]+/g, '$1. ').replace(/[\n\r]+/g, ' ').trim();
        }

        if (titleText.startsWith("Newsletter: ")) {
            titleText = titleText.substring(11);
        }

        if (isValidTitle_Bloomberg(titleText) && href) {
            seen.add(href); // 记录已抓取的链接
            newRows.push([currentDatetime, titleText, href]);
        }
    });

    if (newRows.length > 0) {
        const html = generateHTML(newRows, 'Bloomberg');
        const blob = new Blob([html], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const timestamp = now.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }).replace(/[/: ]/g, '_');

        chrome.runtime.sendMessage({
            action: "downloadHTML",
            url: url,
            filename: `bloomberg_${timestamp}.html`
        });
    }
}

// ================= 新增：进度条 UI 控制函数 =================
function createProgressUI(total) {
    if (document.getElementById('scraper-progress-container')) return;
    const container = document.createElement('div');
    container.id = 'scraper-progress-container';
    container.style.cssText = `
        position: fixed; bottom: 20px; right: 20px; width: 320px;
        background: #ffffff; border: 1px solid #e5e7eb;
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
        border-radius: 8px; padding: 16px; z-index: 999999;
        font-family: system-ui, -apple-system, sans-serif; color: #1f2937;
    `;
    container.innerHTML = `
        <div style="font-weight: 600; font-size: 14px; margin-bottom: 12px; display: flex; justify-content: space-between;">
            <span>🚀 路透社抓取中...</span>
            <span id="scraper-percent">0%</span>
        </div>
        <div style="width: 100%; background: #f3f4f6; border-radius: 999px; height: 8px; margin-bottom: 12px; overflow: hidden;">
            <div id="scraper-progress-bar" style="width: 0%; background: #3b82f6; height: 100%; transition: width 0.3s ease;"></div>
        </div>
        <div id="scraper-status" style="font-size: 12px; color: #4b5563; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">准备中...</div>
        <div id="scraper-eta" style="font-size: 12px; color: #6b7280;">预计剩余时间: 计算中...</div>
    `;
    document.body.appendChild(container);
}

function updateProgressUI(current, total, startTime, statusText) {
    const container = document.getElementById('scraper-progress-container');
    if (!container) return;

    const percent = total === 0 ? 100 : Math.round((current / total) * 100);
    document.getElementById('scraper-progress-bar').style.width = `${percent}%`;
    document.getElementById('scraper-percent').innerText = `${percent}%`;
    document.getElementById('scraper-status').innerText = `进度: ${current} / ${total} | ${statusText}`;

    if (current > 0 && current < total) {
        const elapsed = Date.now() - startTime;
        const timePerItem = elapsed / current;
        const remaining = (total - current) * timePerItem;
        const remainingSeconds = Math.round(remaining / 1000);
        document.getElementById('scraper-eta').innerText = `预计剩余时间: ${remainingSeconds} 秒`;
    } else if (current === total) {
        document.getElementById('scraper-eta').innerText = `处理完成！`;
    }
}

function removeProgressUI() {
    const container = document.getElementById('scraper-progress-container');
    if (container) {
        container.innerHTML = `<div style="font-weight: bold; color: #10b981; text-align: center;">✅ 抓取完成！即将下载...</div>`;
        setTimeout(() => container.remove(), 3000);
    }
}
// =========================================================

// Reuters 抓取函数
async function scrapeReuters() {
    const now = new Date();
    // 动态获取当前年份
    const currentYear = now.getFullYear();

    const currentDatetime = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, '0'),
        String(now.getDate()).padStart(2, '0'),
        String(now.getHours()).padStart(2, '0'),
    ].join('_');

    // 【修改点1】：放宽年份匹配规则，去掉前后的横杠，只要包含当前年份即可
    const allLinks = Array.from(
        document.querySelectorAll(`a[href*='${currentYear}']`)
    );

    // 要排除的路径片段
    const excludePaths = ['/podcasts/', '/sports/', '/africa/', '/audio/'];
    const seen = new Set();
    const newRows = [];

    // 预过滤出真正需要处理的链接，以便准确计算进度
    const validLinks = allLinks.filter(link => {
        const href = link.href;
        if (link.dataset.testid === 'MediaImageLink') return false;
        if (link.querySelector('img') && link.dataset.testid !== 'TitleLink' && link.dataset.testid !== 'Title') return false;
        if (excludePaths.some(p => href.includes(p))) return false;
        if (seen.has(href)) return false;
        seen.add(href);
        return true;
    });

    const totalLinks = validLinks.length;
    let processedCount = 0;
    const startTime = Date.now();

    // 启动进度条
    createProgressUI(totalLinks);

    // 重置 seen 以便在循环中复用去重逻辑（或者直接在下面去掉 seen 检查，因为已经过滤过了）
    seen.clear();

    for (const link of validLinks) {
        const href = link.href;
        seen.add(href);

        let titleText = '';
        let statusMsg = '解析标题中...';

        // 【核心修改】：针对 SubtopicLink 这种短标题，发起请求获取详情页的真实长标题
        if (link.dataset.testid === 'SubtopicLink') {
            statusMsg = '正在请求子页面获取长标题...';
            updateProgressUI(processedCount, totalLinks, startTime, statusMsg);

            try {
                const response = await fetch(href);
                const htmlText = await response.text();
                const parser = new DOMParser();
                const doc = parser.parseFromString(htmlText, 'text/html');

                // 尝试获取详情页的 h1 标签或 og:title
                const h1 = doc.querySelector('h1');
                const ogTitle = doc.querySelector('meta[property="og:title"]');

                if (h1 && h1.textContent.trim()) {
                    titleText = h1.textContent.trim();
                } else if (ogTitle && ogTitle.content.trim()) {
                    titleText = ogTitle.content.trim();
                } else {
                    titleText = link.textContent.trim(); // 兜底使用短标题
                }
            } catch (error) {
                console.error(`获取真实长标题失败: ${href}`, error);
                titleText = link.textContent.trim(); // 请求失败时兜底
            }
        } else {
            // 优先 span[data-testid="TitleHeading"]
            const heading = link.querySelector("[data-testid='TitleHeading']");
            if (heading) {
                titleText = heading.textContent.trim();
            }
            // 万一有 <a data-testid="Title">…</a> 或 <a data-testid="TitleLink">...</a>
            else if (link.dataset.testid === 'Title' || link.dataset.testid === 'TitleLink') {
                titleText = link.textContent.trim();
            }
            // 兜底：任何文本
            else {
                titleText = link.textContent.trim();
            }
        }

        processedCount++;
        updateProgressUI(processedCount, totalLinks, startTime, '处理完成');

        if (titleText.includes("Tiananmen")) {
            continue;
        }

        if (titleText) {
            newRows.push([currentDatetime, titleText, href]);
        }
    }

    if (newRows.length === 0) {
        removeProgressUI();
        return;
    }

    const html = generateHTML(newRows, 'Reuters');
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const timestamp = now
        .toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        })
        .replace(/[/: ]/g, '_');

    chrome.runtime.sendMessage({
        action: "downloadHTML",
        url,
        filename: `reuters_${timestamp}.html`
    });

    // 抓取并下载完成后移除进度条
    removeProgressUI();
}

// WSJ 抓取函数
function scrapeWSJ(shouldDownload = true) {
    const now = new Date();
    const currentDatetime = `${now.getFullYear()}_${String(now.getMonth() + 1).padStart(2, '0')}_${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}`;
    const newRows = [];
    const hostname = window.location.hostname;

    // 添加新的选择器 css-g4pnb7
    const titleElements = document.querySelectorAll('h3.css-fsvegl a, article h2 a, .WSJTheme--headline--7VCzo7Ay a, .css-g4pnb7, .css-2pp34t');

    titleElements.forEach(titleElement => {
        const href = titleElement.href;

        // 跳过包含 livecoverage 或 buyside 的链接
        if (!href || href.toLowerCase().includes('livecoverage') || href.toLowerCase().includes('wsj.com/buyside') || href.toLowerCase().includes('wsj.com/video') || href.toLowerCase().includes('wsj.com/sports')) {
            return;
        }

        // 检查链接域名，只保留 wsj.com 的链接
        try {
            const url = new URL(href);
            if (!url.hostname.includes('wsj.com')) {
                return;
            }
        } catch (e) {
            // 如果 URL 解析失败，跳过这个链接
            return;
        }

        let titleText = titleElement.innerText.trim();

        // 移除阅读时间标记
        titleText = titleText.replace(/\d+ min read/g, '').trim();

        if (titleText.includes("Tiananmen")) {
            return;
        }

        if (titleText && href) {
            newRows.push([currentDatetime, titleText, href]);
        }
    });

    // 只有当 shouldDownload 为 true 且有内容时才下载
    if (shouldDownload && newRows.length > 0) {
        const html = generateHTML(newRows, 'WSJ');
        const blob = new Blob([html], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const timestamp = now.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }).replace(/[/: ]/g, '_');

        // 根据域名决定文件名前缀
        const prefix = hostname.includes('cn.wsj.com') ? 'cnwsj_' : 'wsj_';

        chrome.runtime.sendMessage({
            action: "downloadHTML",
            url: url,
            filename: `${prefix}${timestamp}.html`
        });
    }

    return newRows.length;
}

// FT 抓取函数
function scrapeFT() {
    const now = new Date();
    const currentDatetime = `${now.getFullYear()}_${String(now.getMonth() + 1).padStart(2, '0')}_${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}`;

    const newRows = [];

    // 排除的标题文本，来自 selenium_FT.py 的逻辑
    const excludedTitles = [
        "opinion content.",
        "FT Series.",
        "Review.",
        "HTSI."
    ];

    // CSS 选择器，来自 selenium_FT.py
    const titleElements = document.querySelectorAll("a[href*='/content/']");

    titleElements.forEach(titleElement => {
        const href = titleElement.href;
        const titleText = titleElement.textContent.trim();

        // 检查 href 和 titleText 是否有效
        if (!href || !titleText) {
            return;
        }

        // 检查是否包含排除的关键词，来自 selenium_FT.py 的逻辑
        if (titleText.toLowerCase().includes('podcasts') ||
            titleText.toLowerCase().includes('film') ||
            titleText.includes('FT News Briefing.')) {
            return;
        }

        // 替代方案：使用正则匹配单词边界，不管是开头还是中间都能过滤
        if (/\bXi\b/.test(titleText)) {
            return;
        }

        // 检查是否是完全匹配的排除标题
        if (excludedTitles.includes(titleText)) {
            return;
        }

        newRows.push([currentDatetime, titleText, href]);
    });

    if (newRows.length > 0) {
        const html = generateHTML(newRows, 'FT');
        const blob = new Blob([html], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const timestamp = now.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }).replace(/[/: ]/g, '_');

        chrome.runtime.sendMessage({
            action: "downloadHTML",
            url: url,
            filename: `ft_${timestamp}.html`
        });
    }
}


// ========== 根据网站使用不同的事件监听方式 ==========
const hostname = window.location.hostname;

if (hostname.includes('bloomberg.com')) {
    console.log('Bloomberg Scraper 已注入，等待内容渲染...');

    let hasScraped = false;

    function tryBloombergScrape(source) {
        if (hasScraped) return;
        const currentYear = new Date().getFullYear();
        const links = document.querySelectorAll(`a[href*='/${currentYear}']`);
        console.log(`[Bloomberg] ${source}: 发现 ${links.length} 个候选链接`);

        if (links.length >= 5) {
            hasScraped = true;
            console.log(`[Bloomberg] 链接数量足够，开始抓取 (via ${source})`);
            bloombergObserver.disconnect();
            scrapeBloomberg();
        }
    }

    // 策略1：定时轮询（快速尝试 + 递增间隔）
    setTimeout(() => tryBloombergScrape('timeout-1.5s'), 1500);
    setTimeout(() => tryBloombergScrape('timeout-3s'), 3000);
    setTimeout(() => tryBloombergScrape('timeout-6s'), 6000);
    setTimeout(() => tryBloombergScrape('timeout-10s'), 10000);

    // 策略2：MutationObserver 监听 DOM 变化
    const bloombergObserver = new MutationObserver(() => {
        tryBloombergScrape('mutation');
    });

    function startBloombergObserver() {
        if (document.body) {
            bloombergObserver.observe(document.body, {
                childList: true,
                subtree: true
            });
        } else {
            setTimeout(startBloombergObserver, 200);
        }
    }
    startBloombergObserver();

    // 策略3：15秒兜底强制抓取
    setTimeout(() => {
        if (!hasScraped) {
            hasScraped = true;
            bloombergObserver.disconnect();
            console.log('[Bloomberg] 超时兜底，强制执行抓取');
            scrapeBloomberg();
        }
    }, 15000);

} else if (hostname.includes('wsj.com')) {
    // WSJ 使用 DOMContentLoaded 事件
    document.addEventListener('DOMContentLoaded', () => {
        console.log('WSJ Scraper loaded');

    });

    // 对于动态加载的内容，添加 MutationObserver 来监测DOM变化
    function throttle(func, limit) {
        let inThrottle;
        return function () {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        }
    }

    // 在观察到DOM变化后，仅执行第二次抓取并下载
    const throttledScrape = throttle(() => {
        console.log('检测到WSJ页面变化，执行额外抓取...');
        scrapeWSJ(true);
    }, 5000);  // 至少间隔5秒

    // 等待初始抓取完成后再设置观察器
    setTimeout(() => {
        const observer = new MutationObserver(throttledScrape);

        // 配置 observer
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        // 2分钟后断开观察器以避免长时间消耗资源
        setTimeout(() => {
            observer.disconnect();
        }, 2 * 60 * 1000);
    }, 3000);
} else if (hostname.includes('reuters.com')) {
    console.log('Reuters Scraper 已注入，等待内容渲染...');

    let hasScraped = false;

    function tryReutersScrape(source) {
        if (hasScraped) return;
        const currentYear = new Date().getFullYear();

        // 【修改点2】：这里的探测逻辑也要同步放宽年份限制
        const links = document.querySelectorAll(`a[href*='${currentYear}']`);
        console.log(`[Reuters] ${source}: 发现 ${links.length} 个候选链接`);

        if (links.length >= 5) {
            hasScraped = true;
            console.log(`[Reuters] 链接数量足够，开始抓取 (via ${source})`);
            observer.disconnect();
            scrapeReuters(); // 因为现在是 async，这里调用依然没问题，它会在后台执行
        }
    }

    // 策略1：定时轮询（覆盖 Python 端滚动完成后的时间窗口）
    setTimeout(() => tryReutersScrape('timeout-3s'), 3000);
    setTimeout(() => tryReutersScrape('timeout-6s'), 6000);
    setTimeout(() => tryReutersScrape('timeout-10s'), 10000);
    setTimeout(() => tryReutersScrape('timeout-15s'), 15000);

    // 策略2：MutationObserver 监听 DOM 变化（React 渲染完成时触发）
    const observer = new MutationObserver(() => {
        tryReutersScrape('mutation');
    });

    // 等 body 可用后再 observe
    function startObserver() {
        if (document.body) {
            observer.observe(document.body, {
                childList: true,
                subtree: true
            });
        } else {
            setTimeout(startObserver, 200);
        }
    }
    startObserver();

    // 策略3：20秒后无论如何强制抓取一次（兜底）
    setTimeout(() => {
        if (!hasScraped) {
            hasScraped = true;
            observer.disconnect();
            console.log('[Reuters] 超时兜底，强制执行抓取');
            scrapeReuters();
        }
    }, 20000);
} else if (hostname.includes('ft.com')) { // 新增 FT 的处理逻辑
    window.addEventListener('load', () => {
        console.log('FT Scraper loaded');
        scrapeFT();
    });
}