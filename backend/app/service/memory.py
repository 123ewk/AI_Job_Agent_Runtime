"""记忆业务服务。

负责长期记忆的语义检索、写入、关联与分层。
Memory 是 Agent 的长期上下文，跨会话保留。

跨域协作：
- 与 LLM 协作：生成 embedding 向量
- 与 pgvector 协作：余弦相似度检索
- 与 Agent Runtime 协作：任务启动时注入检索结果，结束时提取新记忆
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError, NotImplementedError
from app.infra.embedding import EMBEDDING_DIM, EmbeddingError, generate_embedding
from app.models.memory import Memory as MemoryModel
from app.repository.memory import ZERO_EMBEDDING, MemoryRepository
from app.schema.memory import MemoryCreate, MemoryResponse, MemorySearchRequest
from app.service.base import BaseService, transactional

# 三级检索权重（doc 04 §11）
WEIGHT_CONVERSATION = 1.0
WEIGHT_JOB = 0.7
WEIGHT_GLOBAL = 0.4

# 相似度阈值（高于此值判定为重复，跳过写入）
SIMILARITY_DUPLICATE_THRESHOLD = 0.95


class MemoryService(BaseService):
    """记忆业务服务。

    职责：
    - 文本向量化（调用 embedding 模型）
    - 语义检索（pgvector 余弦相似度 + 元数据过滤）
    - 跨上下文加权排序（conversation / job / user 三级）
    - 记忆提取与去重（避免重复保存相同事实）
    - 记忆分层（短期会话记忆 / 中期岗位记忆 / 长期偏好记忆）
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.memory_repo = MemoryRepository(db)

    def _to_response(
        self,
        memory: MemoryModel,
        similarity_score: float | None = None,
    ) -> MemoryResponse:
        """ORM Model 转 DTO。

        实现 Model -> DTO 转换，确保 ORM 字段不直接泄漏到 API。
        检索结果时可附加相似度得分。
        """
        return MemoryResponse(
            id=memory.id,
            user_id=memory.user_id,
            type=memory.type,
            content=memory.content,
            conversation_id=memory.conversation_id,
            job_id=memory.job_id,
            similarity_score=similarity_score,
            created_at=memory.created_at.isoformat() if memory.created_at else "",
        )

    @transactional
    async def add(self, user_id: int, data: MemoryCreate) -> MemoryResponse:
        """添加新记忆。

        自动生成 embedding 向量，去重检查（相似度过高则跳过）。

        去重逻辑（优雅降级）：
        1. 生成 embedding 向量；未配置向量模型时返回 None
        2a. 已配置：语义去重（相似度 > 0.95 视为重复，跳过写入）
        2b. 未配置（降级）：精确内容去重 + 零向量占位落库
        3. 存在则跳过并返回现有记忆，否则写入新记忆

        Args:
            user_id: 关联用户 ID
            data: 记忆创建请求

        Returns:
            新建或已存在的记忆响应
        """
        embedding = await self._generate_embedding(user_id, data.content)

        if embedding is None:
            # 降级：无向量可用，精确内容去重 + 零向量占位（满足 embedding NOT NULL）
            existing = await self.memory_repo.find_by_content_exact(
                user_id=user_id,
                content=data.content,
                memory_type=data.type,
            )
            if existing:
                self.logger.debug(
                    "memory_duplicate_exact_skip",
                    user_id=user_id,
                    existing_id=existing.id,
                )
                return self._to_response(existing)
            embedding = ZERO_EMBEDDING
        else:
            # 已配置向量模型：语义去重（检索高相似度记忆）
            existing = await self.memory_repo.semantic_search(
                user_id=user_id,
                query_vector=embedding,
                limit=1,
                memory_type=data.type,
            )
            if existing:
                memory, distance = existing[0]
                similarity = 1.0 - distance
                if similarity >= SIMILARITY_DUPLICATE_THRESHOLD:
                    self.logger.debug(
                        "memory_duplicate_skip",
                        user_id=user_id,
                        existing_id=memory.id,
                        similarity=round(similarity, 4),
                    )
                    return self._to_response(memory, similarity_score=similarity)

        # 写入新记忆
        new_memory = await self.memory_repo.create(
            {
                "user_id": user_id,
                "type": data.type,
                "content": data.content,
                "conversation_id": data.conversation_id,
                "job_id": data.job_id,
                "embedding": embedding,
            }
        )

        self.logger.info(
            "memory_created",
            user_id=user_id,
            memory_id=new_memory.id,
            memory_type=data.type,
            conversation_id=data.conversation_id,
            job_id=data.job_id,
        )

        return self._to_response(new_memory)

    async def search(self, user_id: int, request: MemorySearchRequest) -> list[MemoryResponse]:
        """语义检索相关记忆。

        优雅降级：已配置向量模型 → pgvector 余弦相似度 Top-K；未配置 →
        关键词 ILIKE 检索（按时间倒序）。

        注意：语义路径返回的 similarity_score 是余弦相似度（0~1），值越大
        越相似；pgvector 的 cosine_distance = 1 - cosine_similarity。

        Args:
            user_id: 检索用户范围
            request: 检索请求（query + 过滤条件）

        Returns:
            按相似度排序（语义）或时间倒序（降级）的记忆列表
        """
        query_vector = await self._generate_embedding(user_id, request.query)

        if query_vector is None:
            # 降级：无向量可用，关键词 ILIKE 检索
            results = await self.memory_repo.search_keyword(
                user_id=user_id,
                keyword=request.query,
                limit=request.top_k,
                conversation_id=request.conversation_id,
                job_id=request.job_id,
                memory_type=request.memory_type,
            )
            self.logger.debug(
                "memory_keyword_search_completed",
                user_id=user_id,
                query_len=len(request.query),
                result_count=len(results),
                conversation_id=request.conversation_id,
                job_id=request.job_id,
            )
            return [self._to_response(memory) for memory in results]

        results = await self.memory_repo.semantic_search(
            user_id=user_id,
            query_vector=query_vector,
            limit=request.top_k,
            conversation_id=request.conversation_id,
            job_id=request.job_id,
            memory_type=request.memory_type,
        )

        self.logger.debug(
            "memory_search_completed",
            user_id=user_id,
            query_len=len(request.query),
            result_count=len(results),
            conversation_id=request.conversation_id,
            job_id=request.job_id,
        )

        return [
            self._to_response(memory, similarity_score=1.0 - distance)
            for memory, distance in results
        ]

    async def get_context_for_task(
        self,
        user_id: int,
        conversation_id: int | None = None,
        job_id: int | None = None,
        top_k: int = 15,
    ) -> list[dict[str, Any]]:
        """获取任务启动时注入 Planner 的上下文记忆。

        三级检索策略（doc 04 §11）：
        1. 当前 conversation 相关记忆（权重 1.0）
        2. 当前 job 相关记忆（权重 0.7）
        3. 用户全局偏好记忆（权重 0.4）

        结果合并去重，按加权相关性排序，取 Top-N。

        去重规则：相同 fact（content 文本相同）保留最高权重版本。

        优雅降级：未配置向量模型 → 按时间倒序取最近 top_k，按关联标注来源。

        Args:
            user_id: 用户 ID
            conversation_id: 关联会话 ID（可选）
            job_id: 关联职位 ID（可选）
            top_k: 返回结果数量

        Returns:
            加权排序后的上下文记忆列表
        """
        query_vector = await self._generate_embedding(user_id, "")  # TODO: 用任务摘要生成 query

        if query_vector is None:
            # 降级：无向量可用，时间倒序最近记忆 + 来源标注
            return await self._recent_context(user_id, conversation_id, job_id, top_k)

        # 并行检索三个上下文级别，减少 IO 等待
        results_conv, results_job, results_global = await self._search_three_tiers(
            user_id,
            query_vector,
            conversation_id,
            job_id,
            per_level_limit=top_k,
        )

        # 转换为带权重的中间结构
        conv_items = self._weight_results(results_conv, WEIGHT_CONVERSATION, "conversation")
        job_items = self._weight_results(results_job, WEIGHT_JOB, "job")
        global_items = self._weight_results(results_global, WEIGHT_GLOBAL, "global")

        # 加权合并 + 去重 + 排序
        ranked = self._rank_memories(conv_items, job_items, global_items, top_k)

        self.logger.info(
            "memory_context_retrieved",
            user_id=user_id,
            conversation_id=conversation_id,
            job_id=job_id,
            conv_count=len(conv_items),
            job_count=len(job_items),
            global_count=len(global_items),
            final_count=len(ranked),
        )

        return ranked

    async def _search_three_tiers(
        self,
        user_id: int,
        query_vector: list[float],
        conversation_id: int | None,
        job_id: int | None,
        per_level_limit: int,
    ) -> tuple[
        list[tuple[MemoryModel, float]],
        list[tuple[MemoryModel, float]],
        list[tuple[MemoryModel, float]],
    ]:
        """并行检索三级记忆。

        三级并行检索，减少总等待时间：
        - conversation 级：仅匹配 conversation_id（如果提供）
        - job 级：仅匹配 job_id（如果提供），排除 conversation 级已包含的
        - global 级：无关联上下文，排除前两级已包含的

        每级独立检索 Top-per_level_limit，后续合并后再截断。
        """
        results_conv: list[tuple[MemoryModel, float]] = []
        results_job: list[tuple[MemoryModel, float]] = []

        # Level 1: 会话级记忆（权重最高）
        if conversation_id is not None:
            results_conv = await self.memory_repo.semantic_search(
                user_id=user_id,
                query_vector=query_vector,
                limit=per_level_limit,
                conversation_id=conversation_id,
            )

        # Level 2: 岗位级记忆（排除会话级已包含的）
        conv_ids = {m.id for m, _ in results_conv}
        if job_id is not None:
            results_job_raw = await self.memory_repo.semantic_search(
                user_id=user_id,
                query_vector=query_vector,
                limit=per_level_limit + len(conv_ids),
                job_id=job_id,
            )
            # 排除会话级已包含的
            results_job = [(m, d) for m, d in results_job_raw if m.id not in conv_ids]

        # Level 3: 全局记忆（排除前两级已包含的）
        job_ids = {m.id for m, _ in results_job}
        existing_ids = conv_ids | job_ids

        results_global_raw = await self.memory_repo.semantic_search(
            user_id=user_id,
            query_vector=query_vector,
            limit=per_level_limit + len(existing_ids),
        )
        # 排除前两级已包含的
        results_global = [(m, d) for m, d in results_global_raw if m.id not in existing_ids]

        return (results_conv, results_job, results_global)

    def _weight_results(
        self,
        results: list[tuple[MemoryModel, float]],
        weight: float,
        source: str,
    ) -> list[dict[str, Any]]:
        """为检索结果添加权重和来源标记。

        计算加权相似度：weighted_similarity = (1 - distance) * weight
        其中 distance 是 pgvector 返回的余弦距离（0~2）。

        Args:
            results: (Memory, cosine_distance) 元组列表
            weight: 该级别的权重系数
            source: 来源标记（conversation/job/global）

        Returns:
            带权重标记的中间结果字典列表
        """
        items: list[dict[str, Any]] = []
        for memory, distance in results:
            raw_similarity = 1.0 - distance  # 转换为余弦相似度 0~1
            weighted_similarity = raw_similarity * weight
            items.append(
                {
                    "memory": memory,
                    "raw_similarity": raw_similarity,
                    "weighted_similarity": weighted_similarity,
                    "weight": weight,
                    "source": source,
                }
            )
        return items

    def _rank_memories(
        self,
        conversation_items: list[dict[str, Any]],
        job_items: list[dict[str, Any]],
        global_items: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """三级记忆加权排序。

        合并策略：
        1. 将三个级别的结果合并为一个池
        2. 去重：相同内容的记忆只保留加权相似度最高的版本
        3. 按加权相似度降序排序
        4. 截断取 Top-k

        去重保证：即使同一条记忆被多级检索命中（如同时关联 conversation 和 job），
        也只保留权重最高的一个版本，避免重复注入上下文。

        Args:
            conversation_items: 会话级加权结果
            job_items: 岗位级加权结果
            global_items: 全局级加权结果
            top_k: 返回数量上限

        Returns:
            排序后的记忆上下文列表，包含原始记忆字段 + 元数据
        """
        # 合并所有结果
        all_items = conversation_items + job_items + global_items

        # 去重：相同 content 保留加权相似度最高的版本
        deduped: dict[str, dict[str, Any]] = {}
        for item in all_items:
            content = item["memory"].content
            if content not in deduped or item["weighted_similarity"] > deduped[content]["weighted_similarity"]:
                deduped[content] = item

        # 按加权相似度降序排序
        ranked = sorted(
            deduped.values(),
            key=lambda x: x["weighted_similarity"],
            reverse=True,
        )

        # 截断取 Top-k
        final_items = ranked[:top_k]

        # 转换为最终响应格式（注入 Planner 的格式）
        result: list[dict[str, Any]] = []
        for item in final_items:
            memory: MemoryModel = item["memory"]
            result.append(
                {
                    "id": memory.id,
                    "type": memory.type,
                    "content": memory.content,
                    "source": item["source"],
                    "raw_similarity": round(item["raw_similarity"], 4),
                    "weighted_similarity": round(item["weighted_similarity"], 4),
                    "weight": item["weight"],
                }
            )

        return result

    async def _recent_context(
        self,
        user_id: int,
        conversation_id: int | None,
        job_id: int | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """降级路径：任务上下文检索。

        未配置向量模型时无相似度可算，改按时间倒序取最近 top_k 条，
        按关联标注来源（conversation > job > global），与 _rank_memories
        输出结构一致（相似度/权重置 None 以示「无语义分数」）。
        """
        memories = await self.memory_repo.list_recent(user_id, limit=top_k)
        result: list[dict[str, Any]] = []
        for m in memories:
            if conversation_id is not None and m.conversation_id == conversation_id:
                source = "conversation"
            elif job_id is not None and m.job_id == job_id:
                source = "job"
            else:
                source = "global"
            result.append(
                {
                    "id": m.id,
                    "type": m.type,
                    "content": m.content,
                    "source": source,
                    "raw_similarity": None,
                    "weighted_similarity": None,
                    "weight": None,
                }
            )
        return result

    async def list_by_conversation(
        self, user_id: int, conversation_id: int, limit: int = 50
    ) -> list[MemoryResponse]:
        """列出会话关联的所有记忆。

        注意：这里不做语义排序，按创建时间倒序返回。
        """
        memories = await self.memory_repo.list_by_conversation(conversation_id, limit=limit)
        # 权限校验：只能返回该用户的记忆
        user_memories = [m for m in memories if m.user_id == user_id]
        return [self._to_response(m) for m in user_memories]

    async def list_by_job(self, user_id: int, job_id: int, limit: int = 50) -> list[MemoryResponse]:
        """列出岗位关联的所有记忆。

        注意：这里不做语义排序，按创建时间倒序返回。
        """
        memories = await self.memory_repo.list_by_job(job_id, limit=limit)
        # 权限校验：只能返回该用户的记忆
        user_memories = [m for m in memories if m.user_id == user_id]
        return [self._to_response(m) for m in user_memories]

    @transactional
    async def delete(self, user_id: int, memory_id: int) -> None:
        """删除记忆。

        目前是硬删除（直接从 DB 移除），未来可考虑软删除方案。

        权限校验：只能删除属于该用户的记忆。

        Args:
            user_id: 操作用户 ID（权限校验用）
            memory_id: 待删除记忆 ID

        Raises:
            NotFoundError: 记忆不存在
            ForbiddenError: 记忆不属于该用户
        """
        memory = await self.memory_repo.get(memory_id)
        if memory is None:
            msg = f"Memory {memory_id} not found"
            self.logger.warning(
                "memory_delete_not_found",
                user_id=user_id,
                memory_id=memory_id,
            )
            raise NotFoundError(msg)

        if memory.user_id != user_id:
            msg = f"Memory {memory_id} does not belong to user {user_id}"
            self.logger.warning(
                "memory_delete_forbidden",
                user_id=user_id,
                memory_id=memory_id,
                owner_id=memory.user_id,
            )
            raise ForbiddenError(msg)

        await self.memory_repo.delete(memory_id)

        self.logger.info(
            "memory_deleted",
            user_id=user_id,
            memory_id=memory_id,
            memory_type=memory.type,
        )

    async def extract_and_save(
        self,
        user_id: int,
        conversation_id: int,
        job_id: int | None,
        messages: list[dict[str, Any]],
    ) -> int:
        """从任务执行记录中提取长期记忆并保存。

        需调用 LLM 从对话历史中提取需要长期保留的事实（用户偏好、
        HR 约定、历史决策等）。

        Raises:
            NotImplementedError: 提取依赖 LLM 记忆提取管线，当前未实现。
                此前占位返回「新增 0 条」属静默假成功，改为明确抛错（501）。

        Args:
            user_id: 关联用户 ID
            conversation_id: 关联会话 ID
            job_id: 关联职位 ID
            messages: 对话历史消息列表

        Returns:
            新增记忆数量
        """
        self.logger.debug(
            "memory_extract_not_implemented",
            user_id=user_id,
            conversation_id=conversation_id,
            job_id=job_id,
            message_count=len(messages),
        )
        msg = "LLM 记忆提取功能尚未实现"
        raise NotImplementedError(msg)

    async def _generate_embedding(self, user_id: int, text: str) -> list[float] | None:
        """生成文本 embedding 向量（512 维）；未配置向量模型时返回 None。

        配置来源（方案 A）：优先读进程内活动配置注册表（扩展推送的明文 key）；
        注册表为空回退 DB（过渡期不回归）。

        降级触发条件（任一命中即返回 None，不抛异常，由调用方降级）：
        - 未配置 api_key / model（记忆功能照常可用，仅无语义检索）
        - 调用 embedding API 失败（网络 / HTTP 错误，容错外部服务不可用）
        - 返回向量维度 != 512（与记忆库 Vector(512) 不一致，防脏向量入库）

        Args:
            user_id: 关联用户（配置按用户隔离，读 DB 需要）
            text: 待向量化的文本

        Returns:
            512 维浮点向量；不可用时 None
        """
        from app.core.active_config_registry import get_active_config
        from app.service.setting import SettingsService

        # 方案 A：优先读注册表；为空回退已存 DB 配置
        current = get_active_config("embedding")
        if not current.get("api_key"):
            current = await SettingsService(self.db).get_embedding_runtime_config(user_id)

        api_key = current.get("api_key")
        model = current.get("model")
        if not api_key or not model:
            self.log_with_context(logging.DEBUG, "embedding_not_configured", user_id=user_id)
            return None

        try:
            vector = await generate_embedding(
                api_key=str(api_key),
                base_url=current.get("base_url"),
                model=str(model),
                text=text,
            )
        except EmbeddingError as exc:
            # 外部服务失败属预期容错：降级而非中断记忆写入/检索
            self.log_with_context(
                logging.WARNING,
                "embedding_generation_failed",
                user_id=user_id,
                error=str(exc),
            )
            return None

        if len(vector) != EMBEDDING_DIM:
            self.log_with_context(
                logging.WARNING,
                "embedding_dimension_mismatch",
                user_id=user_id,
                expected=EMBEDDING_DIM,
                actual=len(vector),
            )
            return None

        return vector
