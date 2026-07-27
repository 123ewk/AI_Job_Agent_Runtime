# AI求职Agent开发Spec_V1.1（技术栈冻结版）

版本：V1.1

状态：开发基准文档

------------------------------------------------------------------------

# 1. 文档目的

本文档用于指导 AI 求职 Agent 进入正式开发阶段。

目标：

-   明确开发顺序
-   明确模块职责
-   固化技术选型
-   标记人工确认项
-   降低架构反复修改

------------------------------------------------------------------------

# 2. 项目定位

AI求职Agent是一个垂直领域Agent。

目标：

帮助用户完成：

-   岗位发现
-   岗位分析
-   HR沟通
-   自动回复
-   简历投递
-   求职流程管理

不是：

-   普通聊天机器人
-   简单Prompt套壳应用

------------------------------------------------------------------------

# 3. 技术栈冻结

## 3.1 前端

### Chrome Extension

技术：

-   Chrome Extension Manifest V3

### UI

技术：

-   Vue 3
-   TypeScript
-   Vite
-   Pinia

负责：

-   SidePanel
-   设置页面
-   Agent状态展示
-   Approval弹窗

状态：

已确定

------------------------------------------------------------------------

## 3.2 后端

技术：

-   Python
-   FastAPI
-   asyncio
-   Pydantic

负责：

-   API服务
-   Task管理
-   Agent运行
-   WebSocket通信

状态：

已确定

------------------------------------------------------------------------

## 3.3 Agent

技术：

-   LangGraph
-   LangChain

用途：

LangGraph：

-   状态机
-   Workflow
-   Checkpoint
-   Human-in-the-loop

LangChain：

-   LLM调用
-   Tool管理

状态：

已确定

------------------------------------------------------------------------

## 3.4 MCP

协议：

stdio

架构：

    LangGraph Agent

    ↓

    MCP Client

    ↓

    stdio

    ↓

    Chrome MCP Server

    ↓

    Chrome Extension

    ↓

    Browser

配置形式：

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

状态：

已确定

------------------------------------------------------------------------

## 3.5 数据库

主数据库：

PostgreSQL

向量：

pgvector

用途：

-   用户信息
-   岗位
-   聊天记录
-   简历向量
-   长期记忆

状态：

已确定

------------------------------------------------------------------------

## 3.6 缓存与队列

技术：

Redis

队列：

Redis Stream

用途：

-   Agent任务
-   HR消息事件
-   并发控制

状态：

已确定

------------------------------------------------------------------------

## 3.7 实时通信

技术：

WebSocket

用途：

Backend

↓

Chrome Extension SidePanel

展示：

-   Agent状态
-   执行日志
-   Approval请求

状态：

已确定

------------------------------------------------------------------------

# 4. 系统架构

    Chrome Extension

        |
        |
    Backend API

        |
        |
    Task Queue

        |
        |
    LangGraph Agent

        |
        |
    Skill Layer

        |
        |
    MCP Client

        |
        |
    Chrome MCP

        |
        |
    Browser

------------------------------------------------------------------------

# 5. 开发阶段

# Phase 0 项目初始化

开发：

-   Monorepo结构
-   Python环境
-   Vue项目
-   数据库初始化

输出：

可运行项目骨架

------------------------------------------------------------------------

# Phase 1 Chrome Extension

开发：

## Settings页面

配置：

-   LLM
-   API Key
-   自动回复
-   自动投递
-   并发数量
-   回复风格

## SidePanel

展示：

-   Agent状态
-   任务信息
-   Approval

## Service Worker

负责：

-   生命周期
-   后台通信

------------------------------------------------------------------------

# Phase 2 Backend基础服务

开发：

FastAPI：

接口：

-   用户配置
-   Task
-   Agent状态
-   WebSocket

------------------------------------------------------------------------

# Phase 3 MCP接入

目标：

完成：

Backend / Agent

调用Chrome MCP。

确认：

stdio启动方式。

人工确认项：

⚠️

需要确定：

Chrome MCP Server实际启动command和args。

------------------------------------------------------------------------

# Phase 4 Boss Skill

V1实现：

## boss.get_jobs

获取岗位。

## boss.get_job_detail

获取岗位详情。

## boss.get_messages

获取聊天记录。

## boss.sync_messages

同步消息。

## boss.send_message

发送消息。

## boss.apply_resume

投递简历。

## boss.verify_action

验证执行结果。

------------------------------------------------------------------------

# Phase 5 数据同步系统

原则：

所有消息进入数据库。

来源：

-   用户手动回复
-   Agent回复
-   Boss历史记录

核心：

messages表。

------------------------------------------------------------------------

# Phase 6 Task系统

技术：

Redis Stream

任务状态：

    PENDING

    RUNNING

    WAITING_APPROVAL

    WAITING_HR

    COMPLETED

    FAILED

    CANCELLED

规则：

一次执行一个Agent任务。

多个任务进入队列。

------------------------------------------------------------------------

# Phase 7 Agent Runtime

负责：

-   State管理
-   Checkpoint
-   Memory
-   Tool调用

Agent不负责：

-   长时间监听
-   定时任务

------------------------------------------------------------------------

# Phase 8 LangGraph Workflow

节点：

    Input Parser

    ↓

    Task Router

    ↓

    Job Analyze

    ↓

    Job Score

    ↓

    Conversation Analyze

    ↓

    Response Planner

    ↓

    Risk Check

    ↓

    Tool Executor

    ↓

    Result Verify

    ↓

    Memory Update

------------------------------------------------------------------------

# Phase 9 自动回复

普通消息：

自动发送。

需要确认：

-   薪资
-   地点
-   入职时间
-   加班
-   外包
-   试用期工资

------------------------------------------------------------------------

# Phase 10 自动投递

流程：

岗位发现

↓

评分

↓

超过阈值

↓

聊天

↓

HR索要简历

↓

投递

------------------------------------------------------------------------

# 6. 人工确认清单

## P0 必须确认

### MCP启动方式

需要：

-   command
-   args
-   环境变量

------------------------------------------------------------------------

### Conversation ID来源

推荐：

Boss ID + 内部UUID

------------------------------------------------------------------------

## P1 需要确认

### 文件存储

推荐：

MinIO

状态：

待确认

------------------------------------------------------------------------

### 部署方式

推荐：

Docker Compose

状态：

待确认

------------------------------------------------------------------------

### Memory范围

确认是否保存：

-   求职目标
-   技能
-   偏好
-   历史选择

------------------------------------------------------------------------

# 7. 开发风险

## Boss页面变化

方案：

Browser Recovery Agent。

## MCP能力不足

方案：

Skill降级。

## Agent错误回复

方案：

Risk Check + Approval。

------------------------------------------------------------------------

# 8. 开发顺序总结

1.  项目骨架

2.  Chrome Extension

3.  MCP连通

4.  Boss Skill

5.  数据同步

6.  Task系统

7.  Agent Runtime

8.  LangGraph Workflow

9.  自动回复

10. 自动投递

------------------------------------------------------------------------

# 9. 当前冻结结论

V1开发固定：

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

后续开发不改变核心架构。
