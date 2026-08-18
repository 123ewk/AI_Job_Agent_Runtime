// MCP Tool 注册 —— 命名对齐 doc 07《MCP 与 Tool 体系设计 V2.0》§5 的 18 个 chrome_* 工具。
//
// 实现分层：
//   server（本文件）只负责参数校验 + 转发到扩展（sendToExtension）。
//   真正的浏览器操作在扩展 background 的 toolsHandler 里经 chrome.scripting 完成，
//   页面内脚本位于 extension/public/inject/。
//
// 只读 5 工具 + 交互 6 工具已实现；其余 7 个占位注册（返回未实现提示），
// 语义上可由 chrome_javascript 注入兜底。
import { z } from "zod";
import { sendToExtension } from "./index.js";

// --- inject_script 风险检测（保持原 browser-mcp-lite 行为） ---
const RISK_PATTERNS = [
  { pattern: /\b(fetch|XMLHttpRequest|sendBeacon|navigator\.sendBeacon)\s*\(/i, label: "network request" },
  { pattern: /document\.cookie/i, label: "cookie access" },
  { pattern: /localStorage|sessionStorage/i, label: "storage access" },
  { pattern: /indexedDB/i, label: "IndexedDB access" },
  { pattern: /new\s+WebSocket\s*\(/i, label: "WebSocket connection" },
  { pattern: /new\s+EventSource\s*\(/i, label: "EventSource connection" },
  { pattern: /window\.open\s*\(/i, label: "window.open" },
  { pattern: /document\.write/i, label: "document.write" },
];

function detectRisks(code) {
  return RISK_PATTERNS.filter((r) => r.pattern.test(code)).map((r) => r.label);
}

function textResponse(obj) {
  return { content: [{ type: "text", text: JSON.stringify(obj, null, 2) }] };
}

// --- 占位工具：语义由注入兜底，返回未实现提示 ---
function placeholder(name) {
  return `tool '${name}' 未在 server 实现。语义上可由 chrome_javascript 注入实现（Skill 层经 Tool Adapter 编排）。`;
}

export function registerTools(server) {
  // ===================================================================
  // 一、导航 / 标签
  // ===================================================================

  // doc 07 §5：列出窗口与标签（原 list_tabs）
  server.tool("get_windows_and_tabs", "列出所有打开的标签页（URL/标题/是否激活）", async () => {
    const tabs = await sendToExtension("list_tabs");
    return textResponse(tabs);
  });

  // doc 07 §5：切换/聚焦指定标签
  server.tool(
    "chrome_switch_tab",
    "切换到指定标签页（带到前台）",
    { tabId: z.number().describe("要聚焦的标签页 ID") },
    async ({ tabId }) => {
      await sendToExtension("focus_tab", { tabId });
      return textResponse({ ok: true, tabId });
    }
  );

  // doc 07 §5：导航/刷新/前进后退 —— 仅页内导航（location.href 赋值），
  // 不建立 CDP 会话，因此不触发 BOSS 直聘反自动化检测。
  // URL 域白名单校验在后端 Tool Adapter（browser_mcp.url_whitelist）执行。
  server.tool(
    "chrome_navigate",
    "在当前标签页内导航到指定 URL（仅页内导航，不触发 CDP；URL 白名单由后端校验）",
    { url: z.string().url().describe("目标 URL"), tabId: z.number().optional().describe("标签页 ID，缺省激活页") },
    async ({ url, tabId }) => {
      await sendToExtension("navigate", { url, tabId });
      return textResponse({ ok: true, url });
    }
  );

  server.tool(
    "chrome_close_tabs",
    "关闭指定标签页（占位：未在 server 实现）",
    { tabIds: z.array(z.number()).describe("要关闭的标签页 ID 列表") },
    async ({ tabIds }) => {
      return textResponse({ ok: false, error: placeholder("chrome_close_tabs"), tabIds });
    }
  );

  // ===================================================================
  // 二、内容读取
  // ===================================================================

  // doc 07 §5.1：无障碍树 + ref —— 抗 DOM 变化的核心（Skill 不写选择器）
  server.tool(
    "chrome_read_page",
    "读取标签页 DOM 的无障碍树（含 ref_* 句柄），供 Agent 定位元素",
    { tabId: z.number().optional().describe("标签页 ID，缺省激活页") },
    async ({ tabId }) => {
      const result = await sendToExtension("read_page", { tabId });
      return textResponse(result);
    }
  );

  server.tool(
    "chrome_get_web_content",
    "读取标签页正文文本/HTML（注入实现，返回 { text, html }）",
    { tabId: z.number().optional().describe("标签页 ID，缺省激活页") },
    async ({ tabId }) => {
      const result = await sendToExtension("get_web_content", { tabId });
      return textResponse(result);
    }
  );

  server.tool(
    "chrome_console",
    "读取控制台日志（占位：无 CDP 会话无法回溯 console；诊断可经 chrome_javascript 采样）",
    { tabId: z.number().optional().describe("标签页 ID，缺省激活页") },
    async ({ tabId }) => {
      return textResponse({ ok: false, error: placeholder("chrome_console"), tabId });
    }
  );

  // ===================================================================
  // 三、交互执行
  // ===================================================================

  // doc 07 §5：点击（ref / selector / 坐标，三选一）
  server.tool(
    "chrome_click_element",
    "点击页面元素：ref（read_page 返回的句柄，推荐）/ selector / 坐标",
    {
      ref: z.string().optional().describe("read_page 返回的 ref_* 句柄"),
      selector: z.string().optional().describe("CSS 选择器（仅 Tool Adapter 兜底路径使用，Skill 禁止写选择器）"),
      x: z.number().optional().describe("相对视口坐标 x（与 y 同时提供时生效）"),
      y: z.number().optional().describe("相对视口坐标 y"),
      tabId: z.number().optional().describe("标签页 ID，缺省激活页"),
    },
    async ({ ref, selector, x, y, tabId }) => {
      if (!ref && !selector && (x == null || y == null)) {
        return textResponse({ ok: false, error: "必须提供 ref / selector / (x,y) 之一" });
      }
      const result = await sendToExtension("click_element", { ref, selector, x, y, tabId });
      return textResponse(result);
    }
  );

  // doc 07 §5：填充/选择（contenteditable / input / textarea）
  server.tool(
    "chrome_fill_or_select",
    "向输入框填充文本：ref / selector；支持 contenteditable（聊天输入框）与原生 input/textarea",
    {
      value: z.string().describe("要填充的文本"),
      ref: z.string().optional().describe("read_page 返回的 ref_* 句柄"),
      selector: z.string().optional().describe("CSS 选择器（仅兜底路径）"),
      tabId: z.number().optional().describe("标签页 ID，缺省激活页"),
    },
    async ({ value, ref, selector, tabId }) => {
      if (!ref && !selector) return textResponse({ ok: false, error: "必须提供 ref 或 selector" });
      const result = await sendToExtension("fill_or_select", { value, ref, selector, tabId });
      return textResponse(result);
    }
  );

  // doc 07 §5：键盘输入（按键 + 修饰键）；文本键入走 fill_or_select
  server.tool(
    "chrome_keyboard",
    "按下单个按键（Enter/Escape/Tab/ArrowDown 等），可带修饰键（Ctrl/Shift/Alt/Meta）",
    {
      key: z.string().describe("按键名，如 Enter、Escape、Tab、ArrowDown、a、F5"),
      modifiers: z.array(z.enum(["Ctrl", "Shift", "Alt", "Meta"])).optional().describe("修饰键列表"),
      tabId: z.number().optional().describe("标签页 ID，缺省激活页"),
    },
    async ({ key, modifiers, tabId }) => {
      const result = await sendToExtension("keyboard", { key, modifiers: modifiers ?? [], tabId });
      return textResponse(result);
    }
  );

  // doc 07 §5：处理 alert/confirm/prompt（占位级别：注入 monkey-patch，拦截后续弹窗）
  server.tool(
    "chrome_handle_dialog",
    "拦截页面后续 alert/confirm/prompt 弹窗并自动应答（无 CDP 无法处理已弹出原生对话框）",
    {
      accept: z.boolean().optional().describe("confirm 默认 accept？默认 true"),
      text: z.string().optional().describe("prompt 自动输入的文本"),
      tabId: z.number().optional().describe("标签页 ID，缺省激活页"),
    },
    async ({ accept, text, tabId }) => {
      const result = await sendToExtension("handle_dialog", { accept: accept ?? true, text: text ?? "", tabId });
      return textResponse(result);
    }
  );

  // doc 07 §5：人工辅助选元素（占位：需配合前端弹层，后续迭代）
  server.tool(
    "chrome_request_element_selection",
    "请求用户手动选择页面元素（占位：未在 server 实现）",
    { hint: z.string().optional().describe("给用户的提示"), tabId: z.number().optional() },
    async ({ hint, tabId }) => {
      return textResponse({ ok: false, error: placeholder("chrome_request_element_selection"), hint, tabId });
    }
  );

  // doc 07 §5：综合操作（占位：由 click/fill/keyboard 组合实现）
  server.tool(
    "chrome_computer",
    "综合鼠标键盘+截图（占位：未在 server 实现，请用 click/fill/keyboard/screenshot 组合）",
    { action: z.string(), tabId: z.number().optional() },
    async ({ action, tabId }) => {
      return textResponse({ ok: false, error: placeholder("chrome_computer"), action, tabId });
    }
  );

  // ===================================================================
  // 四、注入 / 截图 / 网络 / 上传
  // ===================================================================

  // doc 07 §5：执行 JS（高危 —— 后端 Tool Adapter 标记需授权 + 审计）
  server.tool(
    "chrome_javascript",
    "在页面 MAIN world 执行 JavaScript 并返回结果（高危工具，后端要求授权 + 审计）",
    {
      code: z.string().max(10000).describe("要执行的 JS 代码（≤10000 字符，必须返回 JSON 可序列化值）"),
      tabId: z.number().optional().describe("标签页 ID，缺省激活页"),
    },
    async ({ code, tabId }) => {
      const risks = detectRisks(code);
      const result = await sendToExtension("inject_script", { code, tabId });
      const output = JSON.stringify(result, null, 2);
      if (risks.length > 0) {
        return textResponse({
          warning: `RISK: 该脚本使用了 ${risks.join(", ")}，请确认是有意为之`,
          ...result,
        });
      }
      return textResponse(result);
    }
  );

  server.tool(
    "chrome_screenshot",
    "截取标签页可视区域截图",
    { tabId: z.number().optional().describe("标签页 ID，缺省激活页") },
    async ({ tabId }) => {
      const dataUrl = await sendToExtension("screenshot", { tabId });
      const base64 = dataUrl.replace(/^data:image\/png;base64,/, "");
      return { content: [{ type: "image", data: base64, mimeType: "image/png" }] };
    }
  );

  // doc 07 §5：网络抓包（占位：无 CDP 无法回溯；可用 Performance API 经注入采样）
  server.tool(
    "chrome_network_capture",
    "抓取网络请求（占位：无 CDP 会话；可经注入脚本读 Performance API 采样）",
    { tabId: z.number().optional() },
    async ({ tabId }) => {
      return textResponse({ ok: false, error: placeholder("chrome_network_capture"), tabId });
    }
  );

  // doc 07 §5：带 Cookie 发请求（占位 + 高危 —— 需授权；Boss 反爬风险高，不实现）
  server.tool(
    "chrome_network_request",
    "带 Cookie 发请求（占位：高危工具，未实现。Boss 反爬会检测自动化请求）",
    {
      url: z.string().url(),
      method: z.enum(["GET", "POST", "PUT", "DELETE"]).default("GET"),
      headers: z.record(z.string()).optional(),
      body: z.string().optional(),
    },
    async ({ url, method, headers, body }) => {
      return textResponse({ ok: false, error: placeholder("chrome_network_request"), url, method });
    }
  );

  // doc 07 §5：上传文件（占位：投递简历需审批流 + 文件类型校验，后续迭代）
  server.tool(
    "chrome_upload_file",
    "上传文件（占位：未在 server 实现。投递简历需 doc 14 审批流 + pdf/doc/docx 类型校验）",
    { path: z.string(), tabId: z.number().optional() },
    async ({ path, tabId }) => {
      return textResponse({ ok: false, error: placeholder("chrome_upload_file"), path, tabId });
    }
  );
}
