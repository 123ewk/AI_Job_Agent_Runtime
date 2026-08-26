"""领域异常体系（与 HTTP 解耦，只携带状态语义）。

为什么不用 ValueError：
- ValueError 没有状态语义，抛到 API 层一律变 500，前端无法区分「资源不存在」与
  「服务器内部错误」。
- Service 层不该依赖 FastAPI 的 HTTPException（分层方向 api -> service -> repository，
  service 不 import HTTP 层），故用自带 status_code 的领域异常，由 API 层全局 handler
  统一转换为 ErrorResponse。

设计：
- AppError 是唯一基类，子类只需声明 status_code 与 code（机器可读错误标识）。
- message 为面向用户的错误信息，details 承载附加字段（如冲突的 id 列表）。
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """业务异常基类。

    子类覆盖 status_code / code；实例构造时传入 message 与可选 details。
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundError(AppError):
    """资源不存在（404）。

    注意：V1 单用户模式下「不存在的资源」与「不属于当前用户的资源」统一按 404
    处理，避免泄露资源存在性。
    """

    status_code = 404
    code = "not_found"


class ForbiddenError(AppError):
    """权限不足 / 归属校验失败（403）。"""

    status_code = 403
    code = "forbidden"


class ConflictError(AppError):
    """业务状态冲突（409）。

    用于并发会话数超限、状态机非法流转等「当前状态不允许该操作」的场景。
    """

    status_code = 409
    code = "conflict"


class BadRequestError(AppError):
    """客户端参数/请求非法（400）。"""

    status_code = 400
    code = "bad_request"


class NotImplementedError(AppError):
    """功能未实现（501）。

    用于占位 stub 功能（如 sync / memory extract）。调用方应明确感知
    「未实现」，而非收到静默假成功——假成功比明确报错更危险，会让
    上游调用方误以为功能可用。
    """

    status_code = 501
    code = "not_implemented"
