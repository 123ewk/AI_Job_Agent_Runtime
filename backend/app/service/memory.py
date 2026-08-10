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

from app.models.memory import Memory as MemoryModel
from app.repository.memory import MemoryRepository
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

        去重逻辑：
        1. 对新内容生成 embedding
        2. 检索用户记忆中与新内容相似度 > 0.95 的条目
        3. 存在则跳过并返回现有记忆，否则写入新记忆

        Args:
            user_id: 关联用户 ID
            data: 记忆创建请求

        Returns:
            新建或已存在的记忆响应
        """
        # 生成 embedding 向量
        embedding = await self._generate_embedding(data.content)

        # 去重检查：检索高相似度记忆
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

        先向量化 query，然后 pgvector 余弦相似度 Top-K，
        支持按 conversation_id / job_id / memory_type 过滤。

        注意：返回的 similarity_score 是余弦相似度（0~1），值越大越相似。
        pgvector 的 cosine_distance = 1 - cosine_similarity。

        Args:
            user_id: 检索用户范围
            request: 检索请求（query + 过滤条件）

        Returns:
            按相似度排序的记忆列表
        """
        query_vector = await self._generate_embedding(request.query)

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

        Args:
            user_id: 用户 ID
            conversation_id: 关联会话 ID（可选）
            job_id: 关联职位 ID（可选）
            top_k: 返回结果数量

        Returns:
            加权排序后的上下文记忆列表
        """
        query_vector = await self._generate_embedding("")  # TODO: 用任务摘要生成 query

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
            ValueError: 记忆不存在或不属于该用户
        """
        memory = await self.memory_repo.get(memory_id)
        if memory is None:
            msg = f"Memory {memory_id} not found"
            self.logger.warning(
                "memory_delete_not_found",
                user_id=user_id,
                memory_id=memory_id,
            )
            raise ValueError(msg)

        if memory.user_id != user_id:
            msg = f"Memory {memory_id} does not belong to user {user_id}"
            self.logger.warning(
                "memory_delete_forbidden",
                user_id=user_id,
                memory_id=memory_id,
                owner_id=memory.user_id,
            )
            raise ValueError(msg)

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

        TODO: 调用 LLM 从对话历史中提取需要长期保留的事实：
        - 用户偏好（薪资期望、地点、公司类型等）
        - HR 约定（面试时间、流程等）
        - 历史决策（已拒绝/接受的岗位）
        - 其他长期有效的信息

        目前为占位实现，仅记录日志，不做实际提取。

        Args:
            user_id: 关联用户 ID
            conversation_id: 关联会话 ID
            job_id: 关联职位 ID
            messages: 对话历史消息列表

        Returns:
            新增记忆数量（当前始终返回 0）
        """
        self.logger.debug(
            "memory_extract_stub",
            user_id=user_id,
            conversation_id=conversation_id,
            job_id=job_id,
            message_count=len(messages),
        )
        # TODO: 实现 LLM 记忆提取逻辑
        return 0

    async def _generate_embedding(self, text: str) -> list[float]:
        """生成文本 embedding 向量。

        使用 bge-small-zh-v1.5 模型，512 维。

        TODO: 当前为占位实现，返回零向量。
        未来集成 sentence-transformers 或 OpenAI/火山引擎 embedding API。

        实现注意：
        1. 文本长度截断（bge-small-zh 最大 512 tokens）
        2. 批量生成时考虑速率限制
        3. 结果需要 L2 归一化，保证 pgvector 余弦距离计算正确

        Args:
            text: 待向量化的文本

        Returns:
            512 维浮点向量，L2 归一化
        """
        # TODO: 替换为真实 embedding 调用
        # 占位实现：返回 512 维零向量
        # 注意：pgvector 需要 L2 归一化的向量才能正确计算余弦相似度
        self.log_with_context(
            logging.DEBUG,
            "embedding_generation_stub",
            text_len=len(text),
        )
        return [0.0] * 512
