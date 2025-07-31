// 用于在页面中检测视频的内容脚本
let foundVideos = [];  // 改为数组以存储视频URL和相关用户名
let observerActive = false;
// 用于存储可能包含不同分辨率的视频源
let highQualityVideoSources = new Map();

// 创建一个MutationObserver来监视DOM变化
const observer = new MutationObserver(() => {
    detectVideos();
});

// 检测页面上的所有视频
function detectVideos() {
    // 获取所有视频元素
    const videos = document.querySelectorAll('video');
    let newVideosFound = false;

    videos.forEach(video => {
        // 检查视频源
        if (video.src && video.src.startsWith('blob:')) {
            // 检查这个视频是否已经在列表中
            const existingVideo = foundVideos.find(v => v.url === video.src);
            if (!existingVideo) {
                // 尝试找到相关的用户名称
                const videoInfo = {
                    url: video.src,
                    title: "未知视频",
                    username: ""
                };

                // 尝试获取与视频相关的用户名
                // 首先查找包含视频的父元素
                let videoContainer = video;
                let maxSearchDepth = 10; // 防止无限循环
                let depth = 0;

                while (videoContainer && depth < maxSearchDepth) {
                    // 向上查找父元素，直到找到一个可能包含用户信息的元素
                    videoContainer = videoContainer.parentElement;
                    depth++;

                    // 如果找到了父容器，在其中查找用户名
                    if (videoContainer) {
                        // 查找用户名元素，根据你提供的HTML，通常在VonaH nonIntl类的元素内
                        const userNameElement = videoContainer.querySelector('.VonaH.nonIntl h3');
                        if (userNameElement && userNameElement.textContent) {
                            videoInfo.username = userNameElement.textContent.trim();
                            videoInfo.title = `${videoInfo.username}的视频`;
                            break;
                        }

                        // 如果找不到h3，尝试查找其他可能包含用户名的元素
                        const altUserNameElement = videoContainer.querySelector('a.gtry');
                        if (altUserNameElement) {
                            const username = altUserNameElement.getAttribute('href').split('/').pop();
                            if (username) {
                                videoInfo.username = username;
                                videoInfo.title = `${username}的视频`;
                                break;
                            }
                        }
                    }
                }

                foundVideos.push(videoInfo);
                newVideosFound = true;

                // 尝试提取真实视频URL
                fetchBlobUrl(video.src, videoInfo);
            }
        }

        // 检查source元素
        const sources = video.querySelectorAll('source');
        sources.forEach(source => {
            if (source.src) {
                const existingVideo = foundVideos.find(v => v.url === source.src);
                if (!existingVideo) {
                    // 类似逻辑来获取用户名
                    const videoInfo = {
                        url: source.src,
                        title: "未知视频",
                        username: ""
                    };

                    // ...同上的用户名检测代码
                    foundVideos.push(videoInfo);
                    newVideosFound = true;
                }
            }
        });
    });

    if (newVideosFound) {
        updateVideoList();
    }
}

// 尝试提取blob URL的实际内容
async function fetchBlobUrl(blobUrl, videoInfo) {
    try {
        // 获取blob内容
        const response = await fetch(blobUrl);
        const blob = await response.blob();

        // 创建临时URL以供下载
        const url = URL.createObjectURL(blob);

        // 添加到找到的视频中
        const existingVideo = foundVideos.find(v => v.url === blobUrl);
        if (existingVideo) {
            // 更新URL为可下载的URL
            existingVideo.downloadUrl = url;
            updateVideoList();
        }
    } catch (error) {
        console.error('提取blob内容时出错:', error);
    }
}

// 将找到的视频发送到后台脚本
function updateVideoList() {
    chrome.runtime.sendMessage({
        type: 'FOUND_VIDEOS',
        videos: foundVideos
    });
}

// 用于监听网络请求中的媒体文件
// 修改setupRequestCapture函数来寻找HLS或DASH清单
function setupRequestCapture() {
    // 覆盖原始fetch函数
    const originalFetch = window.fetch;
    window.fetch = async function (...args) {
        const response = await originalFetch.apply(this, args);

        // 克隆响应以便我们可以使用它
        const clone = response.clone();
        const url = response.url;

        try {
            const contentType = response.headers.get('content-type') || '';

            // 检查是否是视频内容
            if (contentType.includes('video/') ||
                url.includes('.mp4') ||
                url.includes('.m3u8') ||
                url.includes('.mpd')) {

                // 特别检查流媒体清单文件
                if (url.includes('.m3u8')) {
                    // 处理HLS清单
                    const manifest = await clone.text();
                    const highestResolutionUrl = extractHighestResolutionFromHLS(manifest, url);
                    if (highestResolutionUrl) {
                        // 将高分辨率视频添加到我们的列表中
                        const videoId = generateUniqueId(url);
                        highQualityVideoSources.set(videoId, {
                            manifestUrl: url,
                            highResUrl: highestResolutionUrl,
                            type: 'hls'
                        });

                        // 查找相关视频元素并关联这个高质量源
                        setTimeout(() => {
                            associateHighQualitySourceWithVideo(videoId);
                        }, 500);
                    }
                } else if (url.includes('.mpd')) {
                    // 处理DASH清单
                    const manifest = await clone.text();
                    const highestResolutionUrl = extractHighestResolutionFromDASH(manifest, url);
                    if (highestResolutionUrl) {
                        const videoId = generateUniqueId(url);
                        highQualityVideoSources.set(videoId, {
                            manifestUrl: url,
                            highResUrl: highestResolutionUrl,
                            type: 'dash'
                        });

                        setTimeout(() => {
                            associateHighQualitySourceWithVideo(videoId);
                        }, 500);
                    }
                }

                // 检查MP4文件的分辨率信息
                if (url.includes('.mp4')) {
                    // 保存视频URL，以便后续处理
                    const videoId = generateUniqueId(url);
                    const existingSource = highQualityVideoSources.get(videoId);

                    // 如果还没有这个视频或新URL可能是更高分辨率的
                    if (!existingSource || isLikelyHigherResolution(url, existingSource.highResUrl)) {
                        highQualityVideoSources.set(videoId, {
                            highResUrl: url,
                            type: 'mp4'
                        });

                        setTimeout(() => {
                            associateHighQualitySourceWithVideo(videoId);
                        }, 500);
                    }
                }

                // 如果是blob URL，也尝试关联它
                if (url.startsWith('blob:')) {
                    const existingVideo = foundVideos.find(v => v.url === url);
                    if (!existingVideo) {
                        // 检查这个blob是否对应于之前发现的高分辨率视频
                        const videoInfo = {
                            url: url,
                            title: `视频 (${url.split('/').pop()})`,
                            username: "",
                            isHighestResolution: true // 默认认为是最高分辨率，因为我们没有更多信息
                        };

                        // 尝试提取blob内容
                        fetchBlobUrl(url, videoInfo);

                        foundVideos.push(videoInfo);
                        updateVideoList();
                    }
                }
            }
        } catch (e) {
            console.error('分析响应时出错:', e);
        }

        return response;
    };

    // 同样修改XMLHttpRequest以捕获流媒体清单
    const originalXhrOpen = XMLHttpRequest.prototype.open;
    const originalXhrSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url) {
        this._url = url;
        return originalXhrOpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function () {
        const xhr = this;
        const url = xhr._url;

        if (url && (url.includes('.m3u8') || url.includes('.mpd') || url.includes('.mp4'))) {
            this.addEventListener('load', function () {
                try {
                    const contentType = xhr.getResponseHeader('content-type') || '';

                    if (url.includes('.m3u8')) {
                        const manifest = xhr.responseText;
                        const highestResolutionUrl = extractHighestResolutionFromHLS(manifest, url);
                        if (highestResolutionUrl) {
                            const videoId = generateUniqueId(url);
                            highQualityVideoSources.set(videoId, {
                                manifestUrl: url,
                                highResUrl: highestResolutionUrl,
                                type: 'hls'
                            });

                            setTimeout(() => {
                                associateHighQualitySourceWithVideo(videoId);
                            }, 500);
                        }
                    } else if (url.includes('.mpd')) {
                        const manifest = xhr.responseText;
                        const highestResolutionUrl = extractHighestResolutionFromDASH(manifest, url);
                        if (highestResolutionUrl) {
                            const videoId = generateUniqueId(url);
                            highQualityVideoSources.set(videoId, {
                                manifestUrl: url,
                                highResUrl: highestResolutionUrl,
                                type: 'dash'
                            });

                            setTimeout(() => {
                                associateHighQualitySourceWithVideo(videoId);
                            }, 500);
                        }
                    }
                } catch (e) {
                    console.error('分析XHR响应时出错:', e);
                }
            });
        }

        return originalXhrSend.apply(this, arguments);
    };
}

// 从HLS清单中提取最高分辨率的视频URL
// 从DASH清单中提取最高分辨率的视频URL
function extractHighestResolutionFromDASH(manifest, manifestUrl) {
    try {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(manifest, "text/xml");

        // 查找所有表示项
        const representations = xmlDoc.querySelectorAll('Representation');
        let highestBandwidth = 0;
        let highestRepresentation = null;

        representations.forEach(representation => {
            // 确保这是视频轨道
            const parent = representation.parentNode;
            if (parent.getAttribute('contentType') === 'video' || parent.getAttribute('mimeType')?.includes('video')) {
                const bandwidth = parseInt(representation.getAttribute('bandwidth') || '0');
                const width = parseInt(representation.getAttribute('width') || '0');
                const height = parseInt(representation.getAttribute('height') || '0');

                // 选择基于分辨率或带宽的最高质量
                if (width * height > highestBandwidth || (width * height === 0 && bandwidth > highestBandwidth)) {
                    highestBandwidth = width * height || bandwidth;
                    highestRepresentation = representation;
                }
            }
        });

        if (highestRepresentation) {
            // 获取基本URL
            const baseURLElement = highestRepresentation.querySelector('BaseURL') ||
                xmlDoc.querySelector('BaseURL');

            if (baseURLElement) {
                const baseURL = baseURLElement.textContent;
                // 将相对URL转换为绝对URL
                return new URL(baseURL, manifestUrl).href;
            }
        }
    } catch (e) {
        console.error('解析DASH清单时出错:', e);
    }

    return null;
}

// 将高质量视频源与页面中的视频元素关联起来
function associateHighQualitySourceWithVideo(videoId) {
    const source = highQualityVideoSources.get(videoId);
    if (!source) return;

    // 检查现有视频列表
    const existingVideo = foundVideos.find(v =>
        v.originalUrl === source.manifestUrl ||
        v.url === source.highResUrl ||
        v.manifestId === videoId
    );

    if (existingVideo) {
        // 更新为高分辨率URL
        existingVideo.highResUrl = source.highResUrl;
        existingVideo.manifestId = videoId;
        existingVideo.isHighestResolution = true;
        updateVideoList();
    } else {
        // 尝试查找页面上当前正在播放此视频的元素
        const videos = document.querySelectorAll('video');

        for (const video of videos) {
            // 检查这个视频元素是否关联了我们找到的清单
            if (video.currentSrc && (
                video.currentSrc.includes(source.manifestUrl) ||
                video.src.includes(source.manifestUrl))) {

                // 找出视频的上下文（用户名等）
                const videoInfo = extractVideoContext(video);

                videoInfo.url = video.src; // 原始src
                videoInfo.originalUrl = source.manifestUrl;
                videoInfo.highResUrl = source.highResUrl;
                videoInfo.manifestId = videoId;
                videoInfo.isHighestResolution = true;

                // 添加到视频列表中
                const duplicate = foundVideos.find(v => v.url === videoInfo.url);
                if (!duplicate) {
                    foundVideos.push(videoInfo);
                    updateVideoList();
                } else {
                    // 更新现有条目
                    Object.assign(duplicate, videoInfo);
                    updateVideoList();
                }

                break;
            }
        }
    }
}

// 辅助函数，用于从视频元素中提取上下文信息
function extractVideoContext(videoElement) {
    const videoInfo = {
        title: "未知视频",
        username: ""
    };

    // 同之前的代码，尝试找到与视频相关的用户名
    let element = videoElement;
    let maxSearchDepth = 10;
    let depth = 0;

    while (element && depth < maxSearchDepth) {
        element = element.parentElement;
        depth++;

        if (element) {
            const userNameElement = element.querySelector('.VonaH.nonIntl h3');
            if (userNameElement && userNameElement.textContent) {
                videoInfo.username = userNameElement.textContent.trim();
                videoInfo.title = `${videoInfo.username}的视频`;
                break;
            }

            const altUserNameElement = element.querySelector('a.gtry');
            if (altUserNameElement) {
                const username = altUserNameElement.getAttribute('href').split('/').pop();
                if (username) {
                    videoInfo.username = username;
                    videoInfo.title = `${username}的视频`;
                    break;
                }
            }
        }
    }

    return videoInfo;
}

// 生成唯一ID
function generateUniqueId(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
    }
    return hash.toString(16); // 转换为十六进制字符串
}

// 从URL判断哪个可能具有更高分辨率
function isLikelyHigherResolution(url1, url2) {
    // 这是一个简单的启发式方法，实际结果可能需要根据Snapchat的URL模式调整
    const res1Match = url1.match(/(\d+)x(\d+)/);
    const res2Match = url2.match(/(\d+)x(\d+)/);

    if (res1Match && res2Match) {
        const res1 = parseInt(res1Match[1]) * parseInt(res1Match[2]);
        const res2 = parseInt(res2Match[1]) * parseInt(res2Match[2]);
        return res1 > res2;
    }

    // 如果URL中包含质量提示
    const qualityHints = ['high', 'hd', '1080', '720', '4k'];
    for (const hint of qualityHints) {
        if (url1.includes(hint) && !url2.includes(hint)) {
            return true;
        }
    }

    // 如果文件大小信息可用（有时URL中包含大小信息）
    const size1Match = url1.match(/size=(\d+)/);
    const size2Match = url2.match(/size=(\d+)/);

    if (size1Match && size2Match) {
        return parseInt(size1Match[1]) > parseInt(size2Match[1]);
    }

    return false; // 无法确定
}

// 启动扩展功能
function init() {
    // 启动观察器
    if (!observerActive) {
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
        observerActive = true;
    }

    // 设置网络请求捕获
    setupRequestCapture();

    // 初始检测
    detectVideos();
}

// 在页面加载完成后初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// 监听消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'SCAN_VIDEOS') {
        detectVideos();
        sendResponse({ success: true });
    }
    return true;
});