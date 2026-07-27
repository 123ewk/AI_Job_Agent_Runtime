# AI求职Agent技术栈与技术选型文档 V1.0

## 1. 文档目的

本文档用于冻结 AI 求职 Agent 项目的核心技术路线，指导后续开发。

------------------------------------------------------------------------

# 2. MCP通信协议调整

## 原方案

Streamable HTTP：

``` json
{
  "type": "streamable-http",
  "url": "http://127.0.0.1:12306/mcp"
}
```

## 新方案

采用：

**stdio MCP**

配置示例：

``` json
{
  "mcpServers": {
    "chrome-mcp": {
      "command": "node",
      "args": [
        "/path/to/mcp-server.js"
      ]
    }
  }
}
```

## 调整原因

stdio 更适合本地 Agent：

-   MCP Client 管理 Server 生命周期
-   不需要暴露本地 HTTP 端口
-   调试简单
-   符合桌面 Agent 使用模式

最终架构：

    LangGraph Agent
            |
         MCP Client
            |
          stdio
            |
     Chrome MCP Server
            |
     Chrome Extension
            |
     Browser

------------------------------------------------------------------------

# 3. 前端技术栈

## Chrome插件

技术：

-   Chrome Extension Manifest V3

## UI

技术：

-   Vue 3
-   TypeScript
-   Vite
-   Pinia

用途：

-   SidePanel
-   Settings
-   Approval窗口
-   Agent状态展示

状态：

已确定

------------------------------------------------------------------------

# 4. 后端技术栈

技术：

-   Python
-   FastAPI
-   asyncio
-   Pydantic

用途：

-   API服务
-   WebSocket
-   Task管理
-   Agent运行环境

状态：

已确定

------------------------------------------------------------------------

# 5. Agent技术栈

## Agent框架

LangGraph

原因：

-   状态机
-   Workflow
-   Checkpoint
-   Human-in-the-loop

## LLM框架

LangChain

用途：

-   模型调用
-   Tool管理

状态：

已确定

------------------------------------------------------------------------

# 6. Skill与MCP设计

原则：

Agent 不直接调用浏览器工具。

结构：

    Agent

    ↓

    Skill

    ↓

    MCP Tool

例如：

    boss.send_message

    ↓

    chrome_fill_or_select

    chrome_click_element

Skill负责业务语义封装。

------------------------------------------------------------------------

# 7. 数据存储

## 主数据库

PostgreSQL

用途：

-   用户配置
-   任务
-   聊天记录
-   岗位数据

## 向量能力

pgvector

用途：

-   简历Embedding
-   语义匹配
-   长期记忆

状态：

已确定

------------------------------------------------------------------------

# 8. 缓存与队列

技术：

Redis

用途：

-   Task Queue
-   Agent事件
-   并发控制

队列：

Redis Stream

状态：

已确定

------------------------------------------------------------------------

# 9. 实时通信

技术：

WebSocket

用途：

Backend 与 Chrome Extension SidePanel 实时通信。

展示：

-   Agent步骤
-   日志
-   Approval请求

状态：

已确定

------------------------------------------------------------------------

# 10. 文件存储

推荐：

MinIO

用途：

-   简历文件
-   截图
-   执行证据

状态：

待确认

------------------------------------------------------------------------

# 11. 日志系统

V1：

Python Logging

-   

PostgreSQL execution_logs

记录：

-   task_id
-   node
-   tool
-   input
-   output
-   error

状态：

已确定

------------------------------------------------------------------------

# 12. 部署

推荐：

Docker Compose

服务：

    backend
    worker
    postgres
    redis
    minio

状态：

待确认

------------------------------------------------------------------------

# 13. 技术栈汇总

  领域         技术                        状态
  ------------ --------------------------- --------
  插件         Chrome Extension MV3        确定
  前端         Vue3 + TypeScript + Pinia   确定
  后端         FastAPI                     确定
  Agent        LangGraph                   确定
  LLM框架      LangChain                   确定
  浏览器控制   Chrome MCP Server           确定
  MCP协议      stdio                       确定
  数据库       PostgreSQL                  确定
  向量         pgvector                    确定
  缓存         Redis                       确定
  队列         Redis Stream                确定
  通信         WebSocket                   确定
  文件         MinIO                       待确认
  部署         Docker Compose              待确认

------------------------------------------------------------------------

# 14. 当前人工确认项

## 必须确认

1.  Chrome MCP Server 的stdio启动命令。

需要确定：

-   command
-   args
-   环境变量

2.  MinIO是否进入V1。

3.  Docker Compose是否作为第一版部署方式。

------------------------------------------------------------------------

# 15. 技术冻结结论

V1开发采用：

-   Vue3
-   TypeScript
-   Chrome Extension MV3
-   FastAPI
-   LangGraph
-   LangChain
-   MCP stdio
-   PostgreSQL + pgvector
-   Redis Stream
-   WebSocket

后续开发基于此技术栈。
