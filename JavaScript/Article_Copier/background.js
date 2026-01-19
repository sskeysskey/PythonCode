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
    tab.url.includes("rfi.fr")
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
      // ★★★ 新增/修改 ① ★★★
      // 优先匹配你提供的新版 "feature_article" 页面的正文段落。
      // 这个选择器通过模糊匹配类名来确保稳定性。
      'p[class*="ArticleBodyText_articleBodyContent"]',
      // --- 以下为原有选择器，保持不变 ---
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

  // ==========================================
  // 2. 【新增】DW (德国之声) 处理逻辑
  // ==========================================
  else if (window.location.hostname.includes("dw.com")) {
    // DW 的内容通常在 article 标签内
    const contentRoot = document.querySelector('article') || document.querySelector('#main-content') || document;

    if (contentRoot) {
      // 1. 提取文本
      // DW 的正文和标题通常在 data-tracking-name="rich-text" 的 div 下
      const textSelectors = [
        'div[data-tracking-name="rich-text"] h2',
        'div[data-tracking-name="rich-text"] h3',
        'div[data-tracking-name="rich-text"] p'
      ];

      const allElements = contentRoot.querySelectorAll(textSelectors.join(','));
      let uniqueElements = [...new Set(allElements)];

      textContent = uniqueElements
        .map(el => {
          // 1. 过滤视频容器
          if (el.closest('.vjs-wrapper')) return '';
          if (el.textContent.includes("To view this video please enable JavaScript")) return '';

          const tagName = el.tagName.toLowerCase();

          // 2. 基础文本清理
          let text = el.textContent.trim()
            .replace(/\s+/g, ' ')
            .replace(/&nbsp;/g, ' ')
            .trim();

          // ★★★ 修改点：精准过滤包含“长平观察：”的整段内容 ★★★
          if (text.includes("长平观察：")) {
            return '';
          }

          // 3. ★★★ 新增：过滤社交媒体推广和版权声明 ★★★
          if (
            text.includes("DW中文有Instagram") ||
            text.includes("摘编自其他媒体") ||
            text.includes("dw.chinese") ||
            text.includes("德国之声版权声明") ||
            text.startsWith("© 20") // 匹配 © 2026年...
          ) {
            return '';
          }

          // 4. 过滤无效字符
          if (!text || text.length <= 1 || ['@', '•', '∞'].includes(text)) {
            return '';
          }

          // 5. 标题格式化
          if (tagName === 'h2' || tagName === 'h3') {
            return `\n【${text}】\n`;
          }
          return text;
        })
        .filter(text => text.length > 0)
        .join('\n\n');


      // 2. 提取并下载图片
      if (textContent) {
        // DW 的图片通常在 figure 标签内
        let allImages = [...document.querySelectorAll('article figure img')];

        // 去重
        allImages = [...new Set(allImages)];

        // ★★★ 关键修改：过滤掉低清占位图 (lq-img) ★★★
        // DW 页面中一个 figure 里通常有两个 img，一个是 lq-img (placeholder)，一个是 hq-img (real)
        // 如果不过滤，会导致重复下载，且 lq-img 可能会导致文件名冲突或下载为 HTML
        allImages = allImages.filter(img => !img.classList.contains('lq-img'));

        if (allImages.length === 0) {
          chrome.runtime.sendMessage({
            action: 'noImages'
          });
        } else {
          const processedUrls = new Set();
          allImages.forEach(img => {
            if (img) {
              // 查找高清图 URL (复用 WSJ 的 srcset 解析逻辑)
              let highestResUrl = img.src;
              if (img.srcset) {
                const cleanSrcset = img.srcset.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
                const srcsetEntries = cleanSrcset.split(',').map(entry => {
                  // DW 的 srcset 格式通常是 "url width_descriptor"
                  const parts = entry.trim().split(/\s+/);
                  // 取最后一部分作为宽度，去掉 'w'
                  const widthStr = parts[parts.length - 1];
                  const url = parts[0];
                  const widthNum = parseInt(widthStr?.replace(/[^0-9]/g, '') || '0');
                  return {
                    url: url,
                    width: widthNum
                  };
                });

                // 找到宽度最大的图片
                const highestResSrc = srcsetEntries.reduce((prev, current) => {
                  return (current.width > prev.width) ? current : prev;
                }, srcsetEntries[0]);
                if (highestResSrc && highestResSrc.url) {
                  highestResUrl = highestResSrc.url;
                }
              }

              // 清理 URL
              const finalUrl = highestResUrl.split('?')[0];

              if (!processedUrls.has(finalUrl)) {
                processedUrls.add(finalUrl);

                // 提取图片描述
                let altText = '';
                const figure = img.closest('figure');
                if (figure) {
                  const figcaption = figure.querySelector('figcaption');
                  if (figcaption) {
                    // 移除版权信息等杂质
                    const clone = figcaption.cloneNode(true);
                    const smalls = clone.querySelectorAll('small, .copyright');
                    smalls.forEach(s => s.remove());
                    altText = clone.textContent.trim();
                  }
                }
                // 兜底描述
                if (!altText) altText = img.title || img.alt || 'dw_image';

                // ★★★ 关键修改：增强文件名清理逻辑 ★★★
                const processFileName = (text) => {
                  text = text
                    // 1. 移除中文引号和句号，防止文件名出现 ".." 或 ".html" 混淆
                    .replace(/[“”。，,]/g, '')
                    // 2. 移除系统非法字符
                    .replace(/[\\/?%*:|"<>+]/g, '-')
                    .replace(/\s+/g, ' ')
                    .trim();
                  if (text.length > 100) {
                    text = text.substr(0, 96) + '...';
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

  // --- 修复版：处理 rfi.fr ---
  else if (window.location.hostname.includes("rfi.fr")) {
    const article = document.querySelector('article') || document.getElementById('main-content');

    if (article) {
      // 1. 提取正文
      // 修复点1：兼容 .t-content_body (单下划线) 和 .t-content__body (双下划线)
      const bodyContainer = article.querySelector('.t-content__body, .t-content_body');

      if (bodyContainer) {
        // 修复点2：改用 childNodes 遍历。
        // 因为你的源码显示有 "＜p>" 这种奇怪的标签，还有直接裸露在 div 里的文本。
        // querySelectorAll('p') 抓不到它们，遍历节点最稳妥。
        textContent = Array.from(bodyContainer.childNodes)
          .map(node => {
            // 排除广告容器 (通过类名判断)
            if (node.nodeType === Node.ELEMENT_NODE) {
              // 1. 排除广告和推广容器
              if (node.closest && (node.closest('.o-self-promo') || node.closest('.m-interstitial'))) return '';
              // 如果是元素，取其文本
              return node.textContent.trim();
            }
            // 如果是文本节点（为了抓取那些裸露的文本）
            if (node.nodeType === Node.TEXT_NODE) {
              return node.textContent.trim();
            }
            return '';
          })
          .filter(t => {
            // 基础过滤
            if (!t || t.length <= 1) return false;

            // ★★★ 新增：精准过滤“广告”二字 ★★★
            if (t === '广告') return false;

            // 过滤无效符号
            if (['@', '•', '∞', 'flex', '::before', '::after'].includes(t)) return false;

            // 过滤空白行
            if (/^\s*$/.test(t)) return false;
            return true;
          })
          .map(t => {
            // 额外清理：去掉可能残留的 "＜p>" 或类似标签文本
            return t.replace(/^＜p>/, '').trim();
          })
          .join('\n\n');
      }

      // 2. 提取图片
      if (textContent) {
        const figures = Array.from(article.querySelectorAll('figure.m-item-image'));

        if (figures.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
          const processedUrls = new Set();

          figures.forEach((figure, idx) => {
            const img = figure.querySelector('img');
            if (!img) return;

            // RFI 图片通常在 picture > source 中有高清源
            let bestUrl = '';
            const sources = figure.querySelectorAll('source');

            // 尝试从 source 中找最大的
            let maxW = 0;
            sources.forEach(src => {
              if (src.srcset) {
                const candidates = src.srcset.split(',').map(s => {
                  const parts = s.trim().split(/\s+/);
                  const url = parts[0];
                  const wStr = parts[1] || '';
                  const w = parseInt(wStr.replace(/\D/g, '')) || 0;
                  return { url, w };
                });
                const localMax = candidates.sort((a, b) => b.w - a.w)[0];
                if (localMax && localMax.w > maxW) {
                  maxW = localMax.w;
                  bestUrl = localMax.url;
                }
              }
            });

            // 回退 img 标签
            if (!bestUrl) {
              if (img.srcset) {
                const candidates = img.srcset.split(',').map(s => {
                  const parts = s.trim().split(/\s+/);
                  return { url: parts[0], w: parseInt(parts[1]?.replace(/\D/g, '') || '0') };
                }).sort((a, b) => b.w - a.w);
                if (candidates[0]) bestUrl = candidates[0].url;
              }
            }

            if (!bestUrl) bestUrl = img.src;

            if (!bestUrl) return;
            try {
              bestUrl = new URL(bestUrl, window.location.href).href;
            } catch (e) { return; }

            if (processedUrls.has(bestUrl)) return;
            processedUrls.add(bestUrl);

            // 提取 Caption
            let caption = '';
            const figcaption = figure.querySelector('figcaption');
            if (figcaption) {
              caption = Array.from(figcaption.querySelectorAll('span'))
                .map(s => s.textContent.trim())
                .join(' ')
                .trim();
            }
            if (!caption && img.alt) caption = img.alt.trim();

            let ext = 'jpg';
            if (bestUrl.includes('.webp')) ext = 'webp';
            else if (bestUrl.includes('.png')) ext = 'png';

            let filename = (caption || `rfi-image-${Date.now()}-${idx}`)
              .replace(/[\\/?%*:|"<>+]/g, '-')
              .replace(/\s+/g, ' ')
              .substring(0, 150)
              .trim();

            filename = `${filename}.${ext}`;

            chrome.runtime.sendMessage({
              action: 'downloadImage',
              url: bestUrl,
              filename: filename
            });
          });
        }
      }
    }
  }


  // 处理 economist.com
  else if (window.location.hostname.includes("economist.com")) {
    // ===== 新结构优先：Next.js 模板 (你给的示例) =====
    // 识别：<article data-test-id="Article" id="new-article-template"> 下
    // 正文段落：p[data-component="paragraph"]
    // 图片：figure.css-3mn275 > img （caption: figcaption > span.css-1st60ou）
    (function handleEconomistNewTemplate() {
      try {
        const newArticle = document.querySelector('article#new-article-template[data-test-id="Article"]') ||
          document.querySelector('article[data-test-id="Article"]');
        const mainContainer = document.querySelector('main#content') || document.querySelector('main[role="main"]') || document;

        if (!newArticle) {
          return; // 不命中新模板，交给旧逻辑
        }

        // 1) 提取正文
        const paragraphNodes = Array.from(newArticle.querySelectorAll('p[data-component="paragraph"]'));
        const joinNormalizedSpaces = (s) => s.replace(/\s+/g, ' ').replace(/&nbsp;/g, ' ').trim();

        const getParagraphText = (p) => {
          // 合并首字 + small + 其余文本
          // 示例结构：
          // <p>
          //   <span data-caps="initial">D</span>
          //   <small>ONALD TRUMP'S</small>
          //   后续文本节点/元素...
          // </p>
          let head = '';
          const firstCap = p.querySelector('span[data-caps="initial"]');
          const small = firstCap ? firstCap.nextElementSibling && firstCap.nextElementSibling.tagName === 'SMALL' ? firstCap.nextElementSibling : null : null;

          if (firstCap) head += firstCap.textContent || '';
          if (small) head += small.textContent || '';

          // 收集剩余文本：从 p 的所有子节点顺序遍历，跳过 firstCap 与 small，各种元素递归取文本
          const textFromNode = (node) => {
            if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
            if (node.nodeType === Node.ELEMENT_NODE) {
              if (node === firstCap || node === small) return '';
              // 对于 span/i/small/a 等，都递归
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

        // 2) 如果正文抓到了，再抓图片
        if (newTextContent) {
          // 找图片 figure
          const figures = Array.from(newArticle.querySelectorAll('figure.css-3mn275, figure[class*="css-3mn275"]'));
          const processedUrls = new Set();

          if (figures.length === 0) {
            // 没有图片，仍然复制正文
          } else {
            figures.forEach((figure, idx) => {
              const img = figure.querySelector('img');
              if (!img) return;

              // 选 srcset 最大宽度
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

              // 规范化到高分辨率 Cloudflare cdn-cgi/image URL
              // 如果已经是 cdn-cgi/image，就替换参数；否则保持原样（或后面可加更多兜底逻辑）
              try {
                const u = new URL(bestUrl, window.location.href);

                if (u.pathname.startsWith('/cdn-cgi/image')) {
                  // 形式: /cdn-cgi/image/width=...,quality=...,format=auto/content-assets/...
                  // 我们把 width 固定到 1424，quality=80，format=auto
                  // 把 "/cdn-cgi/image/xxx/content-assets/..." 拆分并重组
                  // 直接用字符串处理更稳妥
                  const rebuilt = u.origin + '/cdn-cgi/image/width=1424,quality=80,format=auto' +
                    u.pathname.replace(/^\/cdn-cgi\/image\/[^/]+/, '').replace(/\/{2,}/g, '/');
                  bestUrl = rebuilt + (u.search || '');
                } else {
                  // 如果不是 cdn-cgi，保持 bestUrl 不变
                  bestUrl = u.href;
                }
              } catch (e) {
                // 如果 URL 解析失败，保持原字符串
              }

              if (processedUrls.has(bestUrl)) return;
              processedUrls.add(bestUrl);

              // 取 caption
              let caption = '';
              const capSpan = figure.querySelector('figcaption span.css-1st60ou, figcaption span[class*="css-1st60ou"]');
              if (capSpan && capSpan.textContent) {
                caption = capSpan.textContent.trim();
              } else if (img.alt) {
                caption = img.alt.trim();
              }

              // 文件扩展名
              let ext = 'jpg';
              try {
                const pathname = new URL(bestUrl, window.location.href).pathname;
                const m = pathname.match(/\.(jpg|jpeg|png|webp|svg)(?:$|\?)/i);
                if (m) ext = m[1].toLowerCase() === 'jpeg' ? 'jpg' : m[1].toLowerCase();
              } catch (_) { }

              // 生成文件名
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

          // 复制正文
          const ta = document.createElement('textarea');
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          ta.value = newTextContent;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);

          // 覆盖外层变量 textContent，使上层返回 true
          textContent = newTextContent;
        }

        // 若 newTextContent 为空，交给旧逻辑继续尝试
      } catch (e) {
        // 新模板分支出错也不要影响旧逻辑
        console.warn('[Economist New Template] parsing failed:', e);
      }
    })();

    // ===== 兼容补丁分支：适配 data-testid + 混入引号文本的新变体（不影响上面的新模板与旧逻辑） =====
    (function handleEconomistPatchedVariant() {
      try {
        if (textContent) return; // 上面的新模板已成功提取则跳过

        // 命中更宽松的 Article 选择器：兼容 data-testid 与 data-test-id
        const articleNode =
          document.querySelector('article#new-article-template[data-testid="Article"]') ||
          document.querySelector('article[data-testid="Article"]') ||
          document.querySelector('article#new-article-template[data-test-id="Article"]') ||
          document.querySelector('article[data-test-id="Article"]');

        if (!articleNode) return;

        // 抓取正文段落：仍以 p[data-component="paragraph"] 为主
        const pList = Array.from(articleNode.querySelectorAll('p[data-component="paragraph"]'));
        if (pList.length === 0) return;

        const normalizeSpaces = (s) =>
          (s || '')
            .replace(/&nbsp;/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();

        const getTextDeep = (node, skipSet) => {
          // 深度收集文本，保留 a/small/i/span 中内容，跳过 skipSet 指定的节点
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
          // 合并首字与 small，然后把其余文本节点也拼进去，兼容被引号包裹的裸文本
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

          // tail 包含 p 中剩余所有文本（包括被 " 包起来的裸文本）
          let tail = getTextDeep(p, skip);

          // 某些页面把英文引号当作文本节点保留：剔除成对的左右引号中的多余空格与孤立引号
          // 先合并 head 与 tail
          let full = `${head} ${tail}`;

          // 清理奇怪符号（你原先的规则保留）
          full = full
            .replace(/[•∞@]/g, ' ')
            .replace(/“|”|‘|’/g, '"') // 将弯引号转直引号，便于统一处理
            .replace(/\s*"\s*/g, '"'); // 引号两侧空白归一

          // 处理被引号包裹且被拆开的片段（例如 " 1942 "）：
          // 1) 把连续的 "word" 合并为 word；2) 保留句内必要的引号
          // 简单启发式：去掉落单的引号；保留成对引号内部的文本
          // 先收敛多余空格
          full = normalizeSpaces(full);

          // 去除多数“孤立引号”：比如以空格分隔的独立 " 直接去掉
          full = full.replace(/\s"\s/g, ' ');

          // 常见模式：" 1942 " => 1942
          full = full.replace(/"\s*([^\"]+?)\s*"/g, '$1');

          // 再做总体空白与杂质清理
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

        // 若取到正文，再处理图片
        if (patchedText) {
          // 更宽松的 figure 选择器（class 名后缀可能变动）
          const figures = Array.from(
            articleNode.querySelectorAll(
              'figure.css-3mn275, figure[class*="css-3mn275"], figure[class*="e1197rjj0"]'
            )
          );

          const processed = new Set();

          figures.forEach((figure, idx) => {
            const img = figure.querySelector('img');
            if (!img) return;

            // 选 srcset 中最大宽度，或回退到 src
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

            // 规范化 Cloudflare cdn-cgi/image 到高分辨率
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
            } catch (_) {
              // 保持原样
            }

            if (processed.has(bestUrl)) return;
            processed.add(bestUrl);

            // 取 caption：兼容 class 变体
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

            // 文件扩展名推断
            let ext = 'jpg';
            try {
              const pathname = new URL(bestUrl, window.location.href).pathname;
              const m = pathname.match(/\.(jpg|jpeg|png|webp|svg)(?:$|\?)/i);
              if (m) ext = m[1].toLowerCase() === 'jpeg' ? 'jpg' : m[1].toLowerCase();
            } catch (_) { /* ignore */ }

            // 生成文件名
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

          // 复制正文到剪贴板，并设置 textContent 以便上层判断
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

    // ===== 旧结构逻辑（你现有的逻辑）放在下面，保持不动 =====
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
              !figure.closest('.css-1xfkcl4');
          });

        if (figures.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
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

  // 处理 nytimes.com
  else if (window.location.hostname.includes("nytimes.com")) {
    try {
      // ---- 去掉 paywall overlay ----
      const gate = document.querySelector('[data-testid="vi-gateway-container"]');
      if (gate) gate.style.display = 'none';

      // ★★★★★ 新增分支：适配 inline-interactive + adventure 项目结构 ★★★★★
      // 识别：section[data-testid="inline-interactive"].interactive-content 内部有 .interactive-body、#adventure-project-container、#adventure-target
      (function () {
        const inlineSection = document.querySelector(
          'section[data-testid="inline-interactive"].interactive-content'
        );

        const looksLikeAdventure =
          inlineSection &&
          inlineSection.querySelector('.interactive-body') &&
          inlineSection.querySelector('#adventure-project-container') &&
          inlineSection.querySelector('#adventure-target');

        if (!looksLikeAdventure) return; // 不符合则放行给后续分支

        const scope = inlineSection;

        // 1) 提取正文：.text-block p
        const paragraphNodes = Array.from(scope.querySelectorAll('.text-block p'));
        let textContent = paragraphNodes
          .map(p => {
            let t = (p.textContent || '').trim();
            t = t.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ');
            // 去掉整段被成对英文引号包裹的情况："... ..."
            t = t.replace(/^"\s*(.*?)\s*"$/, '$1');
            return t;
          })
          .filter(t => t && t.length > 1 && !/^[\s\W]*$/.test(t))
          .join('\n\n');

        // 2) 提取图片：限定在 scope 内
        const rawFigures = Array.from(
          scope.querySelectorAll('figure.full-width.media, figure')
        );
        const figures = rawFigures.filter(fig => fig.querySelector('picture img, img'));

        if (figures.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
          const seenUrls = new Set();
          const seenNames = new Set();

          figures.forEach((figure, i) => {
            const img = figure.querySelector('picture img, img');
            if (!img) return;

            let url = '';
            if (img.srcset && img.srcset.trim()) {
              const parts = img.srcset
                .split(',')
                .map(s => s.trim().split(' ')[0])
                .filter(Boolean);
              if (parts.length) url = parts[parts.length - 1];
            }
            if (!url && img.src) url = img.src;

            if (!url || seenUrls.has(url)) return;
            seenUrls.add(url);

            let cap =
              figure.querySelector('figcaption .caption-text')?.textContent?.trim() ||
              img.alt?.trim() ||
              `nytimes-inline-interactive-${Date.now()}-${i}`;

            cap = cap
              .replace(/[\r\n]+/g, ' ')
              .replace(/\s+/g, ' ')
              .replace(/[/\\?%*:|"<>+]/g, '-')
              .slice(0, 180)
              .trim();

            let filename = `${cap || 'image'}.jpg`;
            let k = 1;
            while (seenNames.has(filename)) {
              filename = `${cap || 'image'}(${k++}).jpg`;
            }
            seenNames.add(filename);

            chrome.runtime.sendMessage({ action: 'downloadImage', url, filename });
          });
        }

        // 3) 复制文本并阻断后续分支
        if (textContent) {
          const ta = document.createElement('textarea');
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          ta.value = textContent;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          throw { __NYT_HANDLED_INLINE_INTERACTIVE__: true }; // 返回 true
        } else {
          // 没有文本但可能已触发图片下载
          throw { __NYT_HANDLED_INLINE_INTERACTIVE__: false }; // 返回 false
        }
      })();

      // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★
      // ★★★ 修改开始：你之前已添加的“新版互动文章”页面支持（保持不动）★★★
      // ★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★★

      // 首先，尝试识别新版互动文章的独特容器
      const interactiveArticle = document.querySelector('article#interactive.interactive');

      if (interactiveArticle) {
        // --- 如果是新版互动文章，执行以下专用逻辑 ---

        // 1. 提取正文
        // 新版文章的正文段落是带有 'g-text' 类的 <p> 标签
        const paras = Array.from(interactiveArticle.querySelectorAll('p.g-text'));
        let textContent = paras
          .map(p => p.textContent.trim().replace(/\s+/g, ' '))
          .filter(t => t && t.length > 1)
          .join('\n\n');

        // 2. 提取图片
        // 新版文章的图片容器是带有 'g-wrapper' 类的 <figure> 标签
        const imageFigures = Array.from(interactiveArticle.querySelectorAll('figure.g-wrapper'));
        if (imageFigures.length === 0) {
          chrome.runtime.sendMessage({ action: 'noImages' });
        } else {
          const seenUrls = new Set();
          const seenNames = new Set();
          imageFigures.forEach((figure, i) => {
            const img = figure.querySelector('picture img, img');
            if (!img) return;

            // 使用与旧逻辑相同的策略获取最高分辨率图片URL
            let url = img.srcset ?
              img.srcset.trim().split(',').map(s => s.trim().split(' ')[0]).pop() :
              img.src;
            if (!url || seenUrls.has(url)) return;
            seenUrls.add(url);

            // 提取图片描述 (新版描述在 'p.g-caption' 中)
            let cap = figure.querySelector('p.g-caption')?.textContent ||
              img.alt ||
              `nytimes-interactive-${Date.now()}-${i}`;

            // 清理并生成文件名
            cap = cap.replace(/[/\\?%*:|"<>+]/g, '-').slice(0, 180).trim();
            let filename = `${cap}.jpg`;

            // 防止重名
            let k = 1;
            while (seenNames.has(filename)) {
              filename = `${cap}(${k++}).jpg`;
            }
            seenNames.add(filename);

            chrome.runtime.sendMessage({ action: 'downloadImage', url, filename });
          });
        }

        // 3. 复制文本（如果找到）并返回
        if (textContent) {
          const ta = document.createElement('textarea');
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          ta.value = textContent;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          return true; // 文本复制成功
        } else {
          // 即使没有文本，图片下载也可能已启动
          return false; // 表示没有文本被复制
        }
      } else {
        // --- 如果不是新版互动文章，则执行您原有的、运行正常的旧版逻辑 ---

        // 找到文章主节点
        const article = document.querySelector('main#site-content article, article#story');
        if (!article) {
          chrome.runtime.sendMessage({ action: 'noImages' });
          return false; // 明确返回false
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
          return false; // 明确返回false
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
        let textContent = paras
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
              let url = img.srcset ?
                img.srcset.trim().split(',').map(s => s.trim().split(' ')[0]).pop() :
                img.src;
              if (!url || seenUrls.has(url)) return;
              seenUrls.add(url);
              // 取 caption
              let cap = block.querySelector('figcaption span')?.textContent ||
                img.alt ||
                `nytimes-${Date.now()}-${i}`;
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
    } catch (e) {
      // 处理新增分支的控制流中断
      if (e && e.__NYT_HANDLED_INLINE_INTERACTIVE__ !== undefined) {
        return !!e.__NYT_HANDLED_INLINE_INTERACTIVE__;
      }
      // 其它异常继续抛出，便于调试
      throw e;
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

  // 修改：Nikkei Asia 处理 (支持三种页面结构)
  else if (window.location.hostname.includes("asia.nikkei.com")) {
    // 检查页面结构类型
    const shorthandArticle = document.querySelector('article.Theme-Story');
    const newStructureArticle = document.querySelector('.NewsArticleWrapper_newsArticleWrapper_SWTIa');

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

      // 提取图片及描述
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
    } else if (newStructureArticle) {
      // --- 2. 新版文章页面结构处理 (针对您反馈的页面) ---
      const bodyContainer = newStructureArticle.querySelector('[data-trackable="bodytext"]');
      if (bodyContainer) {
        const paras = Array.from(bodyContainer.querySelectorAll('p'))
          .map(p => p.textContent.trim().replace(/&nbsp;/g, ' '))
          .filter(t => t.length > 0);
        textContent = paras.join('\n\n');
      }

      if (textContent) {
        imagesFoundForDownload = true;
        const imageBlocks = Array.from(
          newStructureArticle.querySelectorAll(
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

            let url = img.src || '';
            url = url.trim();
            if (!url) return;

            if (url.startsWith('//')) url = location.protocol + url;
            else if (url.startsWith('/')) url = new URL(url, location.origin).href;

            if (seenUrls.has(url)) return;
            seenUrls.add(url);

            let captionText = '';
            // 在新结构中，caption 是 image block 的下一个兄弟元素
            const nextEl = block.nextElementSibling;
            if (nextEl && nextEl.matches('p[data-trackable="caption"]')) {
              captionText = nextEl.textContent.trim();
            }

            // 如果没有找到兄弟caption，回退到图片的alt属性
            if (!captionText) {
              captionText = img.alt.trim();
            }

            let baseName = captionText || `nikkei-image-${Date.now()}-${idx}`;
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
    } else {
      // --- 3. 原有旧版页面结构的处理逻辑 (作为最终后备) ---
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