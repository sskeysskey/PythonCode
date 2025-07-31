function extractVideoUrl() {
    // 首先尝试获取视频播放器中的直接链接
    const videoElements = document.querySelectorAll('video');
    for (const video of videoElements) {
        // 检查video元素的所有来源
        const sources = [];

        // 检查video标签的src属性
        if (video.src && video.src.includes('blob:')) {
            // 如果是blob URL，获取实际的媒体源
            const mediaSource = video.srcObject;
            if (mediaSource) {
                for (const track of mediaSource.getTracks()) {
                    const settings = track.getSettings();
                    if (settings.contentHint === 'video') {
                        sources.push(track.getCapabilities().deviceId);
                    }
                }
            }
        } else if (video.src) {
            sources.push(video.src);
        }

        // 检查source标签
        const sourceElements = video.getElementsByTagName('source');
        for (const source of sourceElements) {
            if (source.src) {
                sources.push(source.src);
            }
        }

        // 检查data-store属性
        if (video.dataset.store) {
            try {
                const dataStore = JSON.parse(video.dataset.store);
                if (dataStore.videoURL) {
                    sources.push(dataStore.videoURL);
                }
            } catch (e) {
                console.error('解析data-store失败:', e);
            }
        }

        // 过滤和返回有效的视频URL
        for (const source of sources) {
            if (isValidVideoUrl(source)) {
                return source;
            }
        }
    }

    // 如果没有找到video元素，尝试从页面脚本中提取
    const scripts = document.querySelectorAll('script');
    for (const script of scripts) {
        const content = script.textContent;
        if (content && content.includes('videoData')) {
            const matches = content.match(/"playable_url(?:_quality_hd)?":"([^"]+)"/);
            if (matches && matches[1]) {
                const url = matches[1].replace(/\\/g, '');
                if (isValidVideoUrl(url)) {
                    return url;
                }
            }
        }
    }

    // 最后尝试从meta标签中提取
    const metaTags = document.querySelectorAll('meta[property="og:video"]');
    for (const meta of metaTags) {
        const content = meta.getAttribute('content');
        if (content && isValidVideoUrl(content)) {
            return content;
        }
    }

    return null;
}

// 验证URL是否为有效的视频URL
function isValidVideoUrl(url) {
    if (!url) return false;

    // 检查是否是完整的URL
    try {
        new URL(url);
    } catch {
        return false;
    }

    // 检查是否包含视频文件扩展名或视频相关关键词
    const videoPatterns = [
        /\.mp4([?#]|$)/i,
        /\.m3u8([?#]|$)/i,
        /\/video\//i,
        /fbcdn/i,
        /video-\w+\.[\w.]+\/v\//i
    ];

    return videoPatterns.some(pattern => pattern.test(url));
}

// 辅助函数：递归搜索JSON中的视频URL
function findVideoUrlsInJson(obj, urls = []) {
    if (!obj || typeof obj !== 'object') return urls;

    // 检查常见的视频URL属性名
    const videoUrlKeys = [
        'playable_url', 'playable_url_quality_hd', 'video_url',
        'hd_src', 'sd_src', 'src', 'video_src', 'url'
    ];

    if (Array.isArray(obj)) {
        for (let item of obj) {
            findVideoUrlsInJson(item, urls);
        }
    } else {
        for (let key in obj) {
            const value = obj[key];

            // 检查是否是视频URL属性
            if (videoUrlKeys.includes(key) && typeof value === 'string' &&
                value.startsWith('http') &&
                (value.includes('.mp4') || value.includes('/video/'))) {
                urls.push(value);
            }

            // 递归检查嵌套对象
            if (typeof value === 'object' && value !== null) {
                findVideoUrlsInJson(value, urls);
            }
        }
    }

    return urls;
}

// 辅助函数：从元素中提取所有数据属性
function getAllDataAttributes(element) {
    const attributes = [];

    // 获取元素上的数据属性
    for (let attr of element.attributes) {
        if (attr.name.startsWith('data-')) {
            attributes.push(attr.value);
        }
    }

    // 递归获取所有子元素的数据属性
    const children = element.children;
    for (let i = 0; i < children.length; i++) {
        attributes.push(...getAllDataAttributes(children[i]));
    }

    return attributes;
}

// In content.js, add this function
function handleBlobVideoDownload(blobUrl) {
    // First try: Access the video element and use its source
    const videoElement = document.querySelector('video');
    if (videoElement && videoElement.src) {
        // Create a download link in the page
        const a = document.createElement('a');
        a.href = videoElement.src;
        a.download = `facebook_video_${Date.now()}.mp4`;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        return true;
    }

    // Second try: Fetch the blob data
    return fetch(blobUrl)
        .then(response => response.blob())
        .then(blob => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `facebook_video_${Date.now()}.mp4`;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            URL.revokeObjectURL(url);
            document.body.removeChild(a);
            return true;
        })
        .catch(error => {
            console.error("Error handling blob URL:", error);
            return false;
        });
}

// 添加一个新的快速提取方法
function createFacebookVideoPlayer() {
    // 为了绕过Facebook的限制，我们可以尝试创建一个新的播放器
    // 首先尝试从URL中提取视频ID
    const url = window.location.href;
    const match = url.match(/\/watch\/?\?v=(\d+)/);

    if (match && match[1]) {
        const videoId = match[1];
        console.log("创建新的视频播放器，视频ID:", videoId);

        // 创建一个iframe来加载原始视频
        const iframe = document.createElement('iframe');
        iframe.style.display = 'none';
        iframe.src = `https://www.facebook.com/video/embed?video_id=${videoId}`;
        document.body.appendChild(iframe);

        // 等待iframe加载并尝试提取视频URL
        return new Promise((resolve) => {
            iframe.onload = () => {
                try {
                    const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
                    const videoElement = iframeDoc.querySelector('video');

                    if (videoElement && videoElement.src) {
                        console.log("从iframe中提取到视频URL:", videoElement.src);
                        resolve(videoElement.src);
                    } else {
                        console.log("iframe中未找到视频元素");
                        resolve(null);
                    }
                } catch (e) {
                    console.error("访问iframe内容时出错:", e);
                    resolve(null);
                } finally {
                    // 清理iframe
                    document.body.removeChild(iframe);
                }
            };

            // 设置超时，防止永久等待
            setTimeout(() => {
                if (document.body.contains(iframe)) {
                    document.body.removeChild(iframe);
                }
                resolve(null);
            }, 5000);
        });
    }

    return Promise.resolve(null);
}

// 监听来自popup的消息
chrome.runtime.onMessage.addListener(function (request, sender, sendResponse) {
    console.log("收到消息:", request);

    // 添加新的处理方法
    if (request.action === "directBlobDownload") {
        const blobUrl = request.blobUrl;
        console.log("尝试直接下载blob视频:", blobUrl);

        // 获取视频元素
        const videoElement = document.querySelector('video');
        if (!videoElement) {
            sendResponse({ success: false, error: "找不到视频元素" });
            return true;
        }

        try {
            // 方法1: 尝试创建下载链接
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = `facebook_video_${Date.now()}.mp4`;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            sendResponse({ success: true });
        } catch (error) {
            console.error("直接下载blob视频失败:", error);
            sendResponse({ success: false, error: error.message });
        }

        return true;
    }

    if (request.action === "captureVideo") {
        captureAndDownloadVideo();
        return true;
    }

    if (request.action === "openVideoInPlayer") {
        openVideoInPlayer();
        return true;
    }

    if (request.action === "downloadBlobVideo") {
        const blobUrl = request.blobUrl;
        handleBlobVideoDownload(blobUrl)
            .then(success => {
                sendResponse({ success: success });
            });
        return true; // Keep the message channel open for async response
    }

    if (request.action === "extractVideo") {
        try {
            console.log("开始提取视频...");

            // 首先尝试常规方法
            const videoUrl = extractVideoUrl();

            if (videoUrl) {
                console.log("提取到视频URL:", videoUrl);
                sendResponse({ success: true, videoUrl: videoUrl });
                return true;
            }

            // 如果常规方法失败，尝试创建播放器提取
            console.log("常规方法失败，尝试创建播放器...");
            createFacebookVideoPlayer().then(url => {
                if (url) {
                    console.log("通过播放器提取到视频URL:", url);
                    sendResponse({ success: true, videoUrl: url });
                } else {
                    console.log("所有方法均未找到视频URL");
                    sendResponse({ success: false, error: "找不到视频链接" });
                }
            }).catch(error => {
                console.error("创建播放器时出错:", error);
                sendResponse({ success: false, error: "提取过程中出错: " + error.message });
            });

            return true; // 保持通道开放以便异步响应
        } catch (error) {
            console.error("提取视频过程中出错:", error);
            sendResponse({ success: false, error: "提取过程中出错: " + error.message });
            return true;
        }
    } else if (request.action === "getVideoId") {
        // 新增功能：仅提取视频ID
        try {
            const currentUrl = window.location.href;
            const match = currentUrl.match(/\/watch\/?\?v=(\d+)/);

            if (match && match[1]) {
                const videoId = match[1];
                console.log("提取到视频ID:", videoId);
                sendResponse({ success: true, videoId: videoId });
            } else {
                console.log("无法从URL提取视频ID");
                sendResponse({ success: false, error: "无法提取视频ID" });
            }
        } catch (error) {
            console.error("提取视频ID时出错:", error);
            sendResponse({ success: false, error: "提取视频ID时出错: " + error.message });
        }
        return true;
    }

    return true;
});

// 添加新的视频录制和下载函数
function captureAndDownloadVideo() {
    const videoElement = document.querySelector('video');
    if (!videoElement) return;

    // 保存当前播放状态
    const wasPlaying = !videoElement.paused;
    if (wasPlaying) videoElement.pause();

    try {
        // 使用MediaRecorder API录制视频
        const stream = videoElement.captureStream();
        const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
        const chunks = [];

        recorder.ondataavailable = e => chunks.push(e.data);
        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'video/webm' });
            const url = URL.createObjectURL(blob);

            // 创建下载链接
            const a = document.createElement('a');
            a.href = url;
            a.download = `facebook_video_${Date.now()}.webm`;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();

            // 清理
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 100);
        };

        // 开始录制
        recorder.start();

        // 回到播放状态并播放完整视频
        if (wasPlaying) videoElement.play();

        // 设置录制时间等于视频长度
        const duration = videoElement.duration * 1000 || 60000; // 默认60秒
        setTimeout(() => {
            recorder.stop();
            if (wasPlaying) videoElement.pause();
        }, duration);

        return true;
    } catch (error) {
        console.error("录制视频失败:", error);
        // 恢复原始播放状态
        if (wasPlaying) videoElement.play();
        return false;
    }
}

// 在新窗口中打开视频
function openVideoInPlayer() {
    const videoElement = document.querySelector('video');
    if (!videoElement || !videoElement.src) return false;

    // 创建包含原视频的新窗口
    const playerWindow = window.open("", "_blank");
    if (!playerWindow) {
        alert("无法打开新窗口，请检查您的浏览器设置");
        return false;
    }

    // 注入HTML
    playerWindow.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Facebook视频播放器</title>
            <style>
                body { margin: 0; background: #000; }
                video { width: 100%; height: 100vh; }
                .controls { position: fixed; bottom: 10px; right: 10px; }
                button { padding: 10px; margin: 5px; cursor: pointer; }
            </style>
        </head>
        <body>
            <video controls autoplay src="${videoElement.src}"></video>
            <div class="controls">
                <button id="downloadBtn">下载视频</button>
            </div>
            <script>
                document.getElementById('downloadBtn').addEventListener('click', function() {
                    const video = document.querySelector('video');
                    if (!video || !video.src) return;
                    
                    const a = document.createElement('a');
                    a.href = video.src;
                    a.download = 'facebook_video_${Date.now()}.mp4';
                    a.style.display = 'none';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                });
            </script>
        </body>
        </html>
    `);
    playerWindow.document.close();

    return true;
}

// Add this to content.js
function captureVideoStream() {
    const videoElement = document.querySelector('video');
    if (!videoElement) return null;

    try {
        const stream = videoElement.captureStream();
        const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
        const chunks = [];

        recorder.ondataavailable = e => chunks.push(e.data);
        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'video/webm' });
            const url = URL.createObjectURL(blob);
            chrome.runtime.sendMessage({
                action: "videoRecorded",
                blobUrl: url
            });
        };

        // Record for the duration of the video
        recorder.start();
        setTimeout(() => {
            recorder.stop();
        }, videoElement.duration * 1000);

        return true;
    } catch (error) {
        console.error("Cannot capture video stream:", error);
        return null;
    }
}

function downloadBlobWithoutCORS(blobUrl) {
    // 获取视频元素
    const video = document.querySelector('video');
    if (!video) return false;

    try {
        // 使用canvas捕获视频帧并创建一个新的视频
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        // 绘制当前帧
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        // 提示用户
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.7);
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 9999;
            font-size: 20px;
            text-align: center;
            padding: 20px;
        `;
        overlay.innerHTML = `
            <div>
                <p>由于浏览器安全限制，无法直接下载视频。</p>
                <p>请点击视频上的右键，然后选择"另存为..."选项来保存视频。</p>
                <button id="closeBtn" style="padding: 10px; margin-top: 20px; cursor: pointer;">关闭提示</button>
            </div>
        `;
        document.body.appendChild(overlay);

        document.getElementById('closeBtn').addEventListener('click', () => {
            document.body.removeChild(overlay);
        });

        return true;
    } catch (error) {
        console.error("无法处理blob视频:", error);
        return false;
    }
}

// In content.js
function createDownloadLink(videoUrl) {
    // Find the video element
    const videoElement = document.querySelector('video');
    if (!videoElement) return false;

    // Create a capture canvas
    const canvas = document.createElement('canvas');
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;

    // Draw the current frame
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

    // Create download link
    const a = document.createElement('a');
    a.download = `facebook_video_${Date.now()}.mp4`;
    a.href = videoUrl;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    return true;
}

// 页面加载完成后立即执行一次提取尝试
console.log("Facebook视频下载器内容脚本已加载");
try {
    setTimeout(() => {
        const videoUrl = extractVideoUrl();
        console.log("页面加载后检测到的视频URL:", videoUrl);
    }, 1000); // 延迟1秒，等待页面完全加载
} catch (error) {
    console.error("初始提取视频过程中出错:", error);
}

// 尝试获取视频直接URL的函数
function getDirectVideoUrl() {
    const videoElement = document.querySelector('video');
    if (!videoElement) return null;

    // 尝试各种获取方法
    // 1. 直接从video元素获取
    if (videoElement.src && !videoElement.src.startsWith('blob:')) {
        return videoElement.src;
    }

    // 2. 从source标签获取
    const sources = videoElement.querySelectorAll('source');
    for (const source of sources) {
        if (source.src && !source.src.startsWith('blob:')) {
            return source.src;
        }
    }

    // 3. 尝试从网络请求中获取
    // 在content.js中添加
    const originalXHR = window.XMLHttpRequest;
    window.XMLHttpRequest = function () {
        const xhr = new originalXHR();
        const originalOpen = xhr.open;

        xhr.open = function () {
            const url = arguments[1];
            if (url && typeof url === 'string' && url.includes('video')) {
                // 存储潜在的视频URL
                window.postMessage({
                    type: 'POTENTIAL_VIDEO_URL',
                    url: url
                }, '*');
            }
            return originalOpen.apply(this, arguments);
        };
        return xhr;
    };

    return null;
}

// 新增函数：处理Facebook特定的视频源
function extractFacebookSourceUrl() {
    // 针对Facebook特定的视频源提取
    const scripts = document.querySelectorAll('script');
    for (const script of scripts) {
        const text = script.textContent || '';

        // 寻找常见的视频URL模式
        const hdMatch = text.match(/"hd_src":"([^"]+)"/);
        if (hdMatch && hdMatch[1]) {
            return hdMatch[1].replace(/\\/g, '');
        }

        const sdMatch = text.match(/"sd_src":"([^"]+)"/);
        if (sdMatch && sdMatch[1]) {
            return sdMatch[1].replace(/\\/g, '');
        }

        // 寻找其他可能的视频URL模式
        const playableMatch = text.match(/"playable_url":"([^"]+)"/);
        if (playableMatch && playableMatch[1]) {
            return playableMatch[1].replace(/\\/g, '');
        }
    }

    // 尝试从页面元数据中提取
    const metaVideo = document.querySelector('meta[property="og:video:url"]');
    if (metaVideo && metaVideo.content) {
        return metaVideo.content;
    }

    return null;
}

// 监听消息
window.addEventListener('message', function (event) {
    if (event.data.type === 'POTENTIAL_VIDEO_URL') {
        const url = event.data.url;
        if (isValidVideoUrl(url)) {
            chrome.runtime.sendMessage({
                action: 'videoUrlFound',
                url: url
            });
        }
    }
});