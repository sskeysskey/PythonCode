// 处理标题是否有效的函数
function isValidTitle_Bloomberg(titleText) {
    const invalidPhrases = [
        'Illustration:', '/Bloomberg', 'Getty Images', '/AP Photo', '/AP',
        'Photos:', 'Photo illustration', 'Source:', '/AFP', 'NurPhoto',
        'SOurce:', 'WireImage', 'Podcast:'
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
    const currentDatetime = `${now.getFullYear()}_${String(now.getMonth() + 1).padStart(2, '0')}_${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}`;
    const links = document.querySelectorAll("a[href*='/2025']");
    const newRows = [];

    links.forEach(link => {
        const href = link.href;
        let titleText = link.textContent.trim();

        if (titleText.startsWith("Newsletter: ")) {
            titleText = titleText.substring(11);
        }

        if (href.includes('/videos/2025') || href.includes('/podcast')) {
            return;
        }

        if (isValidTitle_Bloomberg(titleText) && href) {
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

// reuters 抓取函数
function scrapeReuters() {
    const now = new Date();
    const currentDatetime = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, '0'),
        String(now.getDate()).padStart(2, '0'),
        String(now.getHours()).padStart(2, '0'),
    ].join('_');

    // 先把所有 href*='-2025-' 的 a 拿出来
    const allLinks = Array.from(
        document.querySelectorAll("a[href*='-2025-']")
    );

    // 要排除的路径片段
    const excludePaths = ['/podcasts/', '/sports/', '/africa/'];

    const seen = new Set();
    const newRows = [];

    allLinks.forEach(link => {
        const href = link.href;

        // 1) 排除“媒体图片”链接
        if (link.dataset.testid === 'MediaImageLink') return;

        // 2) 排除带 <img> 的链接
        if (link.querySelector('img')) return;

        // 3) 排除特定板块的链接
        if (excludePaths.some(p => href.includes(p))) return;

        // 4) 去重
        if (seen.has(href)) return;
        seen.add(href);

        // 5) 提取标题
        let titleText = '';
        // 优先 span[data-testid="TitleHeading"]
        const heading = link.querySelector("[data-testid='TitleHeading']");
        if (heading) {
            titleText = heading.textContent.trim();
        }
        // 万一有 <a data-testid="Title">…</a>
        else if (link.dataset.testid === 'Title') {
            titleText = link.textContent.trim();
        }
        // 兜底：任何文本
        else {
            titleText = link.textContent.trim();
        }

        if (titleText) {
            newRows.push([currentDatetime, titleText, href]);
        }
    });

    if (newRows.length === 0) return;

    // --------- 和你现有的 downloadHTML 部分一模一样 ---------
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

// FT 抓取函数 (新增)
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


// 根据网站使用不同的事件监听方式
const hostname = window.location.hostname;

if (hostname.includes('bloomberg.com')) {
    // Bloomberg 使用原来的 load 事件
    window.addEventListener('load', () => {
        console.log('Bloomberg Scraper loaded');
        scrapeBloomberg();
    });
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
    window.addEventListener('load', () => {
        console.log('Reuters Scraper loaded');
        scrapeReuters();
    });
} else if (hostname.includes('ft.com')) { // 新增 FT 的处理逻辑
    window.addEventListener('load', () => {
        console.log('FT Scraper loaded');
        scrapeFT();
    });
}