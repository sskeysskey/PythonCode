// 保存 WSJ 页面待完成下载的图片下载ID，key 为 tabId
let DownloadsPending = {};

// 点击扩展图标时触发
chrome.action.onClicked.addListener(async (tab) => {
    if (
        tab.url.includes("ft.com") ||
        tab.url.includes("bloomberg.com") ||
        tab.url.includes("wsj.com") ||
        tab.url.includes("economist.com") ||
        tab.url.includes("technologyreview.com") ||
        tab.url.includes("reuters.com") ||
        tab.url.includes("nytimes.com") ||
        tab.url.includes("washingtonpost.com") ||
        tab.url.includes("asia.nikkei.com") ||
        tab.url.includes("dw.com") ||
        tab.url.includes("rfi.fr") ||
        tab.url.includes("bbc.com")
    ) {
        try {
            // 执行文本提取与复制操作
            const [result] = await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                function: extractAndCopy
            });

            if (result && result.result) { // 检查 result 是否存在
                // 显示文本复制成功通知
                await chrome.scripting.executeScript({
                    target: { tabId: tab.id },
                    function: showNotification,
                    args: ['已成功复制到剪贴板']
                });
            } else {
                // 显示复制失败通知
                await chrome.scripting.executeScript({
                    target: { tabId: tab.id },
                    function: showNotification,
                    args: ['复制失败，未找到内容或提取出错']
                });
            }
        } catch (err) {
            console.error('Script execution failed:', err);
            // 显示错误通知
            await chrome.scripting.executeScript({
                target: { tabId: tab.id },
                function: showNotification,
                args: ['发生错误，请重试']
            });
        }
    }
});

// 修改后的下载图片消息监听器，增加下载完成跟踪逻辑
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'downloadImage') {
        const tabId = sender.tab ? sender.tab.id : null;
        if (tabId !== null) {
            // 初始化该 tab 的数据结构
            if (!DownloadsPending[tabId]) {
                DownloadsPending[tabId] = {
                    downloads: [],
                    hasStartedImageProcess: true // 标记已开始处理图片下载
                };
            } else {
                // 如果 tabId 已存在，确保 hasStartedImageProcess 也被设置
                DownloadsPending[tabId].hasStartedImageProcess = true;
            }
        }
        chrome.downloads.download({
            url: request.url,
            filename: request.filename,
            saveAs: false // 直接下载，不显示保存对话框
        }, (downloadId) => {
            if (chrome.runtime.lastError) {
                console.error(`Download failed for ${request.url}: ${chrome.runtime.lastError.message}`);
                return;
            }
            if (downloadId && tabId !== null && DownloadsPending[tabId]) {
                // 将下载任务ID加入跟踪队列中
                DownloadsPending[tabId].downloads.push(downloadId);
            }
        });
    } else if (request.action === 'noImages') {
        // 处理无图片的情况
        const tabId = sender.tab ? sender.tab.id : null;
        if (tabId !== null) {
            if (DownloadsPending[tabId] && DownloadsPending[tabId].downloads && DownloadsPending[tabId].downloads.length === 0 && DownloadsPending[tabId].hasStartedImageProcess) {
                chrome.scripting.executeScript({
                    target: { tabId: tabId },
                    function: showNotification,
                    args: ['没有找到可下载的图片']
                });
                delete DownloadsPending[tabId]; // 清理
            } else if (!DownloadsPending[tabId] || !DownloadsPending[tabId].hasStartedImageProcess) {
                chrome.scripting.executeScript({
                    target: { tabId: tabId },
                    function: showNotification,
                    args: ['没有找到可下载的图片']
                });
                // 确保清理，以防万一
                if (DownloadsPending[tabId]) delete DownloadsPending[tabId];
            }
            // 如果有图片正在下载中，收到 noImages 消息（理论上不应发生），则不应显示“无图片”
        }
    }
});

// 监听下载完成后弹出通知
chrome.downloads.onChanged.addListener((delta) => {
    if (delta.state && delta.state.current === "complete") {
        chrome.downloads.search({ id: delta.id }, (results) => {
            if (results && results.length > 0) {
                const downloadItem = results[0];
                const downloadId = downloadItem.id;
                // 遍历所有页面的 tabId
                for (const tabIdStr in DownloadsPending) {
                    const tabId = parseInt(tabIdStr); // 确保 tabId 是数字
                    const tabData = DownloadsPending[tabIdStr];
                    if (tabData && tabData.downloads) { // 确保 tabData 和 downloads 存在
                        const index = tabData.downloads.indexOf(downloadId);
                        if (index !== -1) {
                            // 移除该下载任务ID
                            tabData.downloads.splice(index, 1);
                            // 如果该 tab 下所有图片都下载完成，并且我们确实为这个tab启动了图片处理流程
                            if (tabData.downloads.length === 0 && tabData.hasStartedImageProcess) {
                                chrome.tabs.get(tabId, (tab) => { // 检查tab是否存在
                                    if (chrome.runtime.lastError || !tab) {
                                        // Tab不存在或已关闭，清理并退出
                                        delete DownloadsPending[tabIdStr];
                                        return;
                                    }
                                    // Tab 存在，执行脚本
                                    chrome.scripting.executeScript({
                                        target: { tabId: tabId },
                                        function: showNotification,
                                        args: ['所有图片下载完成']
                                    }).catch(err => console.error(`Error showing notification on tab ${tabId}:`, err));
                                    // 清理该 tab 对应的数据
                                    delete DownloadsPending[tabIdStr];
                                });
                            }
                            break; // 已找到并处理该下载项，跳出循环
                        }
                    }
                }
            }
        });
    } else if (delta.state && delta.state.current === "interrupted") {
        // 处理下载中断的情况
        chrome.downloads.search({ id: delta.id }, (results) => {
            if (results && results.length > 0) {
                const downloadItem = results[0];
                const downloadId = downloadItem.id;
                for (const tabIdStr in DownloadsPending) {
                    const tabId = parseInt(tabIdStr);
                    const tabData = DownloadsPending[tabIdStr];
                    if (tabData && tabData.downloads) {
                        const index = tabData.downloads.indexOf(downloadId);
                        if (index !== -1) {
                            tabData.downloads.splice(index, 1); // 从队列中移除
                            console.warn(`Download ${downloadId} for tab ${tabId} was interrupted.`);
                            // 检查是否所有剩余（或全部）下载都已处理完毕
                            if (tabData.downloads.length === 0 && tabData.hasStartedImageProcess) {
                                chrome.tabs.get(tabId, (tab) => {
                                    if (chrome.runtime.lastError || !tab) {
                                        delete DownloadsPending[tabIdStr];
                                        return;
                                    }
                                    chrome.scripting.executeScript({
                                        target: { tabId: tabId },
                                        function: showNotification,
                                        args: ['部分图片下载中断，其余已完成'] // 或者更通用的消息
                                    }).catch(err => console.error(`Error showing notification on tab ${tabId}:`, err));
                                    delete DownloadsPending[tabIdStr];
                                });
                            }
                            break;
                        }
                    }
                }
            }
        });
    }
});

function showNotification(message) {
    // 如果未添加通知相关的样式，则创建一次
    if (!document.getElementById('notification-style')) {
        const style = document.createElement('style');
        style.id = 'notification-style';
        style.textContent = `
      #notification-container {
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 2147483647;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
      }
      .copy-notification {
        background-color: #4CAF50;
        color: white;
        padding: 12px 24px;
        border-radius: 4px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        font-size: 14px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        opacity: 0;
        transform: translateY(-20px);
        transition: opacity 0.3s ease, transform 0.3s ease;
      }
      .copy-notification.show {
        opacity: 1;
        transform: translateY(0);
      }
    `;
        document.head.appendChild(style);
    }

    // 创建通知容器（如果尚未创建）
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        document.body.appendChild(container);
    }

    // 创建新的通知元素
    const notification = document.createElement('div');
    notification.className = 'copy-notification';
    notification.textContent = message;
    container.appendChild(notification);

    // Trigger animation
    requestAnimationFrame(() => {
        notification.classList.add('show');
    });

    // 持续显示7秒后移除通知
    setTimeout(() => {
        notification.classList.remove('show');
        // Wait for fade out animation to complete before removing
        notification.addEventListener('transitionend', () => {
            notification.remove();
            // 如果容器内没有其他通知则移除容器
            if (container.children.length === 0) {
                container.remove();
            }
        });
    }, 7000);
}

function extractAndCopy() {
    let textContent = '';
    let imagesFoundForDownload = false; // 用于跟踪是否至少尝试下载了一张图片

    if (window.location.hostname.includes("ft.com")) {
        const siteContent = document.getElementById('site-content');
        // 先尝试最常见的新版结构，再 fallback 到旧版
        const articleBody =
            document.getElementById('article-body') ||
            siteContent?.querySelector('#article-body');

        if (articleBody) {
            // 1. 文本提取：兼容 <p> 和最外层 <div> 两种容器
            let paras = Array.from(articleBody.querySelectorAll('p'));
            // 加回新版里文字被 <div> 包裹的情况
            const divParas = Array.from(articleBody.children)
                .filter(el => el.tagName === 'DIV');
            paras = [...new Set([...paras, ...divParas])];

            // 原有的 FT.com 段落过滤逻辑
            const kept = paras.filter(p => {
                const text = p.textContent.trim();
                if (!text || text.length <= 1) return false;
                if (text === '@' || text === '•' || text === '».') return false;
                if (text.includes('is the author of') ||
                    text.toLowerCase().includes('follow ft weekend')) return false;
                if (text.toLowerCase().includes('change has been made') ||
                    text.toLowerCase().includes('story was originally published'))
                    return false;
                if (text.toLowerCase().includes('subscribe') ||
                    text.toLowerCase().includes('newsletter'))
                    return false;
                if (text.toLowerCase().includes('follow') &&
                    (text.includes('instagram') || text.includes('twitter')))
                    return false;
                // 排除主要由 <em> 组成的段落
                const emTags = p.getElementsByTagName('em');
                if (emTags.length > 0 && emTags[0].textContent.length > text.length / 2)
                    return false;
                // 排除大量链接
                const links = p.getElementsByTagName('a');
                if (links.length > 2) return false;
                return true;
            });
            const textContent = kept
                .map(p => p.textContent.trim())
                .join('\n\n');

            // 2. 图片下载：先按老逻辑抓特定类名的 <figure>，再 fallback 到 siteContent 下所有 <figure>
            let imageFigures = Array.from(
                document.querySelectorAll(
                    'figure.n-content-image, figure.n-content-picture, ' +
                    'figure.o-topper_visual, .main-image'
                )
            );
            if (imageFigures.length === 0 && siteContent) {
                imageFigures = Array.from(siteContent.querySelectorAll('figure'));
            }
            // 同一元素去重
            imageFigures = [...new Set(imageFigures)];

            if (imageFigures.length === 0) {
                chrome.runtime.sendMessage({ action: 'noImages' });
            } else {
                let seenUrls = new Set();
                let seenNames = new Set();
                imageFigures.forEach((fig, idx) => {
                    // 取 <picture><img> 或 fig.querySelector('img')
                    const pic = fig.querySelector('picture');
                    const img = pic ? pic.querySelector('img') : fig.querySelector('img');
                    if (!img) return;

                    // 最高分辨率
                    let url = img.src;
                    if (img.srcset) {
                        const candidates = img.srcset
                            .split(',')
                            .map(entry => {
                                const [u, w] = entry.trim().split(/\s+/);
                                return { url: u, width: parseInt(w) || 0 };
                            })
                            .filter(c => c.width > 0)
                            .sort((a, b) => b.width - a.width);
                        if (candidates[0]) url = candidates[0].url;
                    }
                    url = url.trim();
                    if (!/^https?:\/\//.test(url) || seenUrls.has(url)) return;
                    seenUrls.add(url);

                    // 描述：合并所有 span 并去掉版权 ©…
                    let caption = '';
                    const fc = fig.querySelector('figcaption');
                    if (fc) {
                        caption = Array.from(fc.querySelectorAll('span'))
                            .map(sp => sp.textContent.trim())
                            .join(' ')
                            .replace(/©.*$/g, '')
                            .trim();
                    }
                    if (!caption) caption = img.alt.trim();
                    if (!caption) caption = `ft-image-${Date.now()}-${idx}`;

                    // ★★★ 修改点 ★★★
                    // 2. 修改正则表达式，增加对'+'的过滤
                    // 清洗成合法文件名，防重名
                    let base = caption
                        .replace(/[/\\?%*:|"<>+]/g, '') // 过滤掉非法字符以及+和-号
                        .replace(/\s+/g, ' ')
                        .substring(0, 200)
                        .trim();
                    let filename = `${base}.jpg`;
                    let counter = 1;
                    while (seenNames.has(filename)) {
                        filename = `${base}(${counter++}).jpg`;
                    }
                    seenNames.add(filename);

                    chrome.runtime.sendMessage({
                        action: 'downloadImage',
                        url,
                        filename
                    });
                });
            }

            // 3. 复制并返回 true
            if (textContent) {
                const ta = document.createElement('textarea');
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                ta.value = textContent;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                return true;
            }
        } else {
            // 没找到 #article-body
            chrome.runtime.sendMessage({ action: 'noImages' });
        }
        return false;
    }

    // 处理 economist.com
    else if (window.location.hostname.includes("economist.com")) {

        // ===== [新增/优化分支] 专门适配 Economist 1843 杂志等 Svelte 架构页面 =====
        const handleEconomistSvelteOr1843 = (() => {
            try {
                // 1843 页面常有 .body-1843 容器，或含有 svelte- 标识的 class
                const isSveltePage = document.querySelector('.body-1843') || document.querySelector('[class*="svelte-"]');
                if (!isSveltePage) return false;

                // 1) 提取正文（兼容 body-text 标签和普通段落）
                const bodyTextNodes = Array.from(document.querySelectorAll('body-text, .article-text body-text, p[data-component="paragraph"]'));
                let extractedText = '';
                if (bodyTextNodes.length > 0) {
                    extractedText = bodyTextNodes.map(node => {
                        return node.textContent
                            .replace(/\s+/g, ' ')
                            .replace(/[•∞@]/g, '')
                            .trim();
                    })
                        .filter(t => t && t.length > 5 && !/^[.\s]*$/.test(t))
                        .join('\n\n');
                }

                // 2) 提取图片（兼容头图 div.image 和正文 figure.media）
                // 选取所有包含 img 的图片容器
                const imageContainers = Array.from(document.querySelectorAll('div.image, figure.media, figure[class*="svelte-"], div.wrapper[class*="svelte-"]'));
                const validImages = [];

                imageContainers.forEach(container => {
                    // 【关键修改点】：排除推荐/相关内容区域的图片
                    if (
                        container.closest('.related-content') ||
                        container.closest('.related-articles') ||
                        container.closest('aside') ||
                        container.closest('[data-testid="related-content"]')
                    ) {
                        return; // 跳过，不处理推荐区域的图片
                    }

                    const img = container.querySelector('img');
                    if (!img) return;

                    // 提取最高分辨率 URL
                    let bestUrl = '';
                    if (img.srcset) {
                        const entries = img.srcset
                            .split(',')
                            .map(e => e.trim())
                            .filter(Boolean)
                            .map(e => {
                                const parts = e.split(/\s+/);
                                const url = parts[0];
                                const wStr = parts[1] || '';
                                const w = parseInt(wStr.replace(/[^\d]/g, ''), 10) || 0;
                                return { url, w };
                            })
                            .sort((a, b) => b.w - a.w);
                        if (entries.length > 0) bestUrl = entries[0].url;
                    }
                    if (!bestUrl && img.src) bestUrl = img.src;
                    if (!bestUrl) return;

                    // 修复 OCR 识别出的 "Linteractive" 或相对路径
                    if (bestUrl.startsWith('Linteractive')) {
                        bestUrl = '/' + bestUrl.substring(1);
                    }
                    // 补全相对路径为完整绝对路径
                    try {
                        bestUrl = new URL(bestUrl, window.location.href).href;
                    } catch (e) {
                        console.warn("URL resolve failed:", bestUrl);
                    }

                    // 提取描述 (Caption)
                    let caption = '';
                    const figcaption = container.querySelector('figcaption');
                    if (figcaption) {
                        caption = figcaption.textContent
                            .replace(/\s+/g, ' ')
                            .replace(/“|”|‘|’/g, '"')
                            .trim();
                    } else if (img.alt) {
                        caption = img.alt.trim();
                    }

                    validImages.push({ url: bestUrl, caption });
                });

                // 如果找到了正文或图片，则执行处理
                if (extractedText || validImages.length > 0) {
                    textContent = extractedText;

                    if (validImages.length === 0) {
                        chrome.runtime.sendMessage({ action: 'noImages' });
                    } else {
                        imagesFoundForDownload = true;
                        const processedUrls = new Set();
                        const processedNames = new Set();

                        validImages.forEach((imgData, idx) => {
                            if (processedUrls.has(imgData.url)) return;
                            processedUrls.add(imgData.url);

                            // 文件后缀
                            let ext = 'jpg';
                            try {
                                const pathname = new URL(imgData.url).pathname;
                                const m = pathname.match(/\.(jpg|jpeg|png|webp|svg)(?:$|\?)/i);
                                if (m) ext = m[1].toLowerCase() === 'jpeg' ? 'jpg' : m[1].toLowerCase();
                            } catch (_) { }

                            // 清洗文件名
                            const clean = (s) => (s || '')
                                .replace(/[/\\?%*:|"<>+]/g, '-')
                                .replace(/\s+/g, ' ')
                                .trim();

                            let baseName = clean(imgData.caption);
                            // 如果描述过长，截断
                            if (baseName.length > 150) baseName = baseName.slice(0, 150);
                            if (!baseName) baseName = `economist-1843-image-${Date.now()}-${idx}`;

                            let filename = `${baseName}.${ext}`;
                            let counter = 1;
                            while (processedNames.has(filename)) {
                                filename = `${baseName}(${counter++}).${ext}`;
                            }
                            processedNames.add(filename);

                            chrome.runtime.sendMessage({
                                action: 'downloadImage',
                                url: imgData.url,
                                filename: filename
                            });
                        });
                    }

                    // 复制文本到剪贴板
                    if (textContent) {
                        const ta = document.createElement('textarea');
                        ta.style.position = 'fixed';
                        ta.style.opacity = '0';
                        ta.value = textContent;
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);
                    }
                    return true; // 成功匹配并处理
                }
                return false;
            } catch (err) {
                console.warn('[Economist Svelte/1843 Branch] failed:', err);
                return false;
            }
        })();

        // 如果 1843 分支成功处理，则直接跳出
        if (handleEconomistSvelteOr1843) {
            // 已经处理完毕，直接进入收尾
        } else {
            // ===== 新结构优先：Next.js 模板 =====
            (function handleEconomistNewTemplate() {
                try {
                    const newArticle = document.querySelector('article#new-article-template[data-test-id="Article"]') ||
                        document.querySelector('article[data-test-id="Article"]');

                    if (!newArticle) {
                        return;
                    }

                    const paragraphNodes = Array.from(newArticle.querySelectorAll('p[data-component="paragraph"]'));
                    const joinNormalizedSpaces = (s) => s.replace(/\s+/g, ' ').replace(/&nbsp;/g, ' ').trim();

                    const getParagraphText = (p) => {
                        let head = '';
                        const firstCap = p.querySelector('span[data-caps="initial"]');
                        const small = firstCap ? firstCap.nextElementSibling && firstCap.nextElementSibling.tagName === 'SMALL' ? firstCap.nextElementSibling : null : null;

                        if (firstCap) head += firstCap.textContent || '';
                        if (small) head += small.textContent || '';

                        const textFromNode = (node) => {
                            if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
                            if (node.nodeType === Node.ELEMENT_NODE) {
                                if (node === firstCap || node === small) return '';
                                let acc = '';
                                node.childNodes.forEach(ch => acc += textFromNode(ch));
                                return acc;
                            }
                            return '';
                        };

                        let tail = '';
                        p.childNodes.forEach(node => {
                            if (node === firstCap || node === small) return;
                            tail += textFromNode(node);
                        });

                        let full = (head + ' ' + tail);
                        full = joinNormalizedSpaces(full)
                            .replace(/[•∞@]/g, '')
                            .trim();

                        return full;
                    };

                    let extractedParas = paragraphNodes.map(getParagraphText).filter(t => {
                        if (!t) return false;
                        if (t.length < 5) return false;
                        if (/^(Advertisement|Sponsored)$/i.test(t)) return false;
                        if (/^[.\s•@∞]+$/.test(t)) return false;
                        return true;
                    });

                    const newTextContent = extractedParas.join('\n\n');

                    if (newTextContent) {
                        const figures = Array.from(newArticle.querySelectorAll('figure.css-3mn275, figure[class*="css-3mn275"]'));
                        const processedUrls = new Set();

                        if (figures.length === 0) {
                            // No images
                        } else {
                            imagesFoundForDownload = true;
                            figures.forEach((figure, idx) => {
                                // 【额外安全过滤】：排除可能存在于 Next.js 模板下方的推荐区域
                                if (figure.closest('.related-content') || figure.closest('.related-articles') || figure.closest('aside')) {
                                    return;
                                }

                                const img = figure.querySelector('img');
                                if (!img) return;

                                let bestUrl = '';
                                if (img.srcset) {
                                    const entries = img.srcset
                                        .replace(/\s+/g, ' ')
                                        .split(',')
                                        .map(e => e.trim())
                                        .filter(Boolean)
                                        .map(e => {
                                            const parts = e.split(' ');
                                            const url = parts[0];
                                            const wStr = parts[1] || '';
                                            const w = parseInt(wStr.replace(/[^\d]/g, ''), 10) || 0;
                                            return { url, w };
                                        })
                                        .sort((a, b) => b.w - a.w);
                                    if (entries.length > 0) bestUrl = entries[0].url;
                                }
                                if (!bestUrl && img.src) bestUrl = img.src;

                                if (!bestUrl) return;

                                try {
                                    const u = new URL(bestUrl, window.location.href);
                                    if (u.pathname.startsWith('/cdn-cgi/image')) {
                                        const rebuilt = u.origin + '/cdn-cgi/image/width=1424,quality=80,format=auto' +
                                            u.pathname.replace(/^\/cdn-cgi\/image\/[^/]+/, '').replace(/\/{2,}/g, '/');
                                        bestUrl = rebuilt + (u.search || '');
                                    } else {
                                        bestUrl = u.href;
                                    }
                                } catch (e) { }

                                if (processedUrls.has(bestUrl)) return;
                                processedUrls.add(bestUrl);

                                let caption = '';
                                const capSpan = figure.querySelector('figcaption span.css-1st60ou, figcaption span[class*="css-1st60ou"]');
                                if (capSpan && capSpan.textContent) {
                                    caption = capSpan.textContent.trim();
                                } else if (img.alt) {
                                    caption = img.alt.trim();
                                }

                                let ext = 'jpg';
                                try {
                                    const pathname = new URL(bestUrl, window.location.href).pathname;
                                    const m = pathname.match(/\.(jpg|jpeg|png|webp|svg)(?:$|\?)/i);
                                    if (m) ext = m[1].toLowerCase() === 'jpeg' ? 'jpg' : m[1].toLowerCase();
                                } catch (_) { }

                                const clean = (s) => (s || '')
                                    .replace(/&nbsp;/g, ' ')
                                    .replace(/[/\\?%*:|"<>+]/g, '-')
                                    .replace(/\s+/g, ' ')
                                    .trim();
                                let baseName = clean(caption) || `economist-image-${Date.now()}-${idx}`;
                                if (baseName.length > 180) baseName = baseName.slice(0, 180);
                                const filename = `${baseName}.${ext}`;

                                chrome.runtime.sendMessage({
                                    action: 'downloadImage',
                                    url: bestUrl,
                                    filename
                                });
                            });
                        }

                        const ta = document.createElement('textarea');
                        ta.style.position = 'fixed';
                        ta.style.opacity = '0';
                        ta.value = newTextContent;
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);

                        textContent = newTextContent;
                    }
                } catch (e) {
                    console.warn('[Economist New Template] parsing failed:', e);
                }
            })();

            // ===== 兼容补丁分支 =====
            (function handleEconomistPatchedVariant() {
                try {
                    if (textContent) return;

                    const articleNode =
                        document.querySelector('article#new-article-template[data-testid="Article"]') ||
                        document.querySelector('article[data-testid="Article"]') ||
                        document.querySelector('article#new-article-template[data-test-id="Article"]') ||
                        document.querySelector('article[data-test-id="Article"]');

                    if (!articleNode) return;

                    const pList = Array.from(articleNode.querySelectorAll('p[data-component="paragraph"]'));
                    if (pList.length === 0) return;

                    const normalizeSpaces = (s) =>
                        (s || '')
                            .replace(/&nbsp;/g, ' ')
                            .replace(/\s+/g, ' ')
                            .trim();

                    const getTextDeep = (node, skipSet) => {
                        if (!node) return '';
                        if (skipSet && skipSet.has(node)) return '';
                        if (node.nodeType === Node.TEXT_NODE) {
                            return node.textContent || '';
                        }
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            let acc = '';
                            node.childNodes.forEach(ch => {
                                acc += getTextDeep(ch, skipSet);
                            });
                            return acc;
                        }
                        return '';
                    };

                    const extractParagraph = (p) => {
                        const firstCap = p.querySelector('span[data-caps="initial"]');
                        const smallAfter =
                            firstCap && firstCap.nextElementSibling && firstCap.nextElementSibling.tagName === 'SMALL'
                                ? firstCap.nextElementSibling
                                : null;

                        let head = '';
                        if (firstCap && firstCap.textContent) head += firstCap.textContent;
                        if (smallAfter && smallAfter.textContent) head += smallAfter.textContent;

                        const skip = new Set();
                        if (firstCap) skip.add(firstCap);
                        if (smallAfter) skip.add(smallAfter);

                        let tail = getTextDeep(p, skip);
                        let full = `${head} ${tail}`;

                        full = full
                            .replace(/[•∞@]/g, ' ')
                            .replace(/“|”|‘|’/g, '"')
                            .replace(/\s*"\s*/g, '"');

                        full = normalizeSpaces(full);
                        full = full.replace(/\s"\s/g, ' ');
                        full = full.replace(/"\s*([^\"]+?)\s*"/g, '$1');
                        full = normalizeSpaces(full)
                            .replace(/[•∞@]/g, '')
                            .trim();

                        return full;
                    };

                    let paras = pList
                        .map(extractParagraph)
                        .filter(t => {
                            if (!t) return false;
                            if (t.length < 5) return false;
                            if (/^(Advertisement|Sponsored)$/i.test(t)) return false;
                            if (/^[.\s•@∞]+$/.test(t)) return false;
                            return true;
                        });

                    const patchedText = paras.join('\n\n');

                    if (patchedText) {
                        const figures = Array.from(
                            articleNode.querySelectorAll(
                                'figure.css-3mn275, figure[class*="css-3mn275"], figure[class*="e1197rjj0"]'
                            )
                        );

                        const processed = new Set();

                        if (figures.length > 0) {
                            imagesFoundForDownload = true;
                            figures.forEach((figure, idx) => {
                                // 【额外安全过滤】：排除推荐区域
                                if (figure.closest('.related-content') || figure.closest('.related-articles') || figure.closest('aside')) {
                                    return;
                                }

                                const img = figure.querySelector('img');
                                if (!img) return;

                                let bestUrl = '';
                                const rawSrcset = (img.getAttribute('srcset') || '').replace(/\s+/g, ' ').trim();

                                if (rawSrcset) {
                                    const entries = rawSrcset
                                        .split(',')
                                        .map(s => s.trim())
                                        .filter(Boolean)
                                        .map(e => {
                                            const parts = e.split(' ');
                                            const url = parts[0];
                                            const wStr = parts[1] || '';
                                            const w = parseInt(wStr.replace(/[^\d]/g, ''), 10) || 0;
                                            return { url, w };
                                        })
                                        .sort((a, b) => b.w - a.w);
                                    if (entries.length > 0) bestUrl = entries[0].url;
                                }
                                if (!bestUrl && img.src) bestUrl = img.src;

                                if (!bestUrl) return;

                                try {
                                    const u = new URL(bestUrl, window.location.href);
                                    if (u.pathname.startsWith('/cdn-cgi/image')) {
                                        const rebuilt =
                                            u.origin +
                                            '/cdn-cgi/image/width=1424,quality=80,format=auto' +
                                            u.pathname.replace(/^\/cdn-cgi\/image\/[^/]+/, '').replace(/\/{2,}/g, '/');
                                        bestUrl = rebuilt + (u.search || '');
                                    } else {
                                        bestUrl = u.href;
                                    }
                                } catch (_) { }

                                if (processed.has(bestUrl)) return;
                                processed.add(bestUrl);

                                let caption = '';
                                const capSpan =
                                    figure.querySelector('figcaption span.css-1st60ou') ||
                                    figure.querySelector('figcaption span[class*="css-1st60ou"]') ||
                                    figure.querySelector('figcaption') ||
                                    null;
                                if (capSpan && capSpan.textContent) {
                                    caption = capSpan.textContent.trim();
                                } else if (img.alt) {
                                    caption = img.alt.trim();
                                }

                                let ext = 'jpg';
                                try {
                                    const pathname = new URL(bestUrl, window.location.href).pathname;
                                    const m = pathname.match(/\.(jpg|jpeg|png|webp|svg)(?:$|\?)/i);
                                    if (m) ext = m[1].toLowerCase() === 'jpeg' ? 'jpg' : m[1].toLowerCase();
                                } catch (_) { }

                                const clean = (s) =>
                                    (s || '')
                                        .replace(/&nbsp;/g, ' ')
                                        .replace(/[/\\?%*:|"<>+]/g, '-')
                                        .replace(/\s+/g, ' ')
                                        .trim();

                                let baseName = clean(caption) || `economist-image-${Date.now()}-${idx}`;
                                if (baseName.length > 180) baseName = baseName.slice(0, 180);
                                const filename = `${baseName}.${ext}`;

                                chrome.runtime.sendMessage({
                                    action: 'downloadImage',
                                    url: bestUrl,
                                    filename
                                });
                            });
                        }

                        const ta = document.createElement('textarea');
                        ta.style.position = 'fixed';
                        ta.style.opacity = '0';
                        ta.value = patchedText;
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);

                        textContent = patchedText;
                    }
                } catch (err) {
                    console.warn('[Economist Patched Variant] parsing failed:', err);
                }
            })();

            // ===== 旧结构逻辑 =====
            let article = document.querySelector('[data-test-id="Article"]');
            let paragraphs;

            if (article) {
                paragraphs = article.querySelectorAll('p[data-component="paragraph"]');
            } else {
                article = document.querySelector('.article-text') || document.body;
                if (article) {
                    paragraphs = document.querySelectorAll('.article-text body-text, body-text.svelte-16dgy1v');
                }
            }

            if (paragraphs && paragraphs.length > 0 && !textContent) {
                textContent = Array.from(paragraphs)
                    .map(p => {
                        function getAllText(node) {
                            let text = '';
                            Array.from(node.childNodes).forEach(child => {
                                if (child.nodeType === Node.TEXT_NODE) text += child.textContent;
                                else if (child.nodeType === Node.ELEMENT_NODE) {
                                    if (child.tagName === 'SPAN' && child.getAttribute('data-caps') === 'initial') text += child.textContent;
                                    else if (child.tagName === 'SMALL') text += child.textContent;
                                    else if (child.tagName === 'I') text += child.textContent;
                                    else if (child.tagName === 'A' || child.children.length > 0) text += getAllText(child);
                                    else text += child.textContent;
                                }
                            });
                            return text;
                        }
                        let text = getAllText(p)
                            .replace(/\s+/g, ' ')
                            .replace(/[•∞@]/g, '')
                            .replace(/&nbsp;/g, ' ')
                            .trim();
                        return text;
                    })
                    .filter(text => {
                        return text &&
                            text.length > 5 &&
                            !['@', '•', '∞', 'flex'].includes(text) &&
                            !/^\s*$/.test(text) &&
                            !/^[.\s]*$/.test(text) &&
                            !/^By\s/.test(text);
                    })
                    .join('\n\n');

                if (textContent) {
                    const figures = Array.from(article.querySelectorAll('figure.css-3mn275'))
                        .filter(figure => {
                            return !figure.closest('[data-optimizely="onward-articles-component"]') &&
                                !figure.closest('[data-optimizely="related-articles-section"]') &&
                                !figure.closest('[data-tracking-id="content-well-chapter-list"]') &&
                                !figure.closest('.css-1qaigru') &&
                                !figure.closest('.css-12lyffs') &&
                                !figure.closest('.css-1xfkcl4') &&
                                !figure.closest('.related-content') && // 额外安全过滤
                                !figure.closest('.related-articles');
                        });

                    if (figures.length === 0) {
                        chrome.runtime.sendMessage({ action: 'noImages' });
                    } else {
                        imagesFoundForDownload = true;
                        figures.forEach(figure => {
                            const img = figure.querySelector('img');
                            if (img) {
                                let fileExtension = 'jpg';
                                const srcUrl = img.src || '';
                                if (srcUrl.includes('format=auto')) {
                                    const originalPath = srcUrl.split('/').pop().split('_')[1];
                                    if (originalPath) {
                                        const match = originalPath.match(/\.(jpg|jpeg|png|webp)$/i);
                                        if (match) fileExtension = match[1].toLowerCase();
                                    }
                                }
                                const baseUrl = srcUrl.split('/content-assets/')[0] + '/content-assets/';
                                const imagePath = srcUrl.split('/content-assets/')[1].split('?')[0];
                                const highResUrl = `${baseUrl}${imagePath}?width=1424&quality=80&format=auto`;

                                let imageDescription = '';
                                const figcaptionSpan = figure.querySelector('figcaption span.css-1st60ou');
                                if (figcaptionSpan && figcaptionSpan.textContent.trim()) {
                                    imageDescription = figcaptionSpan.textContent.trim();
                                } else if (img.alt && img.alt.trim()) {
                                    imageDescription = img.alt.trim();
                                }

                                let filename;
                                const now = new Date();
                                const timestamp = `${now.getHours()}${now.getMinutes()}${now.getSeconds()}`;
                                if (imageDescription) {
                                    filename = `${imageDescription.replace(/[/\\?%*:|"<>+]/g, '-')}.${fileExtension}`;
                                    if (filename.startsWith('Photograph- ') || filename.startsWith('Chart- ')) {
                                        const seconds = now.getSeconds();
                                        const namePart = filename.substring(0, filename.lastIndexOf('.'));
                                        const extensionPart = filename.substring(filename.lastIndexOf('.'));
                                        filename = `${namePart}-${seconds}${extensionPart}`;
                                    }
                                } else {
                                    filename = `economist-image-${timestamp}.${fileExtension}`;
                                }
                                if (filename.length > 200) {
                                    filename = filename.substring(0, 196) + '.' + fileExtension;
                                }

                                chrome.runtime.sendMessage({
                                    action: 'downloadImage',
                                    url: highResUrl,
                                    filename: filename
                                });
                            }
                        });
                    }
                }
            }
        }
    }

    // ==========================================
    // 3. 通用/收尾逻辑
    // ==========================================

    if (textContent) {
        // 定义要过滤的字符串
        const unwantedText = "If you can't see the content of video posts, please adjust your cookie settings";

        // 使用 replaceAll 替换所有匹配项，并去除多余的空行（可选）
        textContent = textContent.split(unwantedText).join('').trim();

        // 如果替换后导致出现了连续的空行，可以进一步清理（可选）
        textContent = textContent.replace(/\n{3,}/g, '\n\n');
    }

    // 如果提取到了文本，执行复制
    if (textContent) {
        // 创建一个隐藏的 textarea 元素以复制文本
        const textarea = document.createElement('textarea');
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        textarea.value = textContent;
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length); // For better compatibility

        try {
            document.execCommand('copy');
            // 返回 true 表示文本复制成功。图片下载是异步的，其成功与否由 background script 的通知处理。
            return true;
        } catch (err) {
            console.error('复制失败:', err);
            return false;
        } finally {
            document.body.removeChild(textarea);
        }
    } else if (imagesFoundForDownload) {
        return true; // 即使没有文本，但成功触发了图片下载，也返回 true 避免误报“复制失败”
    }

    return false; // 默认返回 false，表示没有文本内容被复制
}