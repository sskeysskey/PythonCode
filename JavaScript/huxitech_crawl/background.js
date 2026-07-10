const BRIDGE = "http://127.0.0.1:8765";
let running = false;

async function handleTask(task) {
  const payload = { id: task.id, ok: false, binary: !!task.binary };
  try {
    const resp = await fetch(task.url, { credentials: "include" });
    payload.status = resp.status;
    payload.ok = resp.ok;
    if (task.binary) {
      const buf = await resp.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = "";
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(
          null, bytes.subarray(i, i + chunk)
        );
      }
      payload.data = btoa(binary);
    } else {
      payload.data = await resp.text();
    }
  } catch (e) {
    payload.error = String(e);
  }
  try {
    await fetch(BRIDGE + "/deliver", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (e) {
    // 桥接掉线，忽略
  }
}

async function loop() {
  if (running) return;
  running = true;
  try {
    while (true) {
      let task = null;
      try {
        const r = await fetch(BRIDGE + "/poll");
        if (r.ok) task = await r.json();
      } catch (e) {
        // Python 服务没开或没网址，稍等再试
        await new Promise(res => setTimeout(res, 2000));
        continue;
      }
      if (task && task.id) {
        await handleTask(task);
      }
    }
  } finally {
    running = false;
  }
}

// 多重保险，防止 MV3 的 service worker 被回收后不再工作
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("keepalive", { periodInMinutes: 0.4 });
  loop();
});
chrome.runtime.onStartup.addListener(loop);
chrome.alarms.onAlarm.addListener(loop);
loop();