# 枚举与常量参考（Enums）

> 代码权威：`backend/app/schema/enums.py`
> 前端可通过 `/docs`（Swagger UI）或 `/openapi.json` 生成 TypeScript 类型定义。

所有枚举均为 `StrEnum`，与 ORM Model 层约束一致，确保 API 契约统一。

## JobStatus — 职位状态

| 值 | 说明 |
| --- | --- |
| `discovered` | 已发现（同步落库） |
| `scored` | 已匹配评分 |
| `chatting` | 沟通中 |
| `applied` | 已投递 |
| `rejected` | 已被拒 |
| `closed` | 已关闭 |
| `skipped` | 已跳过 |

**流转**：`discovered → scored → chatting → applied / rejected / closed / skipped`

## TaskStatus — 任务状态（七态）

| 值 | 说明 |
| --- | --- |
| `pending` | 排队等待执行 |
| `running` | 执行中 |
| `waiting_approval` | 等待人工确认 |
| `recovering` | 恢复中 |
| `succeeded` | 成功（终态） |
| `failed` | 失败（终态） |
| `canceled` | 已取消（终态） |

**合法流转**（由 `TaskService._validate_status_transition` 定义，非法流转 409）：
```
pending            → running, canceled
running            → waiting_approval, succeeded, failed, canceled, recovering
waiting_approval   → running, canceled
recovering         → running, failed
succeeded/failed/canceled → 终态，不可变
```

## TaskType — 任务类型

| 值 | 说明 | 自动优先级 |
| --- | --- | --- |
| `approval_resume` | 人工确认后继续 | **P0** |
| `recovery` | 故障恢复 | **P0** |
| `hr_reply` | HR 消息回复 | **P1** |
| `sync` | 数据同步 | **P1** |
| `user_initiated` | 用户主动触发 | **P2** |
| `proactive_chat` | 主动打招呼 | **P2** |
| `proactive_job` | 主动求职 | **P3** |
| `background_scan` | 后台扫描 | **P3** |

> ⚠️ 自动优先级以 `TaskService._get_priority_by_type` **实际实现**为准。路由 docstring 中的
> `proactive_job=P2`、`sync=P3`、`recovery=P3` 与实现不符，请以此表为准。

## TaskPriority — 任务优先级

| 值 | 说明 |
| --- | --- |
| `P0` | 最高：`approval_resume` / `recovery`（中断恢复） |
| `P1` | `hr_reply` / `sync` |
| `P2` | `user_initiated` / `proactive_chat` |
| `P3` | 后台低优先级（`proactive_job` / `background_scan`） |

## ApprovalStatus — 人工确认状态

| 值 | 说明 |
| --- | --- |
| `pending` | 等待用户确认（默认 20s 超时） |
| `approved` | 用户已同意 |
| `denied` | 用户已拒绝 |
| `timed_out` | 超时自动拒绝 |

## ApprovalType — 人工确认类型（敏感信息分类）

| 值 | 说明 |
| --- | --- |
| `salary` | 薪资 |
| `location` | 地点 |
| `start_date` | 到岗时间 |
| `overtime` | 加班 |
| `outsourcing` | 外包 |
| `offsite` | 异地办公 |
| `probation_salary` | 试用期薪资 |

> 关联：`job_rule` 配置中「未配置项（null）」即为这些类型的触发条件。

## SyncMode / SyncStatus — 同步模式与状态

| 枚举 | 值 | 说明 |
| --- | --- | --- |
| `SyncMode.INITIAL` | `initial` | 初次全量同步 |
| `SyncMode.MANUAL` | `manual` | 用户手动触发 |
| `SyncMode.INCREMENTAL` | `incremental` | 增量自动同步 |
| `SyncStatus.RUNNING` | `running` | 同步中 |
| `SyncStatus.COMPLETED` | `completed` | 完成 |
| `SyncStatus.FAILED` | `failed` | 失败 |

## MemoryType — 长期记忆类型

| 值 | 说明 |
| --- | --- |
| `preference` | 用户偏好 |
| `hr_pact` | HR 潜规则约定 |
| `interview` | 面试经验总结 |
| `decision` | 决策记录 |
| `fact` | 客观事实信息 |

> 注意：无 `history` 枚举值（schema 注释中出现过，但枚举未定义，传入会 422）。

## CheckpointStatus — Checkpoint 索引状态

| 值 | 说明 |
| --- | --- |
| `active` | 任务进行中 |
| `terminal` | 任务终态 |

## 会话与消息枚举（conversation schema 内联校验）

| 字段 | 允许值 |
| --- | --- |
| 会话 `status` | `active` / `waiting_hr` / `closed` |
| 消息 `role` | `user` / `hr` / `agent` / `system` |
| 消息 `source` | `manual` / `agent` / `history` |
