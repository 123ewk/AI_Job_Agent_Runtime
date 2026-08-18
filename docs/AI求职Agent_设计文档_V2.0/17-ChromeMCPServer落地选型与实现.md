# Chrome MCP Server 落地选型与实现

## 文档信息

| 项 | 值 |
|---|---|
| 文档名称 | Chrome MCP Server 落地选型与实现 |
| 版本 | V1.0 |
| 状态 | 已实现（2026-08-15） |
| 关联文档 | 02 系统架构 / 07 MCP 与 Tool 体系 / 08 Boss Skill / 11 Chrome Extension / 15 异常恢复 |
| 关联代码 | `mcp-server/`（node）、`extension/src/background/bridge/`（TS）、`backend/app/infra/browser_mcp.py` + `backend/app/service/browser_tools.py`（Python） |
| 来源 | 合并 browser-mcp-lite（MIT）进本仓库，作为 doc 07 中「Chrome MCP Server / Extension Bridge」的落地实现 |

---

## 1. 为什么是「扩展桥」而不是 CDP

BOSS 直聘反自动化检测已实测确认（2026-08-14/15 多次复现）：

- CDP 调试会话（`chrome.debugger` / `--remote-debugging-port`）被检测 → 页面**自动关闭 / 导航回退**。
- 仓库内 Claude 用 Playwright/CDP 主动导航 zhipin 页面，**标签页被关闭**（Frame detached）。

因此本实现走 **Chrome 扩展 + WebSocket 桥** 通道：

```
Chrome 扩展 (background, MV3)
  └─ chrome.scripting.executeScript(world: "MAIN")  ← 在页面内执行脚本
       ├─ 读取 DOM / 无障碍树
       ├─ 派发原生事件序列（click/fill/keyboard）
       └─ 读取 Vue $data 等页面内部状态
```

不建立 CDP 调试会话，扩展只做一个「按需注入」的桥 —— 这是 Boss 页面能存活的关键。

---

## 2. 三层通道与令牌机制

```
Agent/Skill ──> ToolAdapter ──> BrowserMcpClient(httpx) ──> mcp-server(node, Fastify)
                                                              ├─ /mcp  (Bearer token)   ← 后端侧
                                                              └─ /ws   (auth 首条消息)   ← 扩展侧
                                                                        └─ Chrome 扩展 background
                                                                             └─ chrome.scripting(MAIN world)
                                                                                  └─ Boss 页面
```

**令牌三方一致**（`mcp-server/token.js`）：

| 消费方 | 获取方式 |
|---|---|
| server | env `BROWSER_MCP_TOKEN` 优先 → `~/.browser-mcp-secrets.json`（0600）→ 生成并写文件 |
| 扩展 | 用户在 popup 粘贴（`node mcp-server/token.js --print` 查看）→ `chrome.storage.local[browser_mcp_token]` |
| 后端 | `BROWSER_MCP_TOKEN` env 优先 → 回退同一 secrets 文件（与扩展天然一致） |

> 兼容性：secrets 文件格式与 browser-mcp-lite 完全一致（`{"token": "..."}`），既有安装的令牌无需迁移。

---

## 3. 与 doc 07 的偏差记录（选型决策）

doc 07 §2/§4 冻结「MCP 仅 stdio、不暴露本地端口」。本实现采用 **StreamableHTTP + Bearer token**，是有意为之的偏差：

| 项 | doc 07 冻结 | 本实现 | 理由 |
|---|---|---|---|
| 传输 | stdio 子进程 JSON-RPC | HTTP `POST /mcp`（StreamableHTTP） | 复用现成 server 零改动；扩展/后端/调试三方共享同一端点 |
| 认证 | 无 | Bearer token（env/文件/扩展三方一致） | 127.0.0.1 上多进程共享必须鉴权；token 机制是用户明确要求 |
| 生命周期 | MCP Client 管理子进程 | 后端 lifespan spawn + 30s 健康检查 + 崩溃重启 | 与 doc 07 §4 语义一致，仅通道不同 |

**代价**：暴露 12307 端口（仅 127.0.0.1）。token 已鉴权；若未来需更严格，可加 IP 白名单或改回 stdio shim。

---

## 4. 工具映射表

doc 07 §5 的 18 个工具 → 各层实现状态：

| doc 07 工具 | server 注册 | 扩展 handler | 注入脚本 | 状态 |
|---|---|---|---|---|
| `get_windows_and_tabs` | ✅ | `list_tabs` | — | 已实现 |
| `chrome_switch_tab` | ✅ | `focus_tab` | — | 已实现 |
| `chrome_navigate` | ✅ | `navigate` | interact.js | 已实现（页内导航，URL 白名单在后端） |
| `chrome_close_tabs` | ✅ | — | — | 占位（注入兜底） |
| `chrome_read_page` | ✅ | `read_page` | accessibility-tree.js | 已实现（a11y 树 + ref_*） |
| `chrome_get_web_content` | ✅ | `get_web_content` | interact.js | 已实现（text + html） |
| `chrome_console` | ✅ | — | — | 占位（无 CDP 无法回溯） |
| `chrome_click_element` | ✅ | `click_element` | interact.js | 已实现（ref/selector/坐标） |
| `chrome_fill_or_select` | ✅ | `fill_or_select` | interact.js | 已实现（contenteditable/input/textarea） |
| `chrome_keyboard` | ✅ | `keyboard` | interact.js | 已实现（按键 + 修饰键） |
| `chrome_handle_dialog` | ✅ | `handle_dialog` | interact.js | 已实现（monkey-patch 拦截后续弹窗） |
| `chrome_request_element_selection` | ✅ | — | — | 占位（人工选元素，后续迭代） |
| `chrome_computer` | ✅ | — | — | 占位（click/fill/keyboard 组合） |
| `chrome_javascript` | ✅ | `inject_script` | MAIN world | 已实现（高危，需授权 + 审计） |
| `chrome_screenshot` | ✅ | `screenshot` | — | 已实现（captureVisibleTab） |
| `chrome_network_capture` | ✅ | — | — | 占位（Performance API 可采样） |
| `chrome_network_request` | ✅ | — | — | 占位（高危，Boss 反爬风险，不实现） |
| `chrome_upload_file` | ✅ | — | — | 占位（投递简历需审批流，后续迭代） |

---

## 5. 安全与红线对齐

- **Skill 不写选择器**（doc 07 §2/§5.1）：选择器只存在于 Tool Adapter / 例程注册表；`chrome_read_page` 返回 ref，Agent 用 ref 操作。DOM 变化 → ref 失效 → error_recovery 重新 read_page。
- **content script 禁止抽 DOM**（doc 11 §4.6/§13）：本实现的所有 DOM 读取都在 **MAIN world 按需注入**（由 background 经 chrome.scripting 触发），`src/content/index.ts` 保持纯占位不动。
- **零信任**（doc 07 §8）：
  - URL 域名白名单：`BROWSER_MCP_URL_WHITELIST`（默认 `zhipin.com`），`chrome_navigate`/`chrome_network_request` 强制校验。
  - 高危工具：`BROWSER_MCP_RISK_TOOLS`（默认 `chrome_javascript,chrome_network_request`）→ Adapter 直接拒绝（需 Skill 级授权 + 审计，本轮未接审批流）。
  - 浏览器锁：进程级 `asyncio.Lock` 串行化所有浏览器操作。
  - 超时/重试：30s 超时 → 重启 server → 重试（attempts 上限 3）。
  - 审计：`BrowserToolAdapter` 的 audit_sink 预留（未来接 `execution_logs`，node="tool_executor" 契约已就绪），当前降级为结构化日志。
- **拟人节奏**：`interact.js` 的点击/输入/按键带 30~150ms 随机抖动，避免机械化操作特征。

---

## 6. 配置项（根 `.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `BROWSER_MCP_ENABLED` | `false` | 总开关。关闭时后端完全不 spawn node 进程，现有功能零影响 |
| `BROWSER_MCP_HOST` / `BROWSER_MCP_PORT` | `127.0.0.1` / `12307` | server 监听地址端口 |
| `BROWSER_MCP_TOKEN` | 空 | 显式令牌；留空回退 `~/.browser-mcp-secrets.json` |
| `BROWSER_MCP_SERVER_PATH` | 空 | node 入口绝对路径；留空按 `仓库根/mcp-server/index.js` 推断 |
| `BROWSER_MCP_TIMEOUT` | `30.0` | 单次工具调用超时（秒） |
| `BROWSER_MCP_PING_INTERVAL` | `30.0` | 健康检查周期（秒） |
| `BROWSER_MCP_URL_WHITELIST` | `zhipin.com` | URL 域名白名单（逗号分隔） |
| `BROWSER_MCP_RISK_TOOLS` | `chrome_javascript,chrome_network_request` | 高危工具（需授权） |

---

## 7. 代码位置

| 层 | 文件 |
|---|---|
| server | `mcp-server/index.js` / `tools.js` / `token.js` / `package.json` / `README.md` |
| 扩展桥 | `extension/src/background/bridge/websocketClient.ts`（WS 生命周期 + keepalive alarm） |
| 扩展桥 | `extension/src/background/bridge/toolsHandler.ts`（工具分发 + chrome.scripting） |
| 扩展注入 | `extension/public/inject/accessibility-tree.js` / `interact.js`（MAIN world） |
| 扩展 UI | `extension/src/popup/Popup.vue`（浏览器桥区块：token + 状态灯 + 重连） |
| 后端客户端 | `backend/app/infra/browser_mcp.py`（BrowserMcpClient：生命周期 + JSON-RPC + 令牌解析） |
| 后端适配器 | `backend/app/service/browser_tools.py`（BrowserToolAdapter：白名单/高危/锁/审计） |
| 后端路由 | `backend/app/api/v1/browser.py`（`GET /api/v1/browser/status`） |
| 测试 | `backend/tests/test_browser_mcp.py` / `test_browser_tools.py` / `test_browser_api.py` |

---

## 8. 使用方式

1. 安装并启动 server（或由后端自动拉起）：
   ```bash
   cd mcp-server && npm install && npm start
   node token.js --print   # 查看令牌 —— 自动复制到剪贴板，直接 Ctrl+V 粘贴
   ```
2. 扩展：dev 加载 → popup「浏览器桥」→ 两种方式拿到令牌：
   - **一键获取**：点「获取」按钮（需后端运行中，从 `GET /api/v1/browser/token` 自动读取并填入保存）
   - **手动粘贴**：`cd mcp-server && node token.js --print`（自动复制到剪贴板）→ Ctrl+V 粘贴 →「保存」
3. 后端：`.env` 设 `BROWSER_MCP_ENABLED=true` → 启动后端（lifespan 自动 spawn server + 健康检查）。
4. 验证：`GET http://localhost:8000/api/v1/browser/status` → `{enabled, running, extension_connected, tools}`。
5. 调用：ToolAdapter 未接 Agent 循环；当前可经 Skill 层直接调 `call_tool`（如 `chrome_read_page`）。

---

## 9. 后续迭代

- **例程注册表 + RoutineFallback**：`chat.send_text`（fill+Enter）、`jobs.load_next_page`（滚动）等预写例程命中即直连桥，失败再切 LLM 兜底（省 token 方案，已与用户确认方向）。
- **审批流接入**：`chrome_upload_file`（投递简历）接 doc 14 Approval；高危工具走 Skill 级授权 + `execution_logs` 审计落库。
- **Boss Skill 接线**：doc 08 的 13 个 skill（`boss.send_message` / `boss.sync_messages` 等）经 Adapter 映射到工具，闭合寻岗 → 投递状态机。
- **人工选元素**：`chrome_request_element_selection` 配前端弹层。
- **网络工具**：`chrome_network_capture` 用 Performance API 采样（不新增 zhipin 请求，符合「只读已加载页面」约束）。

---

## 10. 风险与对策

- **Boss 反自动化无永久保证**：扩展 WS 桥 + MAIN world 注入「实测可用」，但可能被检测。对策：保持「只读为主 + 用户在场 + 拟人节奏」，不做批量抓取。
- **12307 端口暴露**：仅 127.0.0.1 + Bearer token；如需更强可加 IP 白名单或 stdio shim。
- **MV3 SW 生命周期**：24s keepalive alarm 保活；SW 被杀后 alarm 唤醒自动重连。
