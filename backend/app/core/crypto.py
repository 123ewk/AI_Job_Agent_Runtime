"""api_key 等敏感配置的对称加密工具。

设计动机：
- 配置中的 api_key 属高敏数据，DB JSONB 不应存明文
- 用 Fernet（AES128-CBC + HMAC）对称加密，密钥从 settings.jwt_secret_key 派生
- 派生用 SHA-256 做 key stretch，避免直接把字符串当密钥（Fernet 要求 32 字节
  url-safe base64 key）
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet


def _derive_key(secret: str) -> bytes:
    """从 secret 派生出 Fernet 兼容的 32 字节 url-safe base64 key。"""
    return urlsafe_b64encode(sha256(secret.encode("utf-8")).digest())


def encrypt_value(secret: str, plaintext: str) -> str:
    """加密敏感字符串，返回 Fernet token 文本。"""
    return Fernet(_derive_key(secret)).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(secret: str, token: str) -> str:
    """解密 Fernet token。

    密钥错误时抛 cryptography.fernet.InvalidToken，调用方需兜底（如视为未配置）。
    """
    return Fernet(_derive_key(secret)).decrypt(token.encode("utf-8")).decode("utf-8")
