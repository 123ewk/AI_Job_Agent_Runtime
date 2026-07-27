// Content Script：注入招聘页面，负责 DOM 提取与元素操作。
// Phase 0 仅占位：报到 + 监听 background 指令。

console.info("[content] content script loaded:", location.href)

chrome.runtime.onMessage.addListener((msg: unknown, _sender, sendResponse) => {
  console.info("[content] received:", (msg as { type?: string })?.type)
  sendResponse({ ok: true })
  return true
})
