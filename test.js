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
                // 可以在这里通知用户下载失败，但避免干扰已有的通知逻辑
                // 如果需要，可以向 content script 发送消息显示特定错误
                if (tabId !== null && DownloadsPending[tabId]) {
                    // 尝试从队列中移除，即使没有 downloadId (不太可能发生)
                    // 主要目的是为了在所有其他图片下载完成后能正确触发“全部完成”
                    // 但这里没有 downloadId，所以无法精确移除
                }
                return;
            }
            if (downloadId && tabId !== null && DownloadsPending[tabId]) {
                // 将下载任务ID加入跟踪队列中
                DownloadsPending[tabId].downloads.push(downloadId);
            } else if (!downloadId && tabId !== null && DownloadsPending[tabId]) {
                // 如果下载启动失败 (没有 downloadId)，也应该处理队列
                // 这种情况比较少见，但为了健壮性可以考虑
                // 例如，如果URL无效，downloadId可能是undefined
                // 为了简单起见，我们主要依赖 onChanged 的 complete 状态
                // 但如果一个下载从未开始，它也不会完成。
                // 这种情况下，如果 DownloadsPending[tabId].downloads 最终为空，
                // 且 hasStartedImageProcess 为 true，但没有图片实际下载，
                // “所有图片下载完成”的通知可能不准确。
                // 一个更复杂的处理是记录预期下载数量。
            }
        });
    } else if (request.action === 'noImages') {
        // 处理无图片的情况
        const tabId = sender.tab ? sender.tab.id : null;
        if (tabId !== null) {
            // 检查 DownloadsPending[tabId] 是否已初始化，以及是否真的没有图片开始下载
            if (DownloadsPending[tabId] && DownloadsPending[tabId].downloads && DownloadsPending[tabId].downloads.length === 0 && DownloadsPending[tabId].hasStartedImageProcess) {
                // 如果已经标记开始处理图片，但下载队列为空，并且收到了 noImages
                // 这意味着确实没有图片被发送到下载流程
                chrome.scripting.executeScript({
                    target: { tabId: tabId },
                    function: showNotification,
                    args: ['没有找到可下载的图片']
                });
                delete DownloadsPending[tabId]; // 清理
            } else if (!DownloadsPending[tabId] || !DownloadsPending[tabId].hasStartedImageProcess) {
                // 如果从未开始图片处理流程（例如，文本提取失败导致根本没尝试图片）
                // 或者，如果这是第一次收到 noImages 且尚未初始化 DownloadsPending
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
                // Optionally remove style if no more notifications are expected soon
                // const styleSheet = document.getElementById('notification-style');
                // if (styleSheet) styleSheet.remove();
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

            if (textContent) {
                // 定义要过滤的字符串
                const unwantedText = "If you can't see the content of video posts, please adjust your cookie settings";

                // 使用 replaceAll 替换所有匹配项，并去除多余的空行（可选）
                textContent = textContent.split(unwantedText).join('').trim();

                // 如果替换后导致出现了连续的空行，可以进一步清理（可选）
                textContent = textContent.replace(/\n{3,}/g, '\n\n');
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

    // 处理 reuters.com
    else if (window.location.hostname.includes("reuters.com")) {
        // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        // ★★★ 新增逻辑: 针对 Reuters Special Report (如年度图片) ★★★
        // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
        const specialReportContainer = document.querySelector('.special-report-article-container, .scrollytelling-body');

        if (specialReportContainer) {
            imagesFoundForDownload = true;

            // 1. 提取文本 (从 .scrollytelling-body 下的 p 标签提取)
            // 过滤掉类似 "@", "®" 或空内容的杂项
            const contentNodes = document.querySelectorAll('.scrollytelling-body p');
            textContent = Array.from(contentNodes)
                .map(node => node.textContent.trim())
                .filter(text => text.length > 1 && !['@', '•', '®'].includes(text))
                .join('\n\n');

            // 2. 提取图片 (针对 figure.media-item)
            const figures = document.querySelectorAll('figure.media-item');
            const processedUrls = new Set();

            if (figures.length === 0) {
                chrome.runtime.sendMessage({ action: 'noImages' });
            } else {
                figures.forEach((figure, idx) => {
                    const img = figure.querySelector('img');
                    if (!img || !img.src) return;

                    let url = img.src;

                    // 确保 URL 是绝对路径
                    try {
                        url = new URL(url, window.location.href).href;
                    } catch (e) {
                        return;
                    }

                    // 过滤掉 base64 小图或重复图
                    if (url.startsWith('data:image/') || processedUrls.has(url)) return;
                    processedUrls.add(url);

                    // --- 提取标题 (针对 Special Report 的结构) ---
                    let caption = '';

                    // 优先尝试获取 .captiontext (包含主要描述)
                    const captionTextDiv = figure.querySelector('.captiontext');
                    const countryTitleDiv = figure.querySelector('.countrytitle');

                    if (captionTextDiv) {
                        caption = captionTextDiv.textContent.trim();
                    } else {
                        // 回退到 figcaption
                        const figcaption = figure.querySelector('figcaption');
                        if (figcaption) caption = figcaption.textContent.trim();
                    }

                    // 清理描述文本: 移除 "REUTERS/..." 和多余的引号
                    // 注意：captionTextDiv.textContent 包含了 span.photog，这里用正则去掉
                    caption = caption.replace(/REUTERS\/.*$/i, '') // 移除摄影师署名
                        .replace(/^[“"']+|[”"']+$/g, '')          // 移除首尾引号
                        .trim();

                    // 如果需要，可以将地点加在文件名前面 (可选)
                    // if (countryTitleDiv && countryTitleDiv.textContent) {
                    //    caption = countryTitleDiv.textContent.trim() + ' - ' + caption;
                    // }

                    // --- 生成文件名 ---
                    const extMatch = url.match(/\.(png|jpe?g|webp)(\?|$)/i);
                    const ext = extMatch ? extMatch[1] : 'jpg';

                    let filename = caption ?
                        caption.replace(/[\\/?%*:|"<>+]/g, '-').substring(0, 180) :
                        `reuters-special-${Date.now()}-${idx}`;

                    // 去除多余空格
                    filename = filename.replace(/\s+/g, ' ').trim() + '.' + ext;

                    // 发送下载消息
                    chrome.runtime.sendMessage({
                        action: 'downloadImage',
                        url: url,
                        filename: filename
                    });
                });
            }

        } else if (document.querySelector('div[data-testid="LivePage"], .arena-liveblog')) {
            // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            // ★★★ 新增逻辑: 针对 Reuters Live Blog (直播报道) 页面 ★★★
            // ★★★ 例如: /world/europe/eurovision-... live page 等       ★★★
            // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            const livePageContainer = document.querySelector(
                'div[data-testid="LivePage"], .arena-liveblog'
            );

            if (livePageContainer) {
                imagesFoundForDownload = true;
                const processedUrls = new Set();
                const seenNames = new Set();
                const textParts = [];

                // -------- 工具函数：从 srcset 中挑最高分辨率 --------
                const pickHighestFromSrcset = (srcset) => {
                    if (!srcset) return '';
                    const candidates = srcset.split(',')
                        .map(entry => {
                            const parts = entry.trim().split(/\s+/);
                            const u = parts[0];
                            const w = parts[1] ? parseInt(parts[1]) : 0;
                            return { url: u, width: w };
                        })
                        .filter(c => c.url && c.width > 0 && !c.url.startsWith('data:'))
                        .sort((a, b) => b.width - a.width);
                    return candidates.length ? candidates[0].url : '';
                };

                // -------- 工具函数：清理 caption --------
                const cleanCaption = (txt) => {
                    if (!txt) return '';
                    return txt
                        .replace(/\u200B/g, '')                  // 零宽空格
                        .replace(/REUTERS\/.*$/i, '')            // 摄影师署名
                        .replace(/^["“"']+|["""']+$/g, '')       // 首尾引号
                        .replace(/\s+/g, ' ')
                        .trim();
                };

                // -------- 工具函数：根据 caption 生成唯一文件名 --------
                const makeFilename = (caption, fallback, url) => {
                    let ext = 'jpg';
                    const m = url.match(/\.(png|jpe?g|webp|gif)(\?|$|_)/i);
                    if (m) ext = m[1].toLowerCase() === 'jpeg' ? 'jpg' : m[1].toLowerCase();

                    let base = (caption || fallback)
                        .replace(/[\\/?%*:|"<>+]/g, '-')
                        .replace(/\s+/g, ' ')
                        .substring(0, 180)
                        .trim();
                    if (!base) base = fallback;

                    let filename = `${base}.${ext}`;
                    let counter = 1;
                    while (seenNames.has(filename)) {
                        filename = `${base}(${counter++}).${ext}`;
                    }
                    seenNames.add(filename);
                    return filename;
                };

                // -------- 1. 抓取页面大标题 --------
                const heading = document.querySelector('h1[data-testid="Heading"]');
                if (heading && heading.textContent.trim()) {
                    textParts.push(heading.textContent.trim());
                }

                // -------- 2. 处理顶部 primary-image (lead image) --------
                const primaryImage = document.querySelector('[data-testid="primary-image"]');
                if (primaryImage) {
                    const img = primaryImage.querySelector('img');
                    if (img) {
                        let url = pickHighestFromSrcset(img.srcset) || img.src || '';
                        if (url && !processedUrls.has(url)) {
                            processedUrls.add(url);

                            let caption = '';
                            // caption 通常在 [data-testid="Body"] 里的第一个 span
                            const capSpan = primaryImage.querySelector(
                                '[data-testid="Body"] span, figcaption span'
                            );
                            if (capSpan) {
                                // 只取 span 的直接文本，避免把 <a>(license) 也带进来
                                caption = Array.from(capSpan.childNodes)
                                    .filter(n => n.nodeType === Node.TEXT_NODE)
                                    .map(n => n.textContent)
                                    .join(' ')
                                    .trim();
                                if (!caption) caption = capSpan.textContent.trim();
                            }
                            if (!caption && img.alt) caption = img.alt.trim();
                            caption = cleanCaption(caption);

                            const filename = makeFilename(
                                caption,
                                `reuters-live-lead-${Date.now()}`,
                                url
                            );
                            chrome.runtime.sendMessage({
                                action: 'downloadImage',
                                url: url,
                                filename: filename
                            });
                        }
                    }
                }

                // -------- 3. 处理直播流卡片 --------
                const cards = document.querySelectorAll(
                    '[data-testid="live-pbp-card"], .live-message--card'
                );
                let liveImgIdx = 0;

                cards.forEach(card => {
                    const body = card.querySelector(
                        '.live-message--card--body, [class*="LivePlayByPlayCardBody"]'
                    );
                    if (!body) return;

                    const paragraphs = Array.from(body.querySelectorAll('p'));
                    const skipIndices = new Set();

                    paragraphs.forEach((p, pIdx) => {
                        if (skipIndices.has(pIdx)) return;

                        const arenaImg = p.querySelector('arena-image');
                        const directImg = p.querySelector('img');

                        // ===== A. 图片段落 =====
                        if (arenaImg || directImg) {
                            let imgUrl = '';
                            let imgAlt = '';

                            // 优先尝试 shadow DOM 内的 img
                            let innerImg = null;
                            if (arenaImg) {
                                if (arenaImg.shadowRoot) {
                                    innerImg = arenaImg.shadowRoot.querySelector('img');
                                }
                                if (!innerImg) {
                                    innerImg = arenaImg.querySelector('img');
                                }
                                imgAlt = arenaImg.getAttribute('alt') || '';
                            }
                            if (!innerImg) innerImg = directImg;

                            if (innerImg) {
                                imgUrl = pickHighestFromSrcset(innerImg.srcset) ||
                                    innerImg.src || '';
                                if (!imgAlt) imgAlt = innerImg.alt || '';
                            }

                            // 兜底：直接拿 arena-image 的 src，并去掉 ?w=… 参数取原图
                            if (!imgUrl && arenaImg) {
                                let raw = arenaImg.getAttribute('src') || '';
                                imgUrl = raw.split('?')[0];
                            }

                            if (!imgUrl) return;
                            // 转绝对路径
                            try { imgUrl = new URL(imgUrl, window.location.href).href; }
                            catch (e) { return; }

                            if (processedUrls.has(imgUrl)) return;
                            processedUrls.add(imgUrl);
                            liveImgIdx++;

                            // 找 caption: 紧随其后的 <p><span class="ql-size-small">…</span></p>
                            let caption = '';
                            const nextP = paragraphs[pIdx + 1];
                            if (nextP) {
                                const sizeSmall = nextP.querySelector('.ql-size-small');
                                if (sizeSmall) {
                                    caption = sizeSmall.textContent.trim();
                                    skipIndices.add(pIdx + 1);  // 这段不进正文
                                }
                            }
                            if (!caption) caption = imgAlt;
                            caption = cleanCaption(caption);

                            const filename = makeFilename(
                                caption,
                                `reuters-live-${Date.now()}-${liveImgIdx}`,
                                imgUrl
                            );
                            chrome.runtime.sendMessage({
                                action: 'downloadImage',
                                url: imgUrl,
                                filename: filename
                            });
                            return;
                        }

                        // ===== B. 文本段落 =====
                        // 跳过纯 caption（整段只有一个 .ql-size-small）
                        const sizeSmallOnly = p.querySelector('.ql-size-small');
                        if (sizeSmallOnly &&
                            p.children.length === 1 &&
                            p.firstElementChild === sizeSmallOnly) {
                            return;
                        }

                        const text = p.textContent
                            .replace(/\u200B/g, '')      // 零宽空格
                            .replace(/\s+/g, ' ')
                            .trim();

                        if (!text) return;
                        if (text.length <= 1) return;
                        if (['•', '@', '∞', '·', '.'].includes(text)) return;

                        textParts.push(text);
                    });
                });

                textContent = textParts.join('\n\n');

                if (processedUrls.size === 0) {
                    chrome.runtime.sendMessage({ action: 'noImages' });
                }
            }
        } else {
            // ★★★ 下面是原有的 Svelte 和旧版逻辑，保持不变，放在 else 中 ★★★

            // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
            // ★★★ START: NEW LOGIC FOR SVELTE-BASED (GRAPHICS) REUTERS PAGES ★★★
            // ★★★ 开始：为基于Svelte的新版（图文）路透社页面添加的新逻辑 ★★★
            const svelteArticle = document.querySelector('main#main-content article[class*="svelte-"]');

            if (svelteArticle) {
                // 确认是新版Svelte页面结构
                imagesFoundForDownload = true; // 标记我们将要处理内容

                // 1. 提取文本 (段落和标题)
                const contentNodes = svelteArticle.querySelectorAll('p, h2');
                textContent = Array.from(contentNodes)
                    .map(node => node.textContent.trim())
                    .filter(text => text && text.length > 1 && !['@', '•', '∞', 'flex'].includes(text))
                    .join('\n\n');

                // 2. 提取图片
                const figures = svelteArticle.querySelectorAll('figure');
                const processedUrls = new Set();

                if (figures.length === 0) {
                    chrome.runtime.sendMessage({ action: 'noImages' });
                } else {
                    figures.forEach((figure, idx) => {
                        const img = figure.querySelector('img');
                        if (!img || !img.src) return;

                        let url = img.src;
                        try {
                            // 确保URL是绝对路径
                            url = new URL(url, window.location.href).href;
                        } catch (e) {
                            console.error("无效的图片URL:", url);
                            return; // 跳过无效的URL
                        }

                        if (processedUrls.has(url)) return;
                        processedUrls.add(url);

                        // 提取图片描述
                        let caption = '';
                        const figcaptionEl = figure.querySelector('figcaption');
                        if (figcaptionEl) {
                            caption = figcaptionEl.textContent.trim();
                        }
                        // 如果没有figcaption，则使用alt属性
                        if (!caption && img.alt) {
                            caption = img.alt.trim();
                        }

                        // 清理描述文本，移除 "REUTERS/..." 等信息
                        caption = caption.replace(/REUTERS\/.*/i, '')
                            .replace(/^["“]+|["”]+$/g, '')
                            .trim();

                        // 从URL中提取文件扩展名，默认为 'jpg'
                        const extMatch = url.match(/\.(png|jpe?g|webp)(\?|$)/i);
                        const ext = extMatch ? extMatch[1] : 'jpg';

                        // 生成文件名
                        let filename = caption ?
                            caption.replace(/[/\\?%*:|"<>+]/g, '-').substring(0, 180) :
                            `reuters-interactive-${Date.now()}-${idx}`;
                        filename = filename + '.' + ext;

                        // 发送下载消息
                        chrome.runtime.sendMessage({
                            action: 'downloadImage',
                            url: url,
                            filename: filename
                        });
                    });
                }
            }

            else {
                // --- 如果不是新版Svelte页面，则执行原有的旧版页面逻辑 ---
                const articleBody = document.querySelector('[data-testid="ArticleBody"]');
                const article = document.querySelector('article[data-testid="Article"]');
                if (articleBody && article) {
                    // 1. 按 DOM 顺序一次性抓取所有 Heading 和 段落
                    const contentNodes = articleBody.querySelectorAll(
                        'h2[data-testid="Heading"], [data-testid^="paragraph-"]'
                    );
                    const textLines = Array.from(contentNodes)
                        .map(el => el.textContent.trim())
                        .filter(t => t.length > 0);
                    textContent = textLines.join('\n\n');

                    // 2. 如果有正文，再去抓图片
                    if (textContent) { // 或者可以改为 if (true) 来总是尝试抓取图片，即使文本内容为空
                        imagesFoundForDownload = true;
                        const processedUrls = new Set();
                        // 更精确地选择图片，可以先尝试轮播图图片，再尝试其他文章图片
                        // 或者直接使用一个通用选择器，如果页面结构不保证所有图片都在 ArticleBody 下
                        const images = Array.from(
                            articleBody.querySelectorAll('img:not([sizes="110px"])')
                        );

                        if (images.length === 0) {
                            chrome.runtime.sendMessage({ action: 'noImages' }); // 更明确的消息
                        } else {
                            images.forEach((img, idx) => {
                                let url = '';
                                // 优先直接的 src (如果它不是一个小的内联数据URI)
                                if (img.src && !img.src.startsWith('data:image/') && img.src !== window.location.href) {
                                    url = img.src;
                                }

                                // 尝试 data attributes (常见的懒加载模式)
                                if (!url || url.startsWith('data:image/')) {
                                    url = img.dataset.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '';
                                }

                                // 从 srcset 中选最高分辨率 (这个逻辑通常是最可靠的)
                                if (img.srcset) {
                                    const candidates = img.srcset
                                        .trim().split(',')
                                        .map(entry => {
                                            const parts = entry.trim().split(/\s+/);
                                            const u = parts[0];
                                            const w = parts[1] ? parts[1].replace('w', '') : '0';
                                            if (!u || u.startsWith('data:image/')) return { url: u, width: 0 };
                                            return { url: u, width: parseInt(w) || 0 };
                                        })
                                        .filter(c => c.width > 0 && c.url && !c.url.startsWith('data:image/'))
                                        .sort((a, b) => b.width - a.width);
                                    if (candidates.length > 0 && candidates[0].url) {
                                        url = candidates[0].url; // srcset 的高优先级
                                    }
                                }

                                // 如果 URL 是相对路径, 转换为绝对路径
                                if (url && url.startsWith('/')) {
                                    try {
                                        url = new URL(url, window.location.origin).href;
                                    } catch (e) {
                                        console.error('Error creating absolute URL:', e);
                                        url = ''; // 无效的相对URL
                                    }
                                }

                                url = url.replace(/\s+/g, ''); // 清理URL中的任何空格 (理论上不应存在)

                                if (!url || url.startsWith('data:image/') || url === window.location.href) { // 最终检查
                                    return; // 跳过这个图片
                                }

                                if (processedUrls.has(url)) {
                                    return;
                                }
                                processedUrls.add(url);

                                // --- 改进的标题提取逻辑 ---
                                let caption = '';
                                // 优先尝试 Figure > Figcaption 结构 (常见于主图)
                                const figureElement = img.closest('figure[data-testid="Figure"]');
                                if (figureElement) {
                                    const captionSpan = figureElement.querySelector('[data-testid="Caption"] span, figcaption span'); // 更通用的选择器
                                    if (captionSpan && captionSpan.textContent) {
                                        caption = captionSpan.textContent;
                                    }
                                }

                                if (!caption) {
                                    const primaryImageDiv = img.closest('[data-testid="primary-image"]');
                                    const figForPrimary = primaryImageDiv ? primaryImageDiv.closest('figure') : null; // primary-image 可能在 figure 内
                                    const actualFig = figForPrimary || img.closest('figure'); // 回退到任意 figure

                                    if (actualFig) {
                                    }
                                }

                                if (caption) { // 清理提取到的 caption
                                    caption = caption.replace(/REUTERS\/.*/i, '')
                                        .replace(/^["“]+|["”]+$/g, '')
                                        .trim();
                                }

                                // Fallback to alt text
                                if (!caption && img.alt) {
                                    caption = img.alt.trim();
                                }
                                // --- 结束标题提取 ---

                                const extMatch = url.match(/\.(png|jpe?g|webp)(\?|$)/i);
                                const ext = extMatch ? extMatch[1] : 'jpg';

                                let filename = caption ?
                                    caption.replace(/[/\\?%*:|"<>+]/g, '-').substring(0, 180) // 缩短一点以防路径过长
                                    :
                                    `reuters-image-${Date.now()}-${idx}`;
                                filename = filename + '.' + ext;

                                chrome.runtime.sendMessage({
                                    action: 'downloadImage',
                                    url: url,
                                    filename: filename
                                });
                            });
                        }
                    }
                } else if (window.location.pathname.includes('/pictures/')) {
                    imagesFoundForDownload = true;
                    // 2.1 抓文字描述（支持 SingleImageHero 和 CollageHero）
                    const heroDesc = document.querySelector(
                        'div[data-testid="SingleImageHeroSubSection"] [data-testid="Body"], ' +
                        'div[data-testid="CollageHeroSubSection"] [data-testid="Body"], ' +
                        'div[data-testid="PicturesLayoutHeroContent"] [data-testid="Body"]'
                    );

                    if (heroDesc) {
                        textContent = heroDesc.textContent.trim(); // 赋值给外层的 textContent
                    }

                    // 2.2 抓所有图片
                    const processedUrls = new Set();
                    const images = Array.from(
                        document.querySelectorAll(
                            'div[data-testid="SingleImageHero"] img, ' +
                            'div[data-testid="CollageHero"] img, ' +
                            'div[data-testid="EventGalleryImageImage"] img'
                        )
                    );

                    images.forEach((img, idx) => {
                        let url = '';
                        // 优先直接的 src
                        if (img.src && !img.src.startsWith('data:image/') && img.src !== window.location.href) {
                            url = img.src;
                        }
                        // 尝试 lazy load 属性
                        if ((!url || url.startsWith('data:image/')) && img.dataset.src) {
                            url = img.dataset.src;
                        }
                        // 解析 srcset
                        if (img.srcset) {
                            const candidates = img.srcset.trim().split(',')
                                .map(entry => {
                                    const [u, w] = entry.trim().split(/\s+/);
                                    return { url: u, width: parseInt(w) || 0 };
                                })
                                .filter(c => c.url && c.width > 0 && !c.url.startsWith('data:image/'))
                                .sort((a, b) => b.width - a.width);

                            if (candidates.length) url = candidates[0].url;
                        }

                        // 补全相对路径
                        if (url && url.startsWith('/')) {
                            try { url = new URL(url, location.origin).href; } catch (e) { url = ''; }
                        }

                        // 清理 URL
                        if (url) url = url.replace(/\s+/g, '');

                        if (!url || url.startsWith('data:image/') || url === location.href) {
                            return;
                        }

                        if (processedUrls.has(url)) {
                            return;
                        }
                        processedUrls.add(url);

                        // ---- 针对图集页面的 Caption 提取 ------------------------------------------
                        let caption = '';

                        // 1. 先找 figcaption 里的 span
                        const fig = img.closest('figure');
                        if (fig) {
                            const span = fig.querySelector('figcaption span, [data-testid="ImageCaption"] span');
                            if (span) caption = span.textContent.trim();
                        }

                        // 2. 如果是 CollageHero 或 SingleHero，尝试用文章的 Title 或 Body 作为文件名
                        // 因为 Hero 图片通常没有直接紧挨着的 caption
                        if (!caption && (img.closest('[data-testid="CollageHero"]') || img.closest('[data-testid="SingleImageHero"]'))) {
                            // 尝试获取页面大标题
                            const mainTitle = document.querySelector('h1[data-testid="Heading"]');
                            if (mainTitle) caption = mainTitle.textContent.trim();
                            // 如果还没有，使用刚才抓取的 textContent 的前一段
                            if (!caption && textContent) caption = textContent.substring(0, 50);
                        }

                        // 3. 再 fallback 用 alt
                        if (!caption && img.alt) caption = img.alt.trim();

                        // 清洗 caption
                        caption = caption.replace(/REUTERS\/.*$/i, '')
                            .replace(/^["“]+|["”]+$/g, '')
                            .trim();

                        // 构造文件名
                        const extMatch = url.match(/\.(png|jpe?g|webp)(\?|$)/i);
                        const ext = extMatch ? extMatch[1] : 'jpg';

                        let filename = caption ?
                            caption.replace(/[\\/?%*:|"<>+]/g, '-').slice(0, 180) :
                            `reuters-pic-${Date.now()}-${idx}`;

                        // 再次清理多余的空格和连字符
                        filename = filename.replace(/\s+/g, ' ').trim();
                        filename += '.' + ext;

                        chrome.runtime.sendMessage({
                            action: 'downloadImage',
                            url,
                            filename
                        });
                    });
                } else {
                    // 如果未找到 articleBody 或 article
                    chrome.runtime.sendMessage({ action: 'noImages' });
                }
            }
        }
    }

    // ==========================================
    // 3. 通用/收尾逻辑
    // ==========================================

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
        // 如果没有文本内容，但尝试了图片下载（例如 Reuters Pictures 页面）
        // 这种情况下，我们不应该返回 false 导致“复制失败”的通知。
        // 而是让 background script 的图片下载通知来主导。
        // 返回一个特殊值或true，表示操作已启动（图片下载）。
        // 或者，如果 extractAndCopy 的返回值仅用于判断文本复制是否成功，
        // 那么这里可以返回 false，但需要确保 'noImages' 或 '所有图片下载完成' 的通知能正确显示。
        // 为了简化，如果主要目的是复制文本，且文本为空，即使有图片，也可能视为“内容未找到（用于复制）”。
        // 保持返回 false，让上层逻辑判断。
        // 如果 extractAndCopy 的返回值 true/false 严格对应文本复制，那么这里返回 false 是对的。
        // 图片下载状态由 `DownloadsPending` 和 `onChanged` 处理。
        return false; // 没有文本可复制
    }

    // 如果既没有文本内容，也没有尝试下载图片（例如，所有网站的解析都失败了）
    if (!textContent && !imagesFoundForDownload) {
        // 确保在没有任何操作发生时，也发送一个 noImages，
        // 以便 background script 可以清理 DownloadsPending（如果之前错误地设置了 hasStartedImageProcess）
        // 但这通常由每个站点处理器内部的 noImages 调用来处理。
        // 此处返回 false 即可。
    }

    return false; // 默认返回 false，表示没有文本内容被复制
}