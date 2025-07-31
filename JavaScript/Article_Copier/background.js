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

  // 处理 bloomberg.com
  else if (window.location.hostname.includes("bloomberg.com")) {
    // 定义主要内容选择器
    const mainSelectors = [
      '.body-content p[class*="media-ui-Paragraph_text"]',
      'p.media-ui-Paragraph_text-SqIsdNjhOtO-',
      'p[class*="media-ui-Paragraph_text"]',
      'p.paywall[data-component="paragraph"]',
      // 更通用的选择器，用于捕获可能的段落
      'p[class*="Paragraph"]',
      'p[class*="paragraph"]',
      // Svelte-like 结构
      'main.dvz-content p[class*="copy-width"]',
      'main.dvz-content p.dropcap[class*="svelte-"]',
      // 针对新 "css--" 命名结构
      'main#dvz__mount div[class*="css--paragraph-wrapper"] > p',
      // ---- 新增：捕获列表项 ---- //
      'li[data-component="unordered-list-item"]',
      'li[class*="media-ui-UnorderedList_item"]'
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
          && !/^You are using an/.test(text);
      })
      .join('\n\n');

    // 如果提取到了有效文本，则进行图片下载
    if (textContent) {
      // 查找所有类型的图片容器
      // 新增：同时查找新结构中的 figure 标签，通常带有 svelte-xxxx 类名，且在 main.dvz-content 内
      const figureElements = document.querySelectorAll(
        // Old structure
        'figure[data-component="article-image"], ' +
        // Svelte-like structure
        'main.dvz-content figure[class*="svelte-"], ' +
        // New "css--" lede image structure
        'main#dvz__mount figure[class*="css--lede-image-inner-wrapper"], ' +
        // Fallback for other potential figures in new "css--" structure (more generic)
        'main#dvz__mount section[class*="--root-container"] figure'
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
              if (figcaptionElement) {
                const captionSpans = figcaptionElement.querySelectorAll('span');
                if (captionSpans && captionSpans.length > 0) {
                  caption = Array.from(captionSpans).map(span => span.textContent.trim()).filter(text => text).join(' ');
                } else {
                  caption = figcaptionElement.textContent.trim();
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
                  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(extCandidate)) {
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

  // 处理 wsj.com
  else if (window.location.hostname.includes("wsj.com")) {
    const article = document.querySelector('article');

    if (article) {
      // 【1】先提取文本，而不进行图片下载
      const possibleSelectors = [
        'p[class*="emoc1hq1"][class*="css-1jdwmf4-StyledNewsKitParagraph"][font-size="17"]',
        'p[class*="css-k3zb61-Paragraph"]',
        'p[data-type="paragraph"]',
        '.paywall p[data-type="paragraph"]',
        'article p[data-type="paragraph"]',
        'p[class*="Paragraph"]',
        '.paywall p'
      ];

      let allParagraphs = [];
      possibleSelectors.forEach(selector => {
        const paragraphs = article.querySelectorAll(selector);
        allParagraphs = [...allParagraphs, ...Array.from(paragraphs)];
      });

      // 去重后生成最终文本内容
      allParagraphs = [...new Set(allParagraphs)];

      textContent = allParagraphs
        .map(p => {
          if (
            p.querySelector('strong[data-type="emphasis"]') ||
            p.className.includes('g-pstyle') ||
            p.closest('.ai2html_export') ||
            p.closest('[data-block="dynamic-inset"]')
          ) {
            return '';
          }

          let text = p.textContent.trim()
            .replace(/<!--[\s\S]*?-->/g, '')
            .replace(/[•∞@]/g, '')
            .replace(/\s+/g, ' ')
            .replace(/&nbsp;/g, ' ')
            // .replace(/≤\/p>/g, '')
            .replace(/<\/?[^>]+>/g, '')
            // .replace(/[.*?]/g, '')
            .trim();

          return text;
        })
        .filter(text => {
          return text &&
            text.length > 1 &&
            !['@', '•', '∞', 'flex'].includes(text) &&
            !/^\s*$/.test(text) &&
            !/^Advertisement$/i.test(text) &&
            !/^.$/.test(text) &&
            !text.includes("Newsletter Sign-up") &&
            !text.includes("Catch up on the headlines, understand the news and make better decisions, free in your inbox daily. Enjoy a free article in every edition.") &&
            !text.includes("News and analysis of the New York City mayor's case") &&
            !text.includes("Latest news and key analysis, selected by editors") &&
            !text.includes("广告");
        })
        .join('\n\n');

      // 【2】只有当文本提取成功后，再进行图片下载
      if (textContent) {
        // 查找"Show Conversation"元素
        const showConversationElement = document.querySelector('.css-1nc85ca-Show0rHideCommentsSpan');

        // 扩展图片查找范围
        let allImages = [
          ...Array.from(article.querySelectorAll('picture.css-u314cv img')), // 原有的选择器
          ...Array.from(article.querySelectorAll('.origami-item img')), // 新增：origami布局中的图片
          ...Array.from(article.querySelectorAll('[data-type="inset"] img')), // 新增：inset中的图片
          ...Array.from(article.querySelectorAll('figure img')) // 新增：figure中的图片
        ];

        // --- 新增过滤逻辑 ---
        // 过滤掉 "What to Read Next" 等推荐区域的图片
        // 这个步骤应该在其他过滤（如评论区过滤、尺寸过滤）之前进行，以提高效率
        allImages = allImages.filter(img => {
          // 检查图片的祖先元素中是否包含特定排除区域的标志
          // data-testid 属性以 "wtrn-block" 开头，例如 "wtrn-block-0"
          // aria-label 属性为 "What to Read Next"
          if (
            img.closest('[data-testid^="wtrn-block"]') ||
            img.closest('[aria-label="What to Read Next"]')
          ) {
            return false; // 如果图片在这些区域内，则排除该图片
          }
          return true; // 否则，保留该图片
        });
        // --- 新增过滤逻辑结束 ---

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
                const origamiCaption = img.closest('.origami-wrapper')?.querySelector('.origami-caption');
                const figureEl = img.closest('figure');
                let captionSpan;
                if (figureEl) {
                  const figcaptionEl = figureEl.nextElementSibling;
                  if (figcaptionEl && figcaptionEl.tagName.toLowerCase() === 'figcaption') {
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

                // --- 新增逻辑：为默认文件名添加时间戳 ---
                if (altText === 'wsj_image') {
                  const seconds = new Date().getSeconds(); // 获取当前秒数 (0-59)
                  altText = `wsj_image-${seconds}`; // 拼接成新名称，如 "wsj_image-46"
                }
                // --- 新增逻辑结束 ---

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

  // 处理 economist.com
  else if (window.location.hostname.includes("economist.com")) {
    // 首先尝试获取原有的文章结构
    let article = document.querySelector('[data-test-id="Article"]');
    let paragraphs;

    if (article) {
      // 原有网页结构的处理
      paragraphs = article.querySelectorAll('p[data-component="paragraph"]');
    } else {
      // 新网页结构的处理 - 修改这部分以匹配新结构
      article = document.querySelector('.article-text') || document.body; // 如果找不到.article-text则使用body
      if (article) {
        paragraphs = document.querySelectorAll('.article-text body-text, body-text.svelte-16dgy1v');
      }
    }

    if (paragraphs && paragraphs.length > 0) {
      textContent = Array.from(paragraphs)
        .map(p => {
          // 递归获取所有文本内容的函数
          function getAllText(node) {
            let text = '';

            // 处理所有子节点
            Array.from(node.childNodes).forEach(child => {
              if (child.nodeType === Node.TEXT_NODE) {
                text += child.textContent;
              } else if (child.nodeType === Node.ELEMENT_NODE) {
                // 特殊处理大写字母开头
                if (child.tagName === 'SPAN' && child.getAttribute('data-caps') === 'initial') {
                  text += child.textContent;
                }
                // 处理 small 标签，保持大写
                else if (child.tagName === 'SMALL') {
                  text += child.textContent;
                }
                // 处理斜体
                else if (child.tagName === 'I') {
                  text += child.textContent;
                }
                // 处理链接和其他元素
                else if (child.tagName === 'A' || child.children.length > 0) {
                  text += getAllText(child);
                }
                else {
                  text += child.textContent;
                }
              }
            });
            return text;
          }

          // 获取并清理文本
          let text = getAllText(p)
            .replace(/\s+/g, ' ') // 规范化空白
            .replace(/[•∞@]/g, '') // 移除特殊字符
            .replace(/&nbsp;/g, ' ') // 处理HTML空格
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

      // 如果成功提取到文本，则处理图片下载
      if (textContent) {
        // 查找所有图片，但排除特定区域的图片
        const figures = Array.from(article.querySelectorAll('figure.css-3mn275'))
          .filter(figure => {
            // 检查父元素，排除相关文章区域的图片
            return !figure.closest('[data-optimizely="onward-articles-component"]') && // 排除相关文章组件
              !figure.closest('[data-optimizely="related-articles-section"]') && // 排除相关文章区域
              !figure.closest('[data-tracking-id="content-well-chapter-list"]') && // 排除章节列表
              !figure.closest('.css-1qaigru') && // 排除水平布局区域
              !figure.closest('.css-12lyffs') && // 排除推荐文章卡片
              !figure.closest('.css-1xfkcl4'); // 排除onward-articles区域
          });

        if (figures.length === 0) {
          chrome.runtime.sendMessage({
            action: 'noImages'
          });
        } else {
          figures.forEach(figure => {
            const img = figure.querySelector('img');
            if (img) {
              // 检查图片格式
              let fileExtension = 'jpg';
              const srcUrl = img.src || '';
              if (srcUrl.includes('format=auto')) {
                // 从原始URL中提取实际文件扩展名
                const originalPath = srcUrl.split('/').pop().split('_')[1];
                if (originalPath) {
                  const match = originalPath.match(/\.(jpg|jpeg|png|gif|webp)$/i);
                  if (match) {
                    fileExtension = match[1].toLowerCase();
                  }
                }
              }

              // 构建最高质量的图片URL
              // 移除现有的width参数，使用1424作为最大宽度
              const baseUrl = srcUrl.split('/content-assets/')[0] + '/content-assets/';
              const imagePath = srcUrl.split('/content-assets/')[1].split('?')[0];
              const highResUrl = `${baseUrl}${imagePath}?width=1424&quality=80&format=auto`;

              // 优先获取figcaption中的span标签内容作为描述
              let imageDescription = '';
              const figcaptionSpan = figure.querySelector('figcaption span.css-1st60ou');
              if (figcaptionSpan && figcaptionSpan.textContent.trim()) {
                imageDescription = figcaptionSpan.textContent.trim();
              } else if (img.alt && img.alt.trim()) {
                imageDescription = img.alt.trim();
              }

              // 生成文件名
              let filename;
              const now = new Date();
              const timestamp = `${now.getHours()}${now.getMinutes()}${now.getSeconds()}`;

              if (imageDescription) {
                // 使用图片描述作为文件名,替换非法字符,并加上时间戳
                filename = `${imageDescription.replace(/[/\\?%*:|"<>+]/g, '-')}.${fileExtension}`;

                // 【新增逻辑】检查文件名是否以特定前缀开头，如果是，则添加秒数时间戳
                if (filename.startsWith('Photograph- ') || filename.startsWith('Chart- ')) {
                  const seconds = now.getSeconds();
                  const namePart = filename.substring(0, filename.lastIndexOf('.'));
                  const extensionPart = filename.substring(filename.lastIndexOf('.'));
                  filename = `${namePart}-${seconds}${extensionPart}`;
                }

              } else {
                // 如果没有描述,使用image加时间戳
                filename = `economist-image-${timestamp}.${fileExtension}`;
              }

              // 确保文件名不会太长
              if (filename.length > 200) {
                filename = filename.substring(0, 196) + '.' + fileExtension;
              }

              // 发送下载消息到background script
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

  // 处理 technologyreview.com
  else if (window.location.hostname.includes("technologyreview.com")) {

    // 更新 Technology Review 的内容提取逻辑
    const contentBody = document.querySelector('#content--body');

    if (contentBody) {
      // 尝试多个可能的选择器
      let paragraphs = [];

      // 选择器列表
      const selectors = [
        // 新的选择器
        'div[class*="gutenbergContent"] p',
        '.html_0 p, .html_2 p, .html_8 p',
        '.contentBody_content--42a60b56e419a26d9c3638a9dab52f55 p',
        // 备用选择器
        '#content--body p',
        'article p',
        '.contentBody_wrapper p'
      ];

      // 依次尝试每个选择器
      for (const selector of selectors) {
        const elements = contentBody.querySelectorAll(selector);
        if (elements && elements.length > 0) {
          paragraphs = elements;
          break;
        }
      }

      // 如果还是没找到，使用最基础的选择器
      if (!paragraphs.length) {
        paragraphs = contentBody.getElementsByTagName('p');
      }

      textContent = Array.from(paragraphs)
        .map(p => {
          let text = p.textContent.trim();

          // 增强的文本清理
          text = text
            .replace(/\s+/g, ' ') // 规范化空白
            .replace(/[\u200B-\u200D\uFEFF]/g, '') // 移除零宽字符
            .replace(/&nbsp;/g, ' ') // 处理HTML空格
            .replace(/<!--[\s\S]*?-->/g, '') // 移除HTML注释
            // .replace(/\[.*?\]/g, '') // 移除方括号内容
            .trim();

          return text;
        })
        .filter(text => {
          // 增强的过滤条件
          const invalidTexts = [
            'flex',
            'Skip to Content',
            'You need to enable JavaScript',
            '@',
            '•',
            '∞',
            '.',
            'Advertisement'
          ];

          return text &&
            text.length > 10 && // 增加最小长度要求
            !invalidTexts.includes(text) &&
            !/^\s*$/.test(text) &&
            !/^Update:/.test(text) &&
            !/^Related Story/.test(text) &&
            !/^[\.•@∞]+$/.test(text);
        })
        .join('\n\n');

      if (textContent) {
        // 简化图片查找逻辑
        const images = contentBody.querySelectorAll('img');

        if (images.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
          images.forEach(img => {
            // 直接使用src属性
            const imgUrl = img.src;

            if (imgUrl && !imgUrl.includes('data:image')) { // 排除base64图片
              // 生成文件名
              let filename;
              if (img.alt && img.alt.trim()) {
                filename = `${img.alt.replace(/[/\\?%*:|"<>+]/g, '-')}`;
              } else {
                const timestamp = new Date().getTime();
                filename = `technologyreview-image-${timestamp}`;
              }

              // 确保文件名不会太长且以.jpg结尾
              if (filename.length > 90) {
                filename = filename.substring(0, 90);
              }
              if (!filename.toLowerCase().endsWith('.jpg')) {
                filename += '.jpg';
              }

              chrome.runtime.sendMessage({
                action: 'downloadImage',
                url: imgUrl,
                filename: filename
              });
            }
          });
        }
      }
    }
  }

  // 处理 reuters.com
  else if (window.location.hostname.includes("reuters.com")) {
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

            // 如果上述未找到，尝试原始代码中的逻辑 (可能针对特定但不太标准的结构)
            // 但要注意 img.closest('[data-testid="primary-image"]') 的用法
            // primary-image 通常是图片容器，其父元素未必是标题的直接容器
            if (!caption) {
              const primaryImageDiv = img.closest('[data-testid="primary-image"]');
              const figForPrimary = primaryImageDiv ? primaryImageDiv.closest('figure') : null; // primary-image 可能在 figure 内
              const actualFig = figForPrimary || img.closest('figure'); // 回退到任意 figure

              if (actualFig) {
                // 尝试从 actualFig 的父元素或兄弟元素找 span (如原始逻辑，但要小心)
                // 或者更可能是 actualFig 的子元素 (如 figcaption)
                const spanInParent = actualFig.parentElement ? actualFig.parentElement.querySelector('span') : null;
                // 这里需要更精确的判断，这个 span 是否真的是标题
                // 这是一个非常脆弱的选择器，除非 DOM 结构非常固定且已知
                // if (spanInParent && spanInParent.textContent.length > 10 && !spanInParent.querySelector('a, button')) { // 粗略判断
                //    caption = spanInParent.textContent;
                // }
                // 更安全的还是依赖 figcaption 或 alt
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

            const extMatch = url.match(/\.(png|jpe?g|gif|webp)(\?|$)/i);
            const ext = extMatch ? extMatch[1] : 'jpg';

            let filename = caption
              ? caption.replace(/[/\\?%*:|"<>+]/g, '-').substring(0, 180) // 缩短一点以防路径过长
              : `reuters-image-${Date.now()}-${idx}`;
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
      // 2.1 抓文字描述（SingleImageHero 顶部描述）
      let textContent = '';
      const heroDesc = document.querySelector(
        'div[data-testid="SingleImageHeroSubSection"] p[data-testid="Body"]'
      );
      if (heroDesc) {
        textContent = heroDesc.textContent.trim();
        // 如果你要把文字传给 background，再发一条消息
        chrome.runtime.sendMessage({ action: 'sendText', text: textContent });
      }

      // 2.2 抓所有图片
      const processedUrls = new Set();
      // 选出 hero 图 和 event-gallery 图集里的 <img>
      const images = Array.from(
        document.querySelectorAll(
          'div[data-testid="SingleImageHero"] img, ' +
          'div[data-testid="EventGalleryImageImage"] img'
        )
      );

      images.forEach((img, idx) => {
        // —— 复用你原来的 URL 提取逻辑 —————————————————————
        let url = '';
        if (img.src && !img.src.startsWith('data:image/') && img.src !== window.location.href) {
          url = img.src;
        }
        if ((!url || url.startsWith('data:image/')) && img.dataset.src) {
          url = img.dataset.src;
        }
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
        if (url.startsWith('/')) {
          try { url = new URL(url, location.origin).href; }
          catch (e) { url = ''; }
        }
        url = url.replace(/\s+/g, '');

        if (!url || url.startsWith('data:image/') || url === location.href) {
          return;
        }
        if (processedUrls.has(url)) {
          return;
        }
        processedUrls.add(url);

        // ---- 针对图集页面的 Caption 提取 ------------------------------------------
        let caption = '';
        // 先找 figcaption 里的 span
        const fig = img.closest('figure');
        if (fig) {
          const span = fig.querySelector('figcaption span, [data-testid="ImageCaption"] span');
          if (span) caption = span.textContent.trim();
        }
        // 再 fallback 用 alt
        if (!caption && img.alt) caption = img.alt.trim();

        // 清洗 caption
        caption = caption.replace(/REUTERS\/.*/i, '')
          .replace(/^["“]+|["”]+$/g, '')
          .trim();

        // 构造文件名
        const extMatch = url.match(/\.(png|jpe?g|gif|webp)(\?|$)/i);
        const ext = extMatch ? extMatch[1] : 'jpg';
        let filename = caption
          ? caption.replace(/[/\\?%*:|"<>+]/g, '-').slice(0, 180)
          : `reuters-pic-${Date.now()}-${idx}`;
        filename += '.' + ext;

        chrome.runtime.sendMessage({
          action: 'downloadImage',
          url,
          filename
        });
      });
    }
    else {
      // 如果未找到 articleBody 或 article
      chrome.runtime.sendMessage({ action: 'noImages' });
    }
  }

  // 处理 nytimes.com
  else if (window.location.hostname.includes("nytimes.com")) {
    // ---- 去掉 paywall overlay ----  
    const gate = document.querySelector('[data-testid="vi-gateway-container"]');
    if (gate) gate.style.display = 'none';

    // 找到文章主节点
    const article = document.querySelector('main#site-content article, article#story');
    if (!article) {
      chrome.runtime.sendMessage({ action: 'noImages' });
      return;
    }

    // ---- 等待正文段落载入 ----  
    const waitFor = (selector, timeout = 2000) => {
      return new Promise(resolve => {
        const start = Date.now();
        (function check() {
          if (document.querySelector(selector) || Date.now() - start > timeout) {
            return resolve();
          }
          requestAnimationFrame(check);
        })();
      });
    };
    waitFor('section[name="articleBody"] p.css-at9mcl');

    // ---- 提取正文 ----  
    const bodySection = article.querySelector('section[name="articleBody"]');
    if (!bodySection) {
      chrome.runtime.sendMessage({ action: 'noImages' });
      return;
    }
    // 把两栏都选进来
    const paras = Array.from(
      bodySection.querySelectorAll([
        'p.css-at9mcl',
        'p.css-at9mc1',
        'div.StoryBodyCompanionColumn p',
        'h2',
        'p[data-testid="drop-cap-letter"] + p'
      ].join(','))
    );
    textContent = paras
      .map(p => p.textContent.trim().replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' '))
      .filter(t =>
        t.length > 1 &&
        !/^[@•∞]/.test(t) &&
        !/^[\s\W]*$/.test(t) &&
        t !== "Editors’ Picks"
      )
      .join('\n\n');

    // ---- 只有正文抓到才处理图片 ----  
    if (textContent) {
      // 原始图片块 selector
      const rawBlocks = Array.from(
        article.querySelectorAll(
          '[data-testid^="ImageBlock"], [data-testid="imageblock-wrapper"], figure'
        )
      );
      // 过滤掉 recirculation / bottom-sheet-sensor 区域内的 block
      const imageBlocks = rawBlocks.filter(block =>
        !block.closest('[data-testid="recirculation"], #bottom-sheet-sensor')
      );

      if (imageBlocks.length === 0) {
        chrome.runtime.sendMessage({ action: 'noImages' });
      } else {
        const seenUrls = new Set();
        const seenNames = new Set();
        imageBlocks.forEach((block, i) => {
          // 找到 img
          const img = block.querySelector('picture img, img');
          if (!img) return;
          // 最高分辨率 URL
          let url = img.srcset
            ? img.srcset.trim().split(',').map(s => s.trim().split(' ')[0]).pop()
            : img.src;
          if (!url || seenUrls.has(url)) return;
          seenUrls.add(url);
          // 取 caption
          let cap = block.querySelector('figcaption span')?.textContent
            || img.alt
            || `nytimes-${Date.now()}-${i}`;
          cap = cap.replace(/[/\\?%*:|"<>+]/g, '-').slice(0, 180).trim();
          let filename = `${cap}.jpg`;
          // 防重名
          let k = 1;
          while (seenNames.has(filename)) {
            filename = `${cap}(${k++}).jpg`;
          }
          seenNames.add(filename);
          chrome.runtime.sendMessage({ action: 'downloadImage', url, filename });
        });
      }

      // ---- 复制正文 并返回 true ----  
      const ta = document.createElement('textarea');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      ta.value = textContent;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      return true;
    } else {
      chrome.runtime.sendMessage({ action: 'noImages' });
      return false;
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

    // 2. 提取并下载图片 (后续逻辑保持不变, 因为现在 textContent 能被正确获取)
    if (textContent) {
      // 找到所有 figure
      const figures = Array.from(container.querySelectorAll('figure'));
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

  // ★★★★★ START: MODIFIED NIKKEI ASIA LOGIC ★★★★★
  // 新增：Nikkei Asia 处理 (支持两种页面结构)
  else if (window.location.hostname.includes("asia.nikkei.com")) {
    // 检查是否存在新的 "Shorthand" 页面结构
    const shorthandArticle = document.querySelector('article.Theme-Story');

    if (shorthandArticle) {
      // 1. 提取正文
      // 选择 article 内的所有 p 标签，但排除 figure (及其子元素) 内的 p 标签
      const paras = Array.from(shorthandArticle.querySelectorAll('p'))
        .filter(p => !p.closest('figure')) // 排除图片容器内的 p 标签
        .map(p => p.textContent.trim())
        .filter(t =>
          t.length > 0 && // 规则1：保留非空段落
          !t.includes("Reporters and videographers:") && // 规则2：排除记者名单
          !t.includes("Editors:") && // 规则3：排除编辑名单
          !t.startsWith("Note: Occupations and ages") // 规则4：排除结尾注释
        );
      textContent = paras.join('\n\n');


      // 2. 提取图片及描述
      if (textContent) {
        imagesFoundForDownload = true;
        // 选择所有图片所在的 figure 容器
        const imageFigures = Array.from(shorthandArticle.querySelectorAll('figure.InlineMedia--image'));
        if (imageFigures.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
          const seenUrls = new Set();
          imageFigures.forEach((figure, idx) => {
            const img = figure.querySelector('img');
            const sources = figure.querySelectorAll('source');
            if (!img) return;

            let bestUrl = '';
            let maxWidth = 0;

            // 从 source 的 srcset 中解析最高分辨率的图片
            sources.forEach(source => {
              const srcset = source.srcset;
              if (srcset) {
                const candidates = srcset.split(',').map(entry => {
                  const parts = entry.trim().split(/\s+/);
                  return {
                    url: parts[0],
                    width: parseInt(parts[1]?.replace('w', ''), 10) || 0
                  };
                });
                const bestCandidate = candidates.sort((a, b) => b.width - a.width)[0];
                if (bestCandidate && bestCandidate.width > maxWidth) {
                  maxWidth = bestCandidate.width;
                  bestUrl = bestCandidate.url;
                }
              }
            });

            // 如果 srcset 中没找到，回退到 img 的 src
            if (!bestUrl) {
              bestUrl = img.src;
            }

            bestUrl = bestUrl.trim();
            if (!bestUrl || seenUrls.has(bestUrl) || !bestUrl.startsWith('http')) return;
            seenUrls.add(bestUrl);

            // 提取图片描述
            let captionText = '';
            const figcaption = figure.querySelector('figcaption.Theme-Caption');
            if (figcaption) {
              captionText = figcaption.textContent.trim();
            }

            // 构造文件名
            let baseName = captionText || img.alt.trim() || `nikkei-shorthand-${Date.now()}-${idx}`;
            baseName = baseName
              .replace(/\(Photo by [^)]+\)/ig, '') // 移除 "(Photo by...)"
              .replace(/[/\\?%*:|"<>+]/g, '-')
              .replace(/\s+/g, ' ')
              .substring(0, 180)
              .trim();
            const filename = (baseName || `image-${Date.now()}-${idx}`) + '.jpg';

            chrome.runtime.sendMessage({
              action: 'downloadImage',
              url: bestUrl,
              filename
            });
          });
        }
      } else {
        chrome.runtime.sendMessage({ action: 'noImages' });
      }
    } else {
      // --- 原有页面结构的处理逻辑 (作为后备) ---
      const bodyContainer = document.querySelector('[data-trackable="bodytext"]');
      if (bodyContainer) {
        const paras = Array.from(bodyContainer.querySelectorAll('p'))
          .map(p => p.textContent.trim())
          .filter(t => t.length > 0);
        textContent = paras.join('\n\n');
      }

      if (textContent) {
        imagesFoundForDownload = true;
        const imageBlocks = Array.from(
          document.querySelectorAll(
            'div[data-trackable="image-main"], div[data-trackable="image-inline"]'
          )
        );
        if (imageBlocks.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
          const seenUrls = new Set();
          imageBlocks.forEach((block, idx) => {
            const img = block.querySelector('img');
            if (!img) return;

            let url = img.getAttribute('full') || img.src || '';
            url = url.trim();
            if (!url) return;

            if (url.startsWith('//')) url = location.protocol + url;
            else if (url.startsWith('/')) url = new URL(url, location.origin).href;

            if (seenUrls.has(url)) return;
            seenUrls.add(url);

            let captionText = '';
            const cap =
              block.querySelector('[data-trackable="caption"], .article_caption') ||
              block.parentElement.querySelector('[data-trackable="caption"], .article_caption');
            if (cap) {
              captionText = cap.textContent
                .replace(/[\r\n]+/g, ' ')
                .replace(/["“”]/g, '')
                .trim();
            }

            let baseName = captionText || img.alt.trim() || `img-${Date.now()}-${idx}`;
            baseName = baseName
              .replace(/[/\\?%*:|"<>+]/g, '-')
              .replace(/\s+/g, ' ')
              .substring(0, 180)
              .trim();
            const filename = (baseName || `image-${Date.now()}-${idx}`) + '.jpg';

            chrome.runtime.sendMessage({
              action: 'downloadImage',
              url,
              filename
            });
          });
        }
      } else {
        chrome.runtime.sendMessage({ action: 'noImages' });
      }
    }
  }
  // ★★★★★ END: MODIFIED NIKKEI ASIA LOGIC ★★★★★

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