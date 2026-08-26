"""记忆管理路由。

提供记忆检索、添加、删除功能。
记忆是 Agent 的长期上下文，按三级加权检索：
- conversation: 1.0（当前会话）
- job: 0.7（关联岗位）
- global: 0.4（全局偏好）

语义相似度由 pgvector 余弦相似度计算。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, MemoryServiceDep
from app.core.logging import get_logger
from app.schema.common import StatusResponse
from app.schema.memory import MemoryCreate, MemoryResponse, MemorySearchRequest

router = APIRouter(prefix="/memory", tags=["memory"])
logger = get_logger("app.api.memory")


@router.post("/search", response_model=list[MemoryResponse])
async def search_memory(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    request: MemorySearchRequest,
) -> list[MemoryResponse]:
    """语义检索记忆。

    输入查询文本，返回最相关的记忆列表。
    支持按会话、岗位过滤。

    去重策略：
    - 相似度 > 0.95 的记忆视为重复，只保留最高权重版本
    - 三级检索结果合并后按加权相似度排序
    """
    return await service.search(user_id, request)


@router.post("", response_model=MemoryResponse, status_code=201)
async def add_memory(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    data: MemoryCreate,
) -> MemoryResponse:
    """添加新记忆。

    自动生成 embedding 向量并做去重检查。
    相似度过高（> 0.95）的记忆会跳过写入，
    直接返回现有记忆（避免重复保存相同事实）。

    记忆类型：
    - fact: 事实性记忆（HR 要求、公司信息等）
    - preference: 用户偏好（语气、风格、薪资要求等）
    - history: 历史交互记录
    """
    return await service.add(user_id, data)


@router.get("/conversation/{conversation_id}", response_model=list[MemoryResponse])
async def list_conversation_memory(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    conversation_id: int,
    limit: int = Query(50, ge=1, le=500, description="记忆数量上限"),
) -> list[MemoryResponse]:
    """获取某会话关联的记忆。"""
    return await service.list_by_conversation(user_id, conversation_id, limit=limit)


@router.get("/job/{job_id}", response_model=list[MemoryResponse])
async def list_job_memory(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    job_id: int,
    limit: int = Query(50, ge=1, le=500, description="记忆数量上限"),
) -> list[MemoryResponse]:
    """获取某岗位关联的记忆。"""
    return await service.list_by_job(user_id, job_id, limit=limit)


@router.delete("/{memory_id}", response_model=StatusResponse)
async def delete_memory(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    memory_id: int,
) -> StatusResponse:
    """删除记忆。

    当前为硬删除，V2 可实现软删除保留审计记录。
    """
    await service.delete(user_id, memory_id)
    return StatusResponse(status="ok", message="记忆已删除")


@router.post("/context/for-task/{task_id}")
async def get_context_for_task(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    task_id: int,
) -> dict:
    """获取任务执行所需的记忆上下文。

    三级加权检索，返回合并后的记忆列表和统计信息。
    供 Agent Runtime 在任务启动时注入上下文。
    """
    # task_id 解析为 conversation_id / job_id，再按三级策略检索
    from app.repository.task import TaskRepository

    task_repo = TaskRepository(service.db)
    task = await task_repo.get(task_id)
    conversation_id = task.conversation_id if task else None
    job_id = task.job_id if task else None

    memories = await service.get_context_for_task(
        user_id,
        conversation_id=conversation_id,
        job_id=job_id,
        top_k=20,
    )
    return {
        "count": len(memories),
        "memories": memories,
        "levels": {
            "conversation": sum(1 for m in memories if m.get("source") == "conversation"),
            "job": sum(1 for m in memories if m.get("source") == "job"),
            "global": sum(1 for m in memories if m.get("source") == "global"),
        },
    }


@router.post("/extract", response_model=StatusResponse)
async def extract_and_save_memory(
    user_id: CurrentUserDep,
    service: MemoryServiceDep,
    conversation_id: int,
) -> StatusResponse:
    """从会话历史中提取新记忆。

    LLM 分析会话历史，提取事实性信息和用户偏好，
    去重后写入记忆库。供任务完成后自动调用。
    """
    # job_id 与 messages 由调用方（任务完成回调）传入；此入口暂以空值占位，
    # service.extract_and_save 当前为 stub，始终返回 0。
    count = await service.extract_and_save(user_id, conversation_id, job_id=None, messages=[])
    return StatusResponse(status="ok", message=f"提取完成，新增 {count} 条记忆")
