# mcp-server —— Chrome MCP Server(AI Job Agent 浏览器桥)

把「真人打开页面的 Chrome」暴露为 MCP 工具的后端服务。扩展经 WebSocket 桥接入,后端 Tool Adapter 经 `/mcp`(StreamableHTTP)调用。

## 为什么不是 CDP

BOSS 直聘检测 CDP 调试会话(`chrome.debugger` / 远程调试端口),检测到会把页面关闭/导航回退。本服务走「扩展 `chrome.scripting` 在页面 MAIN world 按需注入」通道,不建立调试会话 —— 这是实测可存活的关键。

## 结构

```
mcp-server/
├── index.js   # Fastify: /mcp(Bearer 认证) + /ws(扩展 auth) + /ping
├── tools.js   # MCP 工具注册(doc 07 命名,只读5 + 交互6 + 占位7)
├── token.js   # 令牌管理: env BROWSER_MCP_TOKEN → ~/.browser-mcp-secrets.json(0600) → 生成
└── package.json
```

## 启动

```bash
npm install
npm start        # 或 node index.js; PORT/HOST 用 env 覆盖
```

## 令牌机制(三方一致)

1. server 启动时 `ensureToken()`:env `BROWSER_MCP_TOKEN` 优先,否则读 `~/.browser-mcp-secrets.json`,都没有则生成并写文件(0600)。
2. 扩展侧:用户在 popup 粘贴同一 token → `chrome.storage.local`(`browser_mcp_token`)。
3. 后端侧:`settings.browser_mcp_token` 为空时回退同一文件(与扩展天然一致)。

查看当前 token:

```bash
node token.js --print
```

## 端点

| 端点 | 认证 | 用途 |
|---|---|---|
| `GET /ping` | 无 | 健康检查,`{status, extension}` |
| `POST/GET/DELETE /mcp` | `Authorization: Bearer <token>` | MCP StreamableHTTP(后端 Tool Adapter) |
| `WS /ws` | 首条消息 `{type:"auth",token}`(5s 超时) | Chrome 扩展桥 |

## 工具清单(doc 07 命名)

只读:`chrome_read_page`(a11y树+ref)/ `chrome_get_web_content` / `chrome_screenshot` / `chrome_switch_tab` / `get_windows_and_tabs` / `chrome_javascript`(高危)
交互:`chrome_click_element` / `chrome_fill_or_select` / `chrome_keyboard` / `chrome_navigate`(页内) / `chrome_handle_dialog`
占位:`chrome_console` / `chrome_close_tabs` / `chrome_request_element_selection` / `chrome_computer` / `chrome_network_capture` / `chrome_network_request` / `chrome_upload_file`

## 生命周期

由后端 lifespan 以子进程拉起并管理(spawn / 30s 健康检查 / 崩溃重启),也可独立 `npm start` 手动运行。

## 与后端契约

- 后端依赖:`BROWSER_MCP_ENABLED`(默认 false)、`BROWSER_MCP_PORT`、`BROWSER_MCP_TOKEN`、`BROWSER_MCP_SERVER_PATH`
- 详见 `docs/AI求职Agent_设计文档_V2.0/17-ChromeMCPServer落地选型与实现.md`
