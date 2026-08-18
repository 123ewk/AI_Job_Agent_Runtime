"""配置中心。

设计动机：
- 所有运行时参数（数据库、Redis、MinIO、LLM、CORS 等）统一由 Settings 承载，
  避免散落在各模块的硬编码，满足"配置与环境隔离"。
- .env 文件位于仓库根目录（monorepo 顶层），由 backend 向上寻址读取，
  保证后端与未来其他服务共享同一份环境配置。
- 通过 pydantic-settings 做类型校验与零信任输入校验，非法值在启动期即暴露。
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    """运行环境枚举。dev/test/staging/prod 必须严格隔离。"""

    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


def _repo_root() -> Path:
    """返回仓库根目录。

    本文件位于 backend/app/core/config.py，向上 4 级即为仓库根。
    用绝对路径定位 .env，避免因启动 CWD 不同而读不到配置。
    """
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置。

    所有字段与根目录 .env.example 一一对应。新增配置项时务必同步更新 .env.example。
    """

    model_config = SettingsConfigDict(
        env_file=_repo_root() / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------- 应用 ----------------
    app_name: str = "AI Career Copilot"
    app_env: AppEnv = AppEnv.DEV
    debug: bool = False
    log_level: str = "INFO"

    # ---------------- PostgreSQL ----------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "ai_career"
    postgres_password: str = "change-me-in-prod"  # noqa: S105 - 占位默认值，非真实凭据
    postgres_db: str = "ai_career_dev"

    # ---------------- Redis ----------------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # ---------------- MinIO ----------------
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "ai_career_minio"
    minio_secret_key: str = "change-me-in-prod"  # noqa: S105 - 占位默认值，非真实凭据
    minio_bucket: str = "ai-career-assets"
    minio_secure: bool = False
    minio_auto_create_bucket: bool = True

    # ---------------- JWT ----------------
    jwt_secret_key: str = "changeme-to-a-random-secret"  # noqa: S105 - 占位默认值，非真实凭据
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # ---------------- LLM ----------------
    llm_provider: str = "doubao"
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    mimo_api_key: str = ""
    mimo_api_base: str = "https://token-plan-cn.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.5"
    doubao_api_key: str = ""
    doubao_api_base: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = "doubao-seed-2.0-pro"

    # ---------------- Tavily Search ----------------
    tavily_api_key: str = ""
    tavily_api_base: str = "https://api.tavily.com"
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 5
    tavily_timeout: float = 15.0
    tavily_max_retries: int = 3

    # ---------------- 文件上传 ----------------
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10

    # ---------------- CORS ----------------
    cors_allow_origins: str = ""  # 逗号分隔的白名单
    cors_allow_extensions: bool = True
    cors_allow_credentials: bool = True
    cors_max_age_seconds: int = 600

    # ---------------- 匹配模块 ----------------
    match_bm25_weight: float = 0.4
    match_semantic_weight: float = 0.6
    sentence_transformer_model: str = "BAAI/bge-small-zh-v1.5"
    semantic_scorer_enabled: bool = True
    match_bm25_scale: float = 5.0

    # ---------------- 浏览器桥（Chrome MCP Server） ----------------
    # 默认关闭：未显式开启时后端完全不带浏览器能力，不影响现有功能。
    # 通道设计见 docs/AI求职Agent_设计文档_V2.0/17-ChromeMCPServer落地选型与实现.md。
    browser_mcp_enabled: bool = False
    browser_mcp_host: str = "127.0.0.1"
    browser_mcp_port: int = 12307
    # 与 mcp-server/token.js 的令牌一致（env 优先，否则回退 ~/.browser-mcp-secrets.json）
    browser_mcp_token: str = ""
    # node 入口绝对路径；为空时按 "仓库根/mcp-server/index.js" 推断
    browser_mcp_server_path: str = ""
    # 单次工具调用超时（秒）；超时 -> 重启 server -> 重试
    browser_mcp_timeout: float = 30.0
    # 健康检查周期（秒）
    browser_mcp_ping_interval: float = 30.0
    # 工具调用 URL 域名白名单（逗号分隔；chrome_navigate / 高风险工具使用）
    browser_mcp_url_whitelist: str = "zhipin.com"
    # 高危工具（需 Skill 级授权 + 审计日志），逗号分隔
    browser_mcp_risk_tools: str = "chrome_javascript,chrome_network_request"

    # ---------------- 派生属性 ----------------
    @property
    def database_url(self) -> str:
        """异步 PG 连接串。

        密码做 URL 编码，防止含特殊字符（@:/ 等）破坏解析。
        asyncpg 驱动走 async/await，不阻塞事件循环。
        """
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def browser_mcp_url_whitelist_list(self) -> list[str]:
        """将逗号分隔的 URL 白名单解析为列表。"""
        return [
            item.strip()
            for item in self.browser_mcp_url_whitelist.split(",")
            if item.strip()
        ]

    @property
    def browser_mcp_risk_tools_list(self) -> list[str]:
        """将逗号分隔的高危工具列表解析为列表。"""
        return [
            item.strip()
            for item in self.browser_mcp_risk_tools.split(",")
            if item.strip()
        ]

    @property
    def browser_mcp_server_path_resolved(self) -> str:
        """解析 node 入口路径。

        显式配置优先；否则按本文件（backend/app/core/config.py）向上定位仓库根下的
        mcp-server/index.js。用绝对路径避免启动 CWD 不同导致找不到。
        """
        if self.browser_mcp_server_path:
            return self.browser_mcp_server_path
        return str(_repo_root() / "mcp-server" / "index.js")

    @property
    def redis_url(self) -> str:
        """Redis 连接串。无密码时省略 auth 段。"""
        auth = f":{quote_plus(self.redis_password)}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origins_list(self) -> list[str]:
        """将逗号分隔的 CORS 白名单解析为列表，留空返回空列表。"""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def is_dev(self) -> bool:
        return self.app_env == AppEnv.DEV


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回单例 Settings。

    lru_cache 保证整个进程只解析一次 .env，避免重复 IO；
    测试时可通过 get_settings.cache_clear() 重置。
    """
    return Settings()
