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

    // 处理 bloomberg.com
    else if (window.location.hostname.includes("bloomberg.com")) {
        // 定义主要内容选择器
        const mainSelectors = [
            'p[class*="ArticleBodyText_articleBodyContent"]',
            '.body-content p[class*="media-ui-Paragraph_text"]',
            'p.media-ui-Paragraph_text-SqIsdNjhOtO-',
            'p[class*="media-ui-Paragraph_text"]',
            'p.paywall[data-component="paragraph"]',
            'p[class*="Paragraph"]',
            'p[class*="paragraph"]',
            'main.dvz-content p[class*="copy-width"]',
            'main.dvz-content p.dropcap[class*="svelte-"]',
            'main#dvz__mount div[class*="css--paragraph-wrapper"] > p',
            'li[data-component="unordered-list-item"]',
            'li[class*="media-ui-UnorderedList_item"]',
            // ★★★ 新增：新版 ds-- 结构（photo essay / feature 页面）★★★
            'p[class*="ds--paragraph"]',
            'main.dvz-content p[class*="ds--paragraph"]',
            '#dvz_mount p[class*="ds--paragraph"]'
        ];

        // 需要排除的选择器
        const excludeSelectors = [
            '.UpNext_upNext__C39c6',
            '[data-testid="story-card-small"]',
            '.story-card-small',
            '.styles_moreFromBloomberg_HrR5_',
            '.recirc-box-small-list',
            'div[data-testid="social-share-primary"]',
            'aside'
        ];

        let paragraphs = [];

        // 获取主要内容
        mainSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(element => {
                // 检查是否在被排除的区域内
                const isInExcludedArea = excludeSelectors.some(exSel =>
                    element.closest(exSel) !== null
                );
                // ★★★ 新增：如果段落内嵌了 figure（即图片容器），则跳过
                // 避免把 figcaption 的说明文字当作正文抓下来
                if (element.querySelector('figure')) return;

                if (!isInExcludedArea) {
                    paragraphs.push(element);
                }
            });
        });

        // 提取和清理文本
        textContent = [...new Set(paragraphs)]
            .map(el => {
                let text = el.textContent || '';
                return text
                    .trim()
                    // 移除 HTML 注释
                    .replace(/<!--[\s\S]*?-->/g, '')
                    // 移除特殊符号
                    .replace(/[•∞@]/g, '')
                    // 去掉伪元素标记
                    .replace(/:marker/g, '')
                    // 规范化空白
                    .replace(/\s+/g, ' ')
                    .replace(/&nbsp;/g, ' ')
                    // 移除调试标记，如 "== $0"
                    .replace(/==\s*\$\d+/g, '')
                    // 移除剩余标签
                    // .replace(/<\/?[^>]+(>|$)/g, '')
                    .trim();
            })
            .filter(text => {
                return text
                    && text.length > 10                // 最小长度
                    && !/^[@•∞]/.test(text)            // 不以特殊字符开头
                    && !/^\s*$/.test(text)             // 不全是空白
                    && !['flex', 'Advertisement'].includes(text)
                    && !/^[.\s]*$/.test(text)
                    && !/^Up Next:/.test(text)
                    && !/^You are using an/.test(text)
                    && !/^Read More:/i.test(text);     // ★★★ 新增：过滤掉以 "Read More:" 开头的段落 (加了 'i' 忽略大小写) ★★★
            })
            .join('\n\n');

        // 如果提取到了有效文本，则进行图片下载
        if (textContent) {
            // 查找所有类型的图片容器
            // 新增：同时查找新结构中的 figure 标签，通常带有 svelte-xxxx 类名，且在 main.dvz-content 内
            const figureElements = document.querySelectorAll(
                'figure[data-component="article-image"], ' +
                'main.dvz-content figure[class*="svelte-"], ' +
                'main#dvz__mount figure[class*="css--lede-image-inner-wrapper"], ' +
                'main#dvz__mount section[class*="--root-container"] figure, ' +
                '.body-content figure, ' +
                // ★★★ 新增：新版 ds-- 结构的 figure（photo essay 头图 + 正文图 + 多图网格）★★★
                'figure.ds--figure, ' +
                'main.dvz-content figure.ds--figure, ' +
                '#dvz_mount figure.ds--figure'
            );

            // 检查是否找到了符合条件的图片
            let foundValidImages = false;

            // 用于存储已处理的图片URL
            const processedUrls = new Set();

            if (figureElements && figureElements.length > 0) {
                figureElements.forEach(figure => {
                    let img = null;
                    let caption = '';
                    let highestResUrl = '';
                    let figureType = 'unknown'; // To help debug or adapt logic

                    // Try to identify figure type and extract img/caption accordingly

                    // Type 1: Old structure (data-component="article-image")
                    if (figure.matches('figure[data-component="article-image"]')) {
                        figureType = 'old_structure';
                        img = figure.querySelector('img.ui-image.high-res-img');
                        if (img) {
                            if (img.srcset) {
                                const srcsetEntries = img.srcset.split(',')
                                    .map(entry => {
                                        const parts = entry.trim().split(' ');
                                        const url = parts[0].trim();
                                        const width = parseInt(parts[parts.length - 1]) || 0;
                                        return { url, width };
                                    })
                                    .filter(entry => entry.url && entry.width > 0)
                                    .sort((a, b) => b.width - a.width);
                                if (srcsetEntries.length > 0) highestResUrl = srcsetEntries[0].url;
                            }
                            if (!highestResUrl && img.src) highestResUrl = img.src;

                            const figcaptionElement = figure.querySelector('figcaption');
                            // ★★★ 新增/修改 ② ★★★
                            // 优化了标题提取逻辑。优先查找包含 "Caption_caption" 类名的 `<span>`，
                            // 这样可以精确获取描述文本，避免包含 "Source: ..." 等信息。
                            // 如果找不到，则回退到原来的逻辑，确保兼容旧版页面。
                            if (figcaptionElement) {
                                const specificCaptionSpan = figcaptionElement.querySelector('span[class*="Caption_caption"]');
                                if (specificCaptionSpan) {
                                    caption = specificCaptionSpan.textContent.trim();
                                } else {
                                    // Fallback to original logic
                                    const captionSpans = figcaptionElement.querySelectorAll('span');
                                    if (captionSpans && captionSpans.length > 0) {
                                        caption = Array.from(captionSpans).map(span => span.textContent.trim()).filter(text => text).join(' ');
                                    } else {
                                        caption = figcaptionElement.textContent.trim();
                                    }
                                }
                            }
                        }
                    }
                    // Type 2: Svelte-like structure (main.dvz-content figure[class*="svelte-"])
                    else if (figure.matches('main.dvz-content figure[class*="svelte-"]')) {
                        figureType = 'svelte_structure';
                        img = figure.querySelector('dvz-lede-image-container img');
                        if (!img) img = figure.querySelector('img');

                        if (img && img.src) {
                            highestResUrl = img.src;
                            const figcaptionElement = figure.querySelector('figcaption');
                            if (figcaptionElement) {
                                const specificCaptionSpan = figcaptionElement.querySelector('span.caption');
                                if (specificCaptionSpan) {
                                    caption = specificCaptionSpan.textContent.trim();
                                } else {
                                    const captionSpans = figcaptionElement.querySelectorAll('span');
                                    if (captionSpans && captionSpans.length > 0) {
                                        // 合并所有span的文本内容
                                        caption = Array.from(captionSpans)
                                            .map(span => span.textContent.trim())
                                            .filter(text => text) // 过滤空文本
                                            .join(' ');
                                    } else {
                                        caption = figcaptionElement.textContent.trim();
                                    }
                                }
                            }
                        }
                    }
                    // Type 3: New "css--" structure (e.g., lede image)
                    else if (figure.matches('main#dvz__mount figure[class*="css--lede-image-inner-wrapper"], main#dvz__mount section[class*="--root-container"] figure')) {
                        figureType = 'css_structure';
                        img = figure.querySelector('img.css--lede-image'); // Specific to lede image
                        if (!img) img = figure.querySelector('img'); // More generic fallback within the figure

                        if (img) {
                            const srcsetAttr = img.srcset || img.dataset.srcset; // Prioritize srcset, then data-srcset
                            if (srcsetAttr) {
                                const srcsetEntries = srcsetAttr.split(',')
                                    .map(entry => {
                                        // 提取URL和宽度
                                        const parts = entry.trim().split(' ');
                                        const url = parts[0].trim();
                                        // 从类似 "1200w" 的字符串中提取数字
                                        const width = parseInt(parts[parts.length - 1]) || 0;
                                        return { url, width };
                                    })
                                    .filter(entry => entry.url && entry.width > 0)
                                    .sort((a, b) => b.width - a.width);
                                if (srcsetEntries.length > 0) highestResUrl = srcsetEntries[0].url;
                            }
                            if (!highestResUrl && img.src) highestResUrl = img.src;

                            // Caption for new "css--" structure
                            // The caption might be in div.css--caption-outer-wrapper > figcaption.css--caption-wrapper
                            const captionWrapper = figure.querySelector('div.css--caption-outer-wrapper');
                            let figcaptionElement = null;
                            if (captionWrapper) {
                                figcaptionElement = captionWrapper.querySelector('figcaption.css--caption-wrapper');
                            } else { // If outer wrapper not found, try directly
                                figcaptionElement = figure.querySelector('figcaption.css--caption-wrapper');
                            }

                            if (figcaptionElement) {
                                const creditSpan = figcaptionElement.querySelector('span.css--credit');
                                if (creditSpan) {
                                    caption = creditSpan.textContent.trim();
                                } else { // Fallback if specific span.css--credit is not found
                                    caption = figcaptionElement.textContent.trim();
                                }
                            }
                        }
                    }

                    // Type 4: .body-content 内嵌入的裸 figure（Bloomberg 新版正文图）
                    else if (figure.matches('.body-content figure')) {
                        figureType = 'body_content_figure';
                        img = figure.querySelector('img');
                        if (img) {
                            // 优先使用 srcset 取最高分辨率
                            if (img.srcset) {
                                const srcsetEntries = img.srcset.split(',')
                                    .map(entry => {
                                        const parts = entry.trim().split(' ');
                                        const url = parts[0].trim();
                                        const width = parseInt(parts[parts.length - 1]) || 0;
                                        return { url, width };
                                    })
                                    .filter(entry => entry.url && entry.width > 0)
                                    .sort((a, b) => b.width - a.width);
                                if (srcsetEntries.length > 0) highestResUrl = srcsetEntries[0].url;
                            }
                            if (!highestResUrl && img.src) highestResUrl = img.src;

                            // figcaption 里一般是 <p>文本</p> 结构
                            const figcaptionElement = figure.querySelector('figcaption');
                            if (figcaptionElement) {
                                const captionP = figcaptionElement.querySelector('p');
                                if (captionP) {
                                    caption = captionP.textContent.trim();
                                } else {
                                    caption = figcaptionElement.textContent.trim();
                                }
                                // 去掉 "Source: xxx" / "Photographer: xxx" 这类署名
                                caption = caption
                                    .replace(/\s*Source\s*[:：].*$/i, '')
                                    .replace(/\s*Photograph(?:er)?\s*[:：].*$/i, '')
                                    .trim();
                            }
                        }
                    }

                    // Type 5: 新版 "ds--" 结构（dvz-content / dvz_mount 下的 photo essay & feature article）
                    else if (figure.matches('figure.ds--figure')) {
                        figureType = 'ds_structure';
                        img = figure.querySelector('img.ds--image') || figure.querySelector('img');

                        if (img) {
                            // 优先用 srcset 取最高分辨率
                            if (img.srcset) {
                                const srcsetEntries = img.srcset.split(',')
                                    .map(entry => {
                                        const parts = entry.trim().split(/\s+/);
                                        const url = parts[0].trim();
                                        const width = parseInt(parts[parts.length - 1]) || 0;
                                        return { url, width };
                                    })
                                    .filter(entry => entry.url && entry.width > 0)
                                    .sort((a, b) => b.width - a.width);
                                if (srcsetEntries.length > 0) highestResUrl = srcsetEntries[0].url;
                            }
                            if (!highestResUrl && img.src) highestResUrl = img.src;

                            // figcaption 一般是 <figcaption class="... ds--caption ...">文本</figcaption>
                            const figcaptionElement =
                                figure.querySelector('figcaption.ds--caption') ||
                                figure.querySelector('figcaption[class*="ds--caption"]') ||
                                figure.querySelector('figcaption');

                            if (figcaptionElement) {
                                // 有的版本里把摄影师/来源单独包在 span 里，优先取主描述
                                const captionMain = figcaptionElement.querySelector('span:not([class*="credit"]):not([class*="source"])');
                                if (captionMain && captionMain.textContent.trim()) {
                                    caption = captionMain.textContent.trim();
                                } else {
                                    caption = figcaptionElement.textContent.trim();
                                }
                                // 去掉 "Source: xxx" / "Photographer: xxx" 这类署名
                                caption = caption
                                    .replace(/\s*Source\s*[:：].*$/i, '')
                                    .replace(/\s*Photograph(?:er)?\s*[:：].*$/i, '')
                                    .trim();
                            }

                            // 图集 photo-essay 头图通常没有 figcaption，回退到 alt
                            if (!caption && img.alt) {
                                caption = img.alt.trim();
                            }
                        }
                    }

                    // Common processing for img and caption if found
                    if (img && highestResUrl) {
                        // Clean URL and ensure it's absolute
                        highestResUrl = highestResUrl.replace(/\s+/g, '');
                        if (highestResUrl.startsWith('//')) { // Protocol-relative URL
                            highestResUrl = window.location.protocol + highestResUrl;
                        } else if (highestResUrl.startsWith('/')) { // Origin-relative URL
                            highestResUrl = new URL(highestResUrl, window.location.origin).href;
                        } else if (!highestResUrl.match(/^https?:\/\//i) && !highestResUrl.startsWith('blob:')) {
                            // Potentially a path-relative URL, resolve against document base URI
                            try {
                                highestResUrl = new URL(highestResUrl, window.location.href).href;
                            } catch (e) {
                                console.error('Error creating absolute URL from path-relative:', e, highestResUrl);
                                return; // Skip this image if URL is problematic
                            }
                        }
                        // Absolute URLs (http, https) will pass through correctly with new URL() if base is provided.

                        if (!processedUrls.has(highestResUrl)) {
                            processedUrls.add(highestResUrl);
                            foundValidImages = true;

                            // 改进文件扩展名提取
                            let extension = 'jpg'; // 默认扩展名
                            try {
                                const pathname = new URL(highestResUrl).pathname;
                                const lastDot = pathname.lastIndexOf('.');
                                if (lastDot !== -1 && lastDot < pathname.length - 1) {
                                    const extCandidate = pathname.substring(lastDot + 1).toLowerCase().split('?')[0]; // Remove query params from ext
                                    if (['png', 'jpg', 'jpeg', 'webp', 'svg'].includes(extCandidate)) {
                                        extension = extCandidate;
                                    }
                                }
                            } catch (e) {
                                console.warn('Could not parse URL for extension, defaulting to jpg:', highestResUrl);
                            }


                            let filename;
                            const cleanTextForFilename = (text) => {
                                if (!text) return '';
                                return text
                                    .replace(/&nbsp;/g, ' ')
                                    .replace(/Photograph(?:er)?[\s\S]*$/i, '')
                                    .replace(/\s*(?:Source[-:–—]?)\s*.*$/i, '')
                                    .replace(/[/\\?%*:|"<>+]/g, '-') // Remove invalid chars
                                    .trim();
                            };

                            let cleanedCaption = cleanTextForFilename(caption);
                            let cleanedAlt = cleanTextForFilename(img.alt);

                            if (cleanedCaption) {
                                filename = `${cleanedCaption}.${extension}`;
                            } else if (cleanedAlt) {
                                filename = `${cleanedAlt}.${extension}`;
                            } else {
                                // 如果既没有alt也没有caption，使用时间戳
                                const timestamp = new Date().getTime();
                                filename = `bloomberg-image-${timestamp}.${extension}`;
                            }

                            // Ensure filename is not excessively long
                            const maxLen = 200;
                            if (filename.length > maxLen) {
                                const namePart = filename.substring(0, filename.length - (extension.length + 1));
                                filename = namePart.substring(0, maxLen - (extension.length + 1)) + '.' + extension;
                            }

                            // Ensure filename is not empty before extension
                            if (filename.startsWith('.' + extension)) {
                                filename = `bloomberg-image-${new Date().getTime()}.${extension}`;
                            }


                            chrome.runtime.sendMessage({
                                action: 'downloadImage',
                                url: highestResUrl,
                                filename: filename
                            });
                        }
                    }
                });
            }

            if (!foundValidImages) {
                chrome.runtime.sendMessage({ action: 'noImages' });
            }
        } else {
            chrome.runtime.sendMessage({ action: 'noImages' });
        }
    }

    // 新增：Washington Post 处理
    else if (window.location.hostname.includes("washingtonpost.com")) {
        // ① 先取最可能的文章容器，fallback 到 body
        const container = document.querySelector('article') || document.body;

        // --- 修改开始 ---
        // 1. 提取正文：按优先级尝试多个选择器，以适应不同页面版本
        let paras = [];

        // 尝试选择器 1 (适用于2024年及之后的新版页面)
        paras = Array.from(container.querySelectorAll('p[data-contentid]'));
        if (paras.length > 0) {
        }

        // 如果没找到，尝试选择器 2 (旧版页面)
        if (paras.length === 0) {
            paras = Array.from(container.querySelectorAll('p[data-component="Text"]'));
        }

        // 如果还没找到，尝试选择器 3 (更旧版页面)
        if (paras.length === 0) {
            paras = Array.from(container.querySelectorAll('p[data-apitype="text"]'));
        }
        // --- 修改结束 ---

        textContent = paras
            .map(p => p.textContent.trim())
            .filter(t => t && t.length > 1 && !/^[•@∞]/.test(t))
            .join('\n\n');

        // 2. 提取并下载图片
        if (textContent) {
            // 扩大搜索范围：同时覆盖 <header> 里的 lede 图片和 <article> 里的图片
            // 优先用 .grid-full-inner-standard 作为图片搜索容器（它同时包含 header 和 article）
            const imgContainer =
                document.querySelector('.grid-full-inner-standard') ||
                document.querySelector('main') ||
                document.body;

            // 收集所有 figure：包含文章正文里的，以及 header/topper 里的 lede 图片
            let figures = Array.from(imgContainer.querySelectorAll('figure'));

            // 额外兜底：显式抓取 lede-image（有些页面 figure 会嵌套在不同层级）
            const ledeFig = document.querySelector(
                'figure[data-testid="lede-image"], #topper-lede-art figure, #default-topper figure'
            );
            if (ledeFig && !figures.includes(ledeFig)) {
                figures.unshift(ledeFig); // 头图放第一张
            }

            // 去重
            figures = [...new Set(figures)];

            if (figures.length === 0) {
                chrome.runtime.sendMessage({ action: 'noImages', reason: 'No figure elements found.' });
            } else {
                const processedUrls = new Set();
                const processedFiles = new Set();
                figures.forEach((fig, idx) => {
                    const img = fig.querySelector('img');
                    if (!img) return;

                    // 拿最高分辨率的 URL
                    let bestUrl = img.src;
                    if (img.srcset) {
                        const entries = img.srcset
                            .split(',')
                            .map(s => {
                                const parts = s.trim().split(/\s+/);
                                const url = parts[0];
                                // 处理 "1x", "2x" 或 "300w", "1024w" 等格式
                                let w = 0;
                                if (parts.length > 1) {
                                    const w_str = parts[parts.length - 1];
                                    if (w_str.endsWith('w')) {
                                        w = parseInt(w_str.slice(0, -1), 10) || 0;
                                    } else if (w_str.endsWith('x')) {
                                        // 对于 'x' 描述符，我们可以给一个权重，例如 1x=1, 2x=2
                                        // 但 'w' 描述符通常更精确，优先使用 'w'
                                        // 如果只有 'x'，可以简单地取最后一个 'x' 的值
                                        // 或者，如果混合使用，需要更复杂的逻辑。
                                        // 这里简化处理：如果srcset中主要是 'w'，则 'x' 的权重可能不那么重要
                                        // 如果只有 'x'，则可以按 'x' 的值排序
                                        w = (parseInt(w_str.slice(0, -1), 10) || 0) * 1000; // 给 'x' 一个较大的基数以便排序
                                    }
                                }
                                return { url, w };
                            })
                            .sort((a, b) => b.w - a.w); // 宽度大的优先

                        if (entries[0] && entries[0].url && (entries[0].url.startsWith('http:') || entries[0].url.startsWith('https:'))) {
                            bestUrl = entries[0].url;
                        } else if (entries[0] && entries[0].url) {
                            console.warn(`[WP Parser] srcset URL '${entries[0].url}' might be invalid or not better. Keeping src: '${img.src}'`);
                        }
                    }

                    // 确保URL是绝对路径且协议有效
                    try {
                        // 如果 bestUrl 已经是绝对路径，new URL 会正确处理
                        // 如果 bestUrl 是相对路径，它会相对于 window.location.href 解析
                        const absoluteUrl = new URL(bestUrl, window.location.href);
                        if (!['http:', 'https:'].includes(absoluteUrl.protocol)) {
                            console.warn(`[WP Parser] Skipping image with invalid protocol: ${bestUrl}`);
                            return;
                        }
                        bestUrl = absoluteUrl.href;
                    } catch (e) {
                        console.warn(`[WP Parser] Skipping image due to invalid URL '${bestUrl}':`, e);
                        return;
                    }

                    if (processedUrls.has(bestUrl)) return;
                    processedUrls.add(bestUrl);

                    // caption 或 alt 或时间戳
                    let name = '';
                    const capEl = fig.querySelector('figcaption');
                    if (capEl && capEl.textContent.trim()) {
                        name = capEl.textContent.trim();
                    } else if (img.alt && img.alt.trim()) {
                        name = img.alt.trim();
                    }

                    if (!name || name.toLowerCase() === 'image' || name.toLowerCase() === 'photo' || name.toLowerCase().startsWith('loading')) {
                        name = `wp-image-${Date.now()}-${idx}`;
                    }

                    // 清洗文件名
                    let filename = name
                        .replace(/[/\\?%*:|"<>+]/g, '-')
                        .replace(/\s+/g, '_')
                        .replace(/[^\w.-]/g, '')
                        .trim();

                    const MAX_FILENAME_BASE_LENGTH = 180;
                    if (filename.length > MAX_FILENAME_BASE_LENGTH) {
                        filename = filename.slice(0, MAX_FILENAME_BASE_LENGTH);
                    }
                    filename = filename.replace(/[-._]+$/, '');

                    if (!filename) {
                        filename = `wp-image-${Date.now()}-${idx}`;
                    }
                    filename += '.jpg';


                    if (processedFiles.has(filename)) {
                        const namePart = filename.substring(0, filename.lastIndexOf('.'));
                        const extPart = filename.substring(filename.lastIndexOf('.'));
                        let counter = 1;
                        let newFilenameTry;
                        do {
                            newFilenameTry = `${namePart}_${counter}${extPart}`;
                            counter++;
                        } while (processedFiles.has(newFilenameTry) && counter < 100);
                        filename = newFilenameTry;
                        if (processedFiles.has(filename)) {
                            console.warn(`[WP Parser] Filename conflict for ${name}, could not resolve. Skipping.`);
                            return;
                        }
                    }
                    processedFiles.add(filename);

                    chrome.runtime.sendMessage({
                        action: 'downloadImage',
                        url: bestUrl,
                        filename
                    });
                });
            }
        } else {
            chrome.runtime.sendMessage({ action: 'noImages', reason: 'Text content could not be extracted with any of the available selectors.' });
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