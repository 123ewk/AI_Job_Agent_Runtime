"""通用 Schema 定义（分页、错误响应、基础类型）。"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

T = TypeVar("T")


class BaseSchema(BaseModel):
    """所有 Schema 的基类。

    配置：
    - from_attributes=True：支持从 ORM Model 直接转换（model_validate）
    - extra="forbid"：禁止未定义字段，避免脏数据
    - populate_by_name=True：支持 alias 字段名
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        populate_by_name=True,
    )


class PaginationParams(BaseSchema):
    """分页查询参数。"""

    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=1, le=100, description="每页数量，1-100")

    @property
    def offset(self) -> int:
        """SQL OFFSET 计算值。"""
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseSchema, Generic[T]):
    """分页响应通用包装。

    所有列表接口统一返回此格式，便于前端分页组件处理。
    """

    items: list[T] = Field(..., description="当前页数据列表")
    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, description="每页数量")
    total_pages: int = Field(0, ge=0, validate_default=True, description="总页数")

    @field_validator("total_pages", mode="before")
    @classmethod
    def calculate_total_pages(cls, v: int | None, info: ValidationInfo) -> int:
        """自动计算总页数。

        Pydantic v2 对缺失必填字段不触发 before-validator，所以 total_pages
        必须给默认值（0）+ validate_default=True，否则构造器调用会 500。
        第二个参数是 ValidationInfo（v1 风格 dict 会 AttributeError）。
        """
        if v is not None:
            return v
        total = info.data.get("total", 0)
        page_size = info.data.get("page_size", 20) or 20
        if total == 0:
            return 0
        return (total + page_size - 1) // page_size

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """便捷创建分页响应。"""
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if total > 0 else 0,
        )


class ErrorResponse(BaseSchema):
    """错误响应格式。

    所有异常统一返回此格式，便于前端错误处理。
    """

    error: str = Field(..., description="错误类型标识")
    message: str = Field(..., description="用户可读错误信息")
    details: dict[str, Any] | None = Field(None, description="详细错误信息（可选）")
    request_id: str | None = Field(None, description="请求 ID（用于追踪排查）")


class StatusResponse(BaseSchema):
    """简单状态响应。

    用于不需要返回数据的操作（如删除、开关切换）。
    所有调用点统一构造 StatusResponse(status="ok", message=...)。
    """

    status: str = Field("ok", description="操作状态，成功为 ok")
    message: str | None = Field(None, description="提示信息")
