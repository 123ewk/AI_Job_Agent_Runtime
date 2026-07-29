# AI求职Agent Chrome Extension 前端设计Spec V1.0

## 1. 文档目标

定义 AI 求职 Agent Chrome Extension
的页面结构、尺寸规范、前后端接口需求。

目标：

-   支持 Agent 控制
-   支持 Human-in-the-loop
-   支持后台监听
-   支持任务状态展示

## 2. 插件页面结构

    extension/

    ├── sidepanel
    ├── popup
    ├── settings
    └── options

# 3. 页面尺寸

## SidePanel

主要工作台。

推荐宽度：

400px

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

## Popup

快速入口。

尺寸：

400px \* 600px

内容：

-   Agent开关
-   当前状态
-   快捷操作

## Settings

独立配置页。

推荐：

800px以上。

配置：

-   LLM
-   Key
-   自动回复
-   自动投递
-   求职规则

# 4. SidePanel模块设计

## Header

显示：

-   Agent名称
-   状态
-   设置入口

状态：

Idle

Running

Monitoring

Waiting Approval

Error

接口：

GET /api/v1/agent/status

------------------------------------------------------------------------

## Current Task

显示：

-   当前任务
-   Agent步骤
-   执行进度

接口：

GET /api/v1/tasks/{id}

------------------------------------------------------------------------

## Conversation

显示：

-   HR消息
-   Agent回复
-   用户回复

接口：

GET /api/v1/conversations/{id}/messages

发送：

POST /api/v1/messages/send

------------------------------------------------------------------------

## Approval Center

用于人工确认。

触发：

-   薪资
-   地点
-   入职时间
-   加班
-   外包
-   试用期工资

接口：

GET /api/v1/approvals/pending

POST /api/v1/approvals/{id}/approve

POST /api/v1/approvals/{id}/deny

------------------------------------------------------------------------

## Agent Event Log

显示：

-   Agent节点
-   Tool调用
-   错误

WebSocket：

/ws/sessions/{id}

事件：

agent.step

tool.call

message.sent

approval.required

# 5. Settings页面

## LLM配置

字段：

-   provider
-   base_url
-   api_key
-   model

接口：

PUT /api/v1/settings/llm

------------------------------------------------------------------------

## Agent配置

字段：

-   自动回复
-   自动投递
-   最大并发
-   监听时间

接口：

PUT /api/v1/settings/agent

------------------------------------------------------------------------

## 求职规则

字段：

-   薪资
-   地点
-   是否接受加班
-   是否接受外包
-   是否接受试用期工资
-   是否接受异地

接口：

PUT /api/v1/settings/job-rule

------------------------------------------------------------------------

# 6. 后端接口汇总

## Agent

GET /api/v1/agent/status

POST /api/v1/agent/start

POST /api/v1/agent/stop

## Task

POST /api/v1/tasks

GET /api/v1/tasks

GET /api/v1/tasks/{id}

## Conversation

GET /api/v1/conversations

GET /api/v1/conversations/{id}/messages

POST /api/v1/messages/send

## Sync

POST /api/v1/sync/messages

# 7. Service Worker职责

负责：

-   插件生命周期
-   WebSocket连接
-   后台通知
-   状态同步

# 8. Pinia Store设计

AgentStore:

-   status
-   currentTask
-   events

ConversationStore:

-   conversations
-   messages

ApprovalStore:

-   approvals

SettingsStore:

-   userConfig

# 9. 待确认

## P0

1.  SidePanel宽度

推荐：

400px

2.  Settings是否独立页面

推荐：

独立页面

3.  Popup是否保留

推荐：

保留

## P1

1.  是否需要任务历史页面

当前：

暂不需要

2.  是否增加数据统计页面

# 10. 开发顺序

1.  SidePanel骨架

2.  WebSocket状态

3.  Settings

4.  Approval

5.  Conversation

6.  Task控制
