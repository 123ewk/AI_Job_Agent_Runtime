"""Schema DTO 层（请求/响应数据结构）。

职责：
- 定义 API 输入输出契约
- Pydantic 字段校验
- 枚举类型导出
- ORM Model -> Response 转换（通过 model_validate）

依赖方向：
    schema -> common + enums
    （不依赖 repository / model / service）
"""

from app.schema.common import (
    BaseSchema,
    ErrorResponse,
    PaginatedResponse,
    PaginationParams,
    StatusResponse,
)
from app.schema.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
)
from app.schema.enums import (
    ApprovalStatus,
    ApprovalType,
    CheckpointStatus,
    JobStatus,
    MemoryType,
    SyncMode,
    SyncStatus,
    TaskStatus,
    TaskType,
)
from app.schema.job import (
    HRCreate,
    HRResponse,
    JobCreate,
    JobFilterParams,
    JobResponse,
    JobUpdate,
)
from app.schema.memory import MemoryCreate, MemoryResponse, MemorySearchRequest
from app.schema.resume import ResumeCreate, ResumeResponse, ResumeSummaryResponse, ResumeUpdate
from app.schema.setting import (
    AgentConfigResponse,
    AgentConfigUpdate,
    JobRuleConfigResponse,
    JobRuleConfigUpdate,
    LLMConfigResponse,
    LLMConfigUpdate,
    SettingBatchUpdate,
    SettingCategoryResponse,
    SettingItem,
)
from app.schema.task import (
    ApprovalResponse,
    TaskApproveRequest,
    TaskCreate,
    TaskEvent,
    TaskFilterParams,
    TaskResponse,
    TaskUpdate,
)
from app.schema.user import UserCreate, UserLoginRequest, UserResponse, UserUpdate

__all__ = [
    # Common
    "BaseSchema",
    "PaginationParams",
    "PaginatedResponse",
    "ErrorResponse",
    "StatusResponse",
    # Enums
    "JobStatus",
    "TaskStatus",
    "TaskType",
    "ApprovalStatus",
    "ApprovalType",
    "SyncMode",
    "SyncStatus",
    "MemoryType",
    "CheckpointStatus",
    # User
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserLoginRequest",
    # Setting
    "SettingItem",
    "SettingCategoryResponse",
    "SettingBatchUpdate",
    "LLMConfigUpdate",
    "LLMConfigResponse",
    "AgentConfigUpdate",
    "AgentConfigResponse",
    "JobRuleConfigUpdate",
    "JobRuleConfigResponse",
    # Job
    "JobCreate",
    "JobUpdate",
    "JobResponse",
    "JobFilterParams",
    "HRCreate",
    "HRResponse",
    # Conversation
    "ConversationCreate",
    "ConversationUpdate",
    "ConversationResponse",
    "MessageCreate",
    "MessageResponse",
    # Task
    "TaskCreate",
    "TaskUpdate",
    "TaskResponse",
    "TaskFilterParams",
    "TaskApproveRequest",
    "ApprovalResponse",
    "TaskEvent",
    # Resume
    "ResumeCreate",
    "ResumeUpdate",
    "ResumeResponse",
    "ResumeSummaryResponse",
    # Memory
    "MemoryCreate",
    "MemoryResponse",
    "MemorySearchRequest",
]
