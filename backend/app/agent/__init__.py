"""Agent 编排层（backend/app/agent/）。

对齐 `docs/AI求职Agent_设计文档_V2.0/`：
- runtime/  Agent Runtime 引擎（doc 04）：队列消费/Checkpoint/Memory/调度/锁/Approval
- graph/    LangGraph 工作流（doc 06）：StateGraph 状态/节点/条件边/编译
- skills/   垂直领域 Skill 库（doc 08）：boss-extract-jobs 等
- tools/    MCP Tool 体系（doc 07）：MCP Client/Tool Adapter/Skill 映射
- domain/   Boss 领域规则与守卫（doc 05）：DomainGuard/领域对象/规则
- recovery/ 异常恢复（doc 15）：browser_recovery_agent
- prompts/  LLM Prompt 模板（planner/评分等）

本层位于 service 之上：agent 经 Skill 编排 browser/service，不直接写业务 SQL。
"""
