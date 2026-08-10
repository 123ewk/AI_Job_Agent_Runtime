"""用户域 Schema 定义。"""

from __future__ import annotations

from pydantic import EmailStr, Field, field_validator

from app.schema.common import BaseSchema


class UserBase(BaseSchema):
    """用户基础字段。"""

    email: EmailStr = Field(..., description="邮箱地址", max_length=255)
    nickname: str | None = Field(None, description="昵称", max_length=100)


class UserCreate(UserBase):
    """创建用户请求。

    注册时仅需邮箱和密码；第三方登录由 auth 模块处理。
    """

    password: str = Field(..., min_length=8, max_length=128, description="密码（8-128 字符）")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """简单密码强度校验。"""
        if len(v) < 8:
            raise ValueError("密码长度不能少于 8 位")
        return v


class UserLoginRequest(BaseSchema):
    """用户登录请求。"""

    email: EmailStr = Field(..., description="邮箱地址")
    password: str = Field(..., description="密码")


class UserUpdate(BaseSchema):
    """更新用户信息请求（部分更新，全字段 Optional）。"""

    nickname: str | None = Field(None, max_length=100)
    avatar_url: str | None = Field(None, max_length=500)


class UserResponse(UserBase):
    """用户信息响应。

    注意：不返回密码哈希、API Key 等敏感字段。
    """

    id: int = Field(..., description="用户 ID")
    avatar_url: str | None = Field(None, description="头像 URL")
    is_active: bool = Field(..., description="是否激活")
    created_at: str = Field(..., description="创建时间（ISO 格式）")
