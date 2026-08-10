"""枚举 Schema 定义（API 层导出供前端复用）。

所有枚举与 Model 层枚举保持一致，确保 API 契约统一。
前端可通过 `/api/v1/schema/openapi.json` 生成 TypeScript 类型定义。

枚举命名规则：
- {Domain}{Entity}Status：状态枚举
- {Domain}{Entity}Type：类型枚举
"""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """职位状态枚举（与 Model 层 + V2.0 doc 05/09 CHECK 约束一致）。

    流转：discovered -> scored -> chatting -> applied/rejected/closed/skipped
    """

    DISCOVERED = "discovered"
    SCORED = "scored"
    CHATTING = "chatting"
    APPLIED = "applied"
    REJECTED = "rejected"
    CLOSED = "closed"
    SKIPPED = "skipped"


class TaskStatus(StrEnum):
    """任务状态枚举（与 Model 层一致，doc 03 七态）。

    流转：pending -> running -> [waiting_approval/recovering -> running] -> succeeded/failed/canceled
    终态：succeeded / failed / canceled
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    RECOVERING = "recovering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskType(StrEnum):
    """任务类型枚举（与 doc 03 对齐）。"""

    PROACTIVE_JOB = "proactive_job"
    PROACTIVE_CHAT = "proactive_chat"
    HR_REPLY = "hr_reply"
    APPROVAL_RESUME = "approval_resume"
    SYNC = "sync"
    RECOVERY = "recovery"
    USER_INITIATED = "user_initiated"
    BACKGROUND_SCAN = "background_scan"


class TaskPriority(StrEnum):
    """任务优先级枚举（与 Model 层一致，doc 04）。

    P0: approval_resume（最高，中断恢复）
    P1: hr_reply（HR 消息回复需要及时）
    P2: user_initiated（用户主动触发）
    P3: background_scan/proactive_job（后台低优先级）
    """

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ApprovalStatus(StrEnum):
    """人工确认状态枚举。

    pending：等待用户确认（20 秒超时）
    approved：用户已同意
    denied：用户已拒绝
    timed_out：超时自动拒绝
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ApprovalType(StrEnum):
    """人工确认类型枚举（敏感信息分类）。"""

    SALARY = "salary"
    LOCATION = "location"
    START_DATE = "start_date"
    OVERTIME = "overtime"
    OUTSOURCING = "outsourcing"
    OFFSITE = "offsite"
    PROBATION_SALARY = "probation_salary"


class SyncMode(StrEnum):
    """同步模式枚举。"""

    INITIAL = "initial"  # 初次全量同步
    MANUAL = "manual"  # 用户手动触发
    INCREMENTAL = "incremental"  # 增量自动同步


class SyncStatus(StrEnum):
    """同步状态枚举。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MemoryType(StrEnum):
    """长期记忆类型枚举。"""

    PREFERENCE = "preference"  # 用户偏好
    HR_PACT = "hr_pact"  # HR 潜规则约定
    INTERVIEW = "interview"  # 面试经验总结
    DECISION = "decision"  # 决策记录
    FACT = "fact"  # 客观事实信息


class CheckpointStatus(StrEnum):
    """Checkpoint 索引状态枚举。"""

    ACTIVE = "active"  # 任务进行中
    TERMINAL = "terminal"  # 任务终态
