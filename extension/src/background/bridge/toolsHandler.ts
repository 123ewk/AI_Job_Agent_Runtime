// 浏览器工具处理器 —— 执行 MCP server 转发来的工具请求。
//
// 全部操作经 chrome.scripting.executeScript 在页面 MAIN world 执行，
// 不建立 chrome.debugger/CDP 调试会话（BOSS 直聘检测 CDP 会关闭/回退页面）。
// 页面内脚本：
//   - inject/accessibility-tree.js —— 无障碍树 + ref 句柄（chrome_read_page）
//   - inject/interact.js           —— click/fill/keyboard/getText/navigate/handleDialog
//
// 对齐设计：docs/AI求职Agent_设计文档_V2.0/17-ChromeMCPServer落地选型与实现.md §4（工具映射表）

type ToolParams = Record<string, unknown>

const RESTRICTED_PREFIXES = ["chrome://", "chrome-extension://", "about:", "file://", "data:"]

function isRestricted(url?: string): boolean {
  const lower = (url || "").toLowerCase()
  return !url || RESTRICTED_PREFIXES.some((p) => lower.startsWith(p))
}

/** 运行时保证真实标签页必有 id/windowId，窄化类型以消除可选链。 */
interface ResolvedTab {
  id: number
  windowId: number
  url?: string
  title?: string
  active?: boolean
}

async function getTargetTab(tabId?: number): Promise<ResolvedTab> {
  const tab = tabId != null ? await chrome.tabs.get(tabId) : (await chrome.tabs.query({ active: true, currentWindow: true }))[0]
  if (!tab) throw new Error("No active tab found")
  if (tab.id == null || tab.windowId == null) throw new Error("Tab has no id/windowId")
  return { id: tab.id, windowId: tab.windowId, url: tab.url, title: tab.title, active: tab.active }
}

/** 注入 interact.js（幂等：脚本自身会跳过重复定义）。 */
async function ensureInteract(tabId: number): Promise<void> {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["inject/interact.js"],
  })
}

/** 调用 window.__mcpInteract 的某个方法（需先 ensureInteract）。 */
async function callInteract<T>(tabId: number, method: string, params: Record<string, unknown>): Promise<T> {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: (m: string, p: Record<string, unknown>) => {
      const interact = (window as unknown as { __mcpInteract?: Record<string, (args: Record<string, unknown>) => unknown> }).__mcpInteract
      if (!interact || typeof interact[m] !== "function") {
        return { ok: false, error: "window.__mcpInteract 未定义（interact.js 注入失败？）" }
      }
      return interact[m](p)
    },
    args: [method, params],
  })
  const res = results?.[0]?.result as T | undefined
  if (res === undefined) throw new Error("interact 调用无返回值")
  return res
}

// --- 工具实现 ---

async function toolListTabs(): Promise<unknown> {
  const tabs = await chrome.tabs.query({})
  return tabs.map((t) => ({ id: t.id, url: t.url, title: t.title, active: t.active }))
}

async function toolReadPage(tabId?: number): Promise<unknown> {
  const tab = await getTargetTab(tabId)
  if (isRestricted(tab.url)) throw new Error("Cannot read this type of page")
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["inject/accessibility-tree.js"],
  })
  if (!results?.[0]?.result) throw new Error("Failed to read page DOM")
  return results[0].result
}

async function toolScreenshot(tabId?: number): Promise<unknown> {
  const tab = await getTargetTab(tabId)
  if (!tab.active) {
    await chrome.tabs.update(tab.id, { active: true })
    await new Promise((r) => setTimeout(r, 300))
  }
  return chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" })
}

async function toolFocusTab(tabId: number): Promise<unknown> {
  if (tabId == null) throw new Error("tabId is required")
  const tab = await getTargetTab(tabId)
  if (isRestricted(tab.url)) throw new Error("Cannot focus this type of page")
  await chrome.tabs.update(tab.id, { active: true })
  await chrome.windows.update(tab.windowId, { focused: true })
  return { ok: true }
}

async function toolInjectScript(params: ToolParams): Promise<unknown> {
  const { code } = params
  if (!code || typeof code !== "string") throw new Error("code is required")
  const tab = await getTargetTab(params.tabId as number | undefined)
  if (isRestricted(tab.url)) throw new Error("Cannot inject into this type of page")

  const resultKey = "__mcp_r_" + Date.now()
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    func: (userCode: string, key: string) => {
      try {
        const script = document.createElement("script")
        script.textContent = `try { window['${key}'] = { ok: true, value: (function(){ ${userCode} })() }; } catch(e) { window['${key}'] = { ok: false, error: e.message + '\\n' + (e.stack||'').slice(0,500) }; }`
        document.documentElement.appendChild(script)
        script.remove()
        const res = (window as unknown as Record<string, unknown>)[key]
        delete (window as unknown as Record<string, unknown>)[key]
        if (!res) return { ok: false, error: "Script produced no result (CSP may block inline scripts on this page)" }
        if (res && typeof res === "object" && "ok" in res) {
          const r = res as { ok: boolean; value?: unknown; error?: string }
          if (r.ok) {
            try {
              JSON.stringify(r.value)
            } catch {
              return { ok: false, error: `Return value is not JSON serializable: ${typeof r.value}` }
            }
          }
        }
        return res
      } catch (err) {
        return { ok: false, error: `${err instanceof Error ? err.message : String(err)}\n${err instanceof Error ? (err.stack || "").slice(0, 500) : ""}` }
      }
    },
    args: [code, resultKey],
  })

  const res = results?.[0]?.result as { ok: boolean; value?: unknown; error?: string } | undefined
  if (!res) throw new Error("Script execution returned no result")
  if (!res.ok) throw new Error(res.error)
  return res.value
}

// --- 交互工具（interact.js 实现） ---

async function toolInteract<T>(method: string, params: ToolParams): Promise<unknown> {
  const tab = await getTargetTab(params.tabId as number | undefined)
  if (isRestricted(tab.url)) throw new Error("Cannot interact with this type of page")
  await ensureInteract(tab.id)
  return callInteract<T>(tab.id, method, params)
}

/** 工具名 → 实现的分发表。 */
export async function handleToolRequest(method: string, params: ToolParams): Promise<unknown> {
  switch (method) {
    case "list_tabs":
      return toolListTabs()
    case "read_page":
      return toolReadPage(params.tabId as number | undefined)
    case "screenshot":
      return toolScreenshot(params.tabId as number | undefined)
    case "focus_tab":
      return toolFocusTab(params.tabId as number)
    case "inject_script":
      return toolInjectScript(params)
    // 交互（经 interact.js）
    case "click_element":
      return toolInteract("click", params)
    case "fill_or_select":
      return toolInteract("fill", params)
    case "keyboard":
      return toolInteract("keyboard", params)
    case "get_web_content":
      return toolInteract("getWebContent", params)
    case "navigate":
      return toolInteract("navigate", params)
    case "handle_dialog":
      return toolInteract("handleDialog", params)
    default:
      throw new Error(`Unknown method: ${method}`)
  }
}
