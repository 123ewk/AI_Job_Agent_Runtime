# AI求职Agent开发Spec V1.2（技术栈 + Chrome Extension前端综合版）

版本：V1.2

状态：开发基准文档

------------------------------------------------------------------------

# 1. 文档目的

本文档综合：

-   AI求职Agent开发Spec V1.1
-   Chrome Extension前端设计Spec V1.0

用于统一定义：

-   技术架构
-   插件前端设计
-   后端接口需求
-   开发边界

------------------------------------------------------------------------

# 2. 项目定位

AI求职Agent是一个垂直领域Agent。

核心目标：

-   自动分析岗位
-   判断岗位匹配度
-   管理HR沟通
-   自动回复消息
-   自动投递简历
-   后台监听HR消息

不是：

-   普通聊天机器人
-   简单LLM问答应用

------------------------------------------------------------------------

# 3. 总体架构

    Chrome Extension

        |
        | WebSocket / HTTP

    Backend API

        |

    Task Queue

        |

    LangGraph Agent Runtime

        |

    Skill Layer

        |

    MCP Client

        |

    stdio

        |

    Chrome MCP Server

        |

    Chrome Extension Bridge

        |

    Browser

------------------------------------------------------------------------

# 4. 技术栈冻结

## 前端

-   Chrome Extension Manifest V3
-   Vue3
-   TypeScript
-   Vite
-   Pinia

## 后端

-   Python
-   FastAPI
-   asyncio
-   Pydantic

## Agent

-   LangGraph
-   LangChain

## MCP

协议：

stdio

示例：

``` json
{
  "mcpServers": {
    "chrome-mcp": {
      "command": "node",
      "args": [
        "/path/to/server.js"
      ]
    }
  }
}
```

## 数据

-   PostgreSQL
-   pgvector

## 队列

-   Redis
-   Redis Stream

## 通信

-   WebSocket

------------------------------------------------------------------------

# 5. Chrome Extension设计

目录：

    extension/

    ├── sidepanel
    ├── popup
    ├── settings
    └── service-worker

------------------------------------------------------------------------

# 6. 页面设计

# 6.1 SidePanel

定位：

Agent主控制台。

尺寸：

推荐：

宽度 400px

高度：

跟随浏览器窗口。

布局：

    Header

    Agent状态

    当前任务

    HR聊天

    Approval

    执行日志

    输入区域

------------------------------------------------------------------------

## Header

显示：

-   Agent名称
-   当前状态
-   设置入口

状态：

-   Idle
-   Running
-   Monitoring
-   Waiting Approval
-   Error

接口：

GET /api/v1/agent/status

------------------------------------------------------------------------

## 当前任务

显示：

-   任务名称
-   当前节点
-   执行进度

接口：

GET /api/v1/tasks/{id}

------------------------------------------------------------------------

## HR聊天

显示：

-   HR消息
-   Agent回复
-   用户手动回复

接口：

GET /api/v1/conversations/{id}/messages

发送：

POST /api/v1/messages/send

------------------------------------------------------------------------

## Approval中心

处理：

-   薪资
-   地点
-   入职时间
-   加班
-   外包
-   试用期工资

接口：

GET /api/v1/approvals/pending

确认：

POST /api/v1/approvals/{id}/approve

拒绝：

POST /api/v1/approvals/{id}/deny

------------------------------------------------------------------------

## Agent日志

展示：

-   Agent节点
-   Tool调用
-   错误
-   重试

WebSocket：

/ws/sessions/{id}

事件：

-   agent.step
-   tool.call
-   message.sent
-   approval.required

------------------------------------------------------------------------

# 6.2 Popup

用途：

快速控制。

尺寸：

400×600

功能：

-   启动Agent
-   停止Agent
-   查看状态
-   打开SidePanel

------------------------------------------------------------------------

# 6.3 Settings

独立页面。

尺寸：

800px以上。

配置：

## LLM

字段：

-   provider
-   base_url
-   api_key
-   model

接口：

PUT /api/v1/settings/llm

------------------------------------------------------------------------

## Agent策略

字段：

-   自动回复
-   自动投递
-   最大并发HR数量
-   后台监听时间

接口：

PUT /api/v1/settings/agent

------------------------------------------------------------------------

## 求职规则

字段：

-   期望薪资
-   地点
-   是否接受加班
-   是否接受外包
-   是否接受试用期工资
-   是否接受异地

接口：

PUT /api/v1/settings/job-rule

------------------------------------------------------------------------

# 7. Service Worker职责

负责：

-   插件生命周期
-   WebSocket保持
-   浏览器事件监听
-   通知提醒

------------------------------------------------------------------------

# 8. Pinia Store设计

## AgentStore

保存：

-   status
-   currentTask
-   events

## ConversationStore

保存：

-   conversation列表
-   messages

## ApprovalStore

保存：

-   pending approval

## SettingsStore

保存：

-   用户配置

------------------------------------------------------------------------

# 9. 后端接口设计需求

## Agent

GET /api/v1/agent/status

POST /api/v1/agent/start

POST /api/v1/agent/stop

------------------------------------------------------------------------

## Task

POST /api/v1/tasks

GET /api/v1/tasks

GET /api/v1/tasks/{id}

------------------------------------------------------------------------

## Conversation

GET /api/v1/conversations

GET /api/v1/conversations/{id}/messages

------------------------------------------------------------------------

## Message

POST /api/v1/messages/send

------------------------------------------------------------------------

## Sync

POST /api/v1/sync/messages

功能：

同步Boss聊天记录。

------------------------------------------------------------------------

# 10. Agent与前端事件协议

事件：

    agent.step

    tool.call

    task.updated

    message.received

    message.sent

    approval.required

    task.failed

------------------------------------------------------------------------

# 11. 开发顺序

Phase 1:

Chrome Extension骨架

Phase 2:

Backend基础服务

Phase 3:

MCP stdio连接

Phase 4:

Boss Skill

Phase 5:

聊天同步

Phase 6:

Task系统

Phase 7:

LangGraph Agent

Phase 8:

自动回复

Phase 9:

自动投递

------------------------------------------------------------------------

# 12. 待确认事项

## P0

1.  Chrome MCP Server stdio启动参数

需要：

-   command
-   args

2.  Conversation ID生成规则

推荐：

Boss ID + 内部UUID

------------------------------------------------------------------------

## P1

1.  MinIO是否加入V1

2.  Docker Compose是否第一版使用

3.  Memory保存范围

------------------------------------------------------------------------

# 13. 冻结结论

V1固定：

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

后续开发基于本文档。
