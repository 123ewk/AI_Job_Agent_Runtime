# Agent状态机与Workflow设计

## Agent模式

Agent不是while循环服务。

采用事件驱动：

事件产生 -\> Agent启动 -\> 执行任务 -\> 保存状态 -\> 结束

## 节点

-   Input Parser
-   Task Router
-   Job Analyze
-   Job Score
-   Conversation Analyze
-   HR Intent Analyze
-   Response Planner
-   Risk Check
-   Tool Executor
-   Result Verify
-   Memory Update

## 主动任务

支持：

1.  岗位入口
2.  聊天入口
