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
        tab.url.includes("asia.nikkei.com") // 新增 Nikkei Asia
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

    // 处理 wsj.com
    else if (window.location.hostname.includes("wsj.com")) {
        // 扩大搜索范围，有时候内容不在 article 标签直属下，但在 main 或 paywall 容器中
        // 优先锁定 article，如果没有则回退到 document
        const contentRoot = document.querySelector('article') || document.querySelector('main') || document;

        if (contentRoot) {
            // 【关键修改 1】在选择器数组中增加了 h2 和 h3 标签
            // 将所有可能的文本选择器放入一个数组
            // 注意：顺序不再决定提取顺序，DOM流的物理位置决定提取顺序
            const textSelectors = [
                // 1. 视差画廊 (Parallax Gallery)
                '.pg-media-text h4',
                '.pg-media-text p',

                // 2. 增加：标准正文中的小标题 (匹配你的 HTML 中的 <h3 data-type="hed">)
                'h2[data-type="hed"]',
                'h3[data-type="hed"]',

                // 3. 标准正文段落
                'p[data-type="paragraph"]',

                // 4. 针对 WSJ 不同版式的特定 CSS类名
                'p.css-1009hy1-StyledNewsKitParagraph',
                'p.css-k3zb6l-Paragraph',
                'p[class*="emoc1hq1"]',
                'p[class*="css-1jdwmf4"]',

                // 5. Paywall 容器下的段落 (作为兜底)
                '.paywall p'
            ];

            // 使用 join(',') 将选择器合并，querySelectorAll 会按照 DOM 在页面中的物理顺序返回元素
            // 这样返回的 nodeList 是严格按照 HTML 页面从上到下的顺序排列的
            const allElements = contentRoot.querySelectorAll(textSelectors.join(','));

            // 将 NodeList 转换为数组并去重 (防止同一个元素被多个选择器命中)
            let uniqueElements = [...new Set(allElements)];

            textContent = uniqueElements
                .map(el => {
                    // 过滤逻辑：跳过不需要的元素
                    if (
                        el.closest('.ai2html_export') || // 排除图表内嵌文字
                        el.closest('figcaption') ||      // 排除图片说明(通常由图片下载逻辑处理)
                        el.className.includes('g-pstyle')
                    ) {
                        return '';
                    }

                    // 【关键修改 2】扩展标题判断逻辑，包含 h2, h3, h4
                    const tagName = el.tagName.toLowerCase();
                    const isHeader = tagName === 'h2' || tagName === 'h3' || tagName === 'h4';

                    let text = el.textContent.trim()
                        .replace(/<!--[\s\S]*?-->/g, '') // 去除注释
                        .replace(/[•∞@]/g, '')
                        .replace(/\s+/g, ' ')
                        .replace(/&nbsp;/g, ' ')
                        .replace(/<\/?[^>]+>/g, '') // 去除HTML标签
                        .trim();

                    // 再次过滤无效文本
                    if (
                        !text ||
                        text.length <= 1 ||
                        ['@', '•', '∞', 'flex'].includes(text) ||
                        /^\s*$/.test(text) ||
                        /^Advertisement$/i.test(text) ||
                        text.includes("Newsletter Sign-up") ||
                        text.includes("Catch up on the headlines") ||
                        text.includes("News and analysis of the New York City") ||
                        text.includes("Latest news and key analysis") ||
                        text.includes("广告")
                    ) {
                        return '';
                    }

                    // 如果是标题，前后加换行符及【】以区分
                    return isHeader ? `\n【${text}】\n` : text;
                })
                .filter(text => text.length > 0) // 移除空字符串
                .join('\n\n'); // 用双换行符连接段落

            // ... 以下是图片下载逻辑，保持原样或根据需要微调 ...
            // 【2】只有当文本提取成功后，再进行图片下载
            if (textContent) {
                // 查找"Show Conversation"元素
                const showConversationElement = document.querySelector('.css-1nc85ca-Show0rHideCommentsSpan');

                // 【修改】扩展图片查找范围，增加对视差画廊图片的抓取
                let allImages = [
                    // 【新增】抓取视差画廊中的图片
                    ...Array.from(document.querySelectorAll('.pg-element img')),
                    // 【新增】抓取位于 <main> 标签下、<article> 标签外的头图
                    ...Array.from(document.querySelectorAll('main > .bigTop picture img')),
                    // --- 以下为原有选择器，保持不变 ---
                    ...Array.from(document.querySelectorAll('article picture.css-u314cv img')),
                    ...Array.from(document.querySelectorAll('article .origami-item img')),
                    ...Array.from(document.querySelectorAll('article [data-type="inset"] img')),
                    ...Array.from(document.querySelectorAll('article figure img'))
                ];

                // 【新增】对抓取到的图片进行去重
                allImages = [...new Set(allImages)];

                // 【新增】过滤掉 "What to Read Next" 等推荐区域的图片
                allImages = allImages.filter(img => {
                    if (
                        img.closest('[data-testid^="wtrn-block"]') ||
                        img.closest('[aria-label="What to Read Next"]')
                    ) {
                        return false;
                    }
                    return true;
                });

                // 如果找到"Show Conversation"元素，则过滤掉其后的图片
                if (showConversationElement) {
                    allImages = allImages.filter(img => {
                        const position = showConversationElement.compareDocumentPosition(img);
                        return !(position & Node.DOCUMENT_POSITION_FOLLOWING);
                    });
                }

                // 继续进行剩余过滤
                allImages = allImages.filter(img => {
                    const imgSrc = img.src || '';

                    if (imgSrc.toLowerCase().endsWith('.svg') ||
                        imgSrc.includes('/icons/') ||
                        imgSrc.includes('/social') ||
                        imgSrc.includes('/ui/') ||
                        img.closest('button, .share-button, .toolbar')) {
                        return false;
                    }

                    const imgWidth = img.width || img.naturalWidth || 0;
                    const imgHeight = img.height || img.naturalHeight || 0;
                    if (imgWidth > 0 && imgHeight > 0 && (imgWidth < 150 || imgHeight < 150)) {
                        return false;
                    }

                    return true;
                });

                if (allImages.length === 0) {
                    chrome.runtime.sendMessage({ action: 'noImages' });
                } else {
                    const processedUrls = new Set();

                    allImages.forEach(img => {
                        if (img) {
                            let highestResUrl = img.src;

                            if (img.srcset) {
                                const cleanSrcset = img.srcset.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
                                const srcsetEntries = cleanSrcset.split(',').map(entry => {
                                    const [url, width] = entry.trim().split(/\s+/);
                                    const widthNum = parseInt(width?.replace(/[^\d]/g, '') || '0');
                                    return {
                                        url: url.trim(),
                                        width: widthNum
                                    };
                                });

                                const highestResSrc = srcsetEntries.reduce((prev, current) => {
                                    return (current.width > prev.width) ? current : prev;
                                }, srcsetEntries[0]);

                                if (highestResSrc && highestResSrc.url) {
                                    highestResUrl = highestResSrc.url;
                                }
                            }

                            const baseUrl = highestResUrl.split('?')[0];
                            const finalUrl = `${baseUrl}?width=700&size=1.2610340479192939&pixel_ratio=2`;

                            if (!processedUrls.has(baseUrl)) {
                                processedUrls.add(baseUrl);

                                let altText = '';

                                // 【新增】优先从视差画廊的标题提取描述
                                const pgTextWrapper = img.closest('.pg-element')?.querySelector('.pg-media-text');
                                if (pgTextWrapper) {
                                    const pgTitle = pgTextWrapper.querySelector('h4.pg-title');
                                    const pgCaption = pgTextWrapper.querySelector('.pg-image-caption');
                                    if (pgTitle && pgTitle.textContent.trim()) {
                                        altText = pgTitle.textContent.trim();
                                    } else if (pgCaption && pgCaption.textContent.trim()) {
                                        altText = pgCaption.textContent.trim();
                                    }
                                }

                                // 如果视差画廊没有找到描述，使用原有逻辑
                                if (!altText) {
                                    const origamiCaption = img.closest('.origami-wrapper')?.querySelector('.origami-caption');
                                    const figureEl = img.closest('figure');
                                    let captionSpan;
                                    if (figureEl) {
                                        // 【修改】修正了对 figcaption 的查找逻辑，使其更健壮
                                        const figcaptionEl = figureEl.nextElementSibling?.tagName.toLowerCase() === 'figcaption'
                                            ? figureEl.nextElementSibling
                                            : figureEl.querySelector('figcaption');
                                        if (figcaptionEl) {
                                            captionSpan = figcaptionEl.querySelector('.css-426zcb-CaptionSpan');
                                        }
                                    }
                                    const creditSpan = img.closest('[data-type="image"]')?.querySelector('.css-7jz429-Credit');

                                    if (origamiCaption) {
                                        altText = origamiCaption.textContent;
                                    } else if (captionSpan) {
                                        altText = captionSpan.textContent;
                                    } else if (creditSpan) {
                                        altText = creditSpan.textContent;
                                    } else {
                                        altText = img.alt || 'wsj_image';
                                    }
                                }

                                // 为默认文件名添加时间戳
                                if (altText === 'wsj_image') {
                                    const seconds = new Date().getSeconds();
                                    altText = `wsj_image-${seconds}`;
                                }

                                const processFileName = (text) => {
                                    text = text.replace(/[/\\?%*:|"<>+]/g, '-')
                                        .replace(/\s+/g, ' ')
                                        .trim();
                                    if (text.length > 200) {
                                        text = text.substr(0, 196).split(' ').slice(0, -1).join(' ');
                                    }
                                    return `${text}.jpg`;
                                };

                                chrome.runtime.sendMessage({
                                    action: 'downloadImage',
                                    url: finalUrl,
                                    filename: processFileName(altText)
                                });
                            }
                        }
                    });
                }
            }
        }
    }

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