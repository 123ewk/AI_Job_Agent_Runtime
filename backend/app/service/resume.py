"""简历业务服务。

负责简历元数据与解析文本的 CRUD、默认简历管理（is_default 唯一性）。

跨域协作：
- 结构化摘要 + embedding 存 ResumeSummary 表（多版本），V1 阶段 Agent
  摘要/向量化管线尚未接线，因此创建时不写摘要行，summary_preview 恒为 None。
- 文件上传（MinIO）与文档解析管线未接线，V1 以解析后文本 content 入库。

设计取舍：
- 首个简历自动 is_default=True（用户无需手动设置即有默认简历投递用）。
- set_default 先清空再置顶：保证任何时刻至多一份默认简历，避免并发下
  多条 is_default 同时为 True（投递时 get_default 取第一条，语义错乱）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repository.resume import ResumeRepository
from app.schema.common import PaginatedResponse
from app.schema.resume import ResumeCreate, ResumeDetailResponse, ResumeResponse
from app.service.base import BaseService, transactional


class ResumeService(BaseService):
    """简历业务服务。

    职责：
    - 简历 CRUD（元数据 + 解析文本）
    - 默认简历唯一性管理
    - 版本号管理（V1 固定 version=1，多版本更新待摘要管线接线后启用）
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db)
        self.resume_repo = ResumeRepository(db)

    @transactional
    async def create(self, user_id: int, data: ResumeCreate) -> ResumeResponse:
        """创建简历。

        首个简历自动设为默认；V1 不生成摘要/向量（Agent 摘要管线未接线），
        不写 ResumeSummary 假行，summary_preview 保持 None。
        """
        existing_count = await self.resume_repo.count_by_filter({"user_id": user_id})

        resume_data = data.model_dump(exclude_unset=True)
        resume_data["user_id"] = user_id
        resume_data["version"] = 1
        resume_data["is_default"] = existing_count == 0

        resume = await self.resume_repo.create(resume_data)
        self.logger.info(
            "resume_created",
            extra={"user_id": user_id, "resume_id": resume.id, "name": resume.name},
        )
        return ResumeResponse.model_validate(resume, from_attributes=True)

    async def get(self, user_id: int, resume_id: int) -> ResumeDetailResponse:
        """获取简历详情（含解析原文）。"""
        resume = await self.resume_repo.get_by_unique(id=resume_id, user_id=user_id)
        if not resume:
            raise NotFoundError(f"简历不存在: {resume_id}")
        return ResumeDetailResponse.model_validate(resume, from_attributes=True)

    async def list(
        self, user_id: int, page: int = 1, page_size: int = 20
    ) -> PaginatedResponse[ResumeResponse]:
        """获取用户简历列表（按更新时间倒序）。"""
        resumes, total = await self.resume_repo.list_by_filter_with_count(
            {"user_id": user_id},
            page=page,
            page_size=page_size,
        )
        items = [ResumeResponse.model_validate(r, from_attributes=True) for r in resumes]
        return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)

    @transactional
    async def set_default(self, user_id: int, resume_id: int) -> ResumeResponse:
        """将简历设为默认（投递用）。

        先清空用户全部 is_default 再置顶当前简历，保证唯一性。
        """
        resume = await self.resume_repo.get_by_unique(id=resume_id, user_id=user_id)
        if not resume:
            raise NotFoundError(f"简历不存在: {resume_id}")

        await self.resume_repo.clear_default(user_id)
        await self.resume_repo.update(resume_id, {"is_default": True})

        updated = await self.resume_repo.get_by_unique(id=resume_id, user_id=user_id)
        assert updated is not None  # 刚校验过存在且未删除
        self.logger.info("resume_set_default", extra={"user_id": user_id, "resume_id": resume_id})
        return ResumeResponse.model_validate(updated, from_attributes=True)

    @transactional
    async def delete(self, user_id: int, resume_id: int) -> None:
        """删除简历（硬删除，关联摘要随外键 CASCADE）。"""
        resume = await self.resume_repo.get_by_unique(id=resume_id, user_id=user_id)
        if not resume:
            raise NotFoundError(f"简历不存在: {resume_id}")

        await self.resume_repo.delete(resume_id)
        self.logger.info("resume_deleted", extra={"user_id": user_id, "resume_id": resume_id})
