"""service 编排测试：mock adapter/job_service/settings_service，不连真实浏览器。

约定：skills/ 独立可测，不依赖 pytest-asyncio —— 用 asyncio.run 包装同步测试函数。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from job_fit import JobRules
from service import BossExtractService, SkillResult


# ---------------------------------------------------------------------------
# mock 基建
# ---------------------------------------------------------------------------
class FakeResult:
    """ToolResult 替身。"""

    def __init__(self, ok: bool = True, data: dict | None = None, error: str | None = None) -> None:
        self.ok = ok
        self.data = data
        self.error = error


def make_adapter(*, script_result: FakeResult | None = None, web_content_result: FakeResult | None = None) -> AsyncMock:
    adapter = AsyncMock()

    async def call_tool(name: str, args: dict | None = None) -> FakeResult:  # noqa: ARG001
        if name == "chrome_javascript":
            return script_result or FakeResult(ok=False, error="script_result 未配置")
        if name == "chrome_get_web_content":
            return web_content_result or FakeResult(ok=False, error="web_content_result 未配置")
        return FakeResult(ok=False, error=f"意外工具: {name}")

    adapter.call_tool.side_effect = call_tool
    return adapter


def make_job_service() -> tuple[AsyncMock, list[dict]]:
    js = AsyncMock()
    created_payloads: list[dict] = []

    async def fake_create(_user_id: int, payload: dict) -> dict:
        created_payloads.append(payload)
        return {"id": len(created_payloads), "external_id": payload["external_id"]}

    js.create.side_effect = fake_create
    return js, created_payloads


def make_settings_service(*, min_salary: int | None = 20, preferred_locations: list[str] | None = None) -> AsyncMock:
    if preferred_locations is None:
        preferred_locations = ["北京"]
    ss = AsyncMock()
    ss.get_job_rule = AsyncMock(
        return_value=SimpleNamespace(
            min_salary=min_salary,
            max_salary=None,
            preferred_locations=preferred_locations,
            overtime_allowed=False,
            outsourcing_allowed=False,
            offsite_allowed=False,
        )
    )
    return ss


# 三岗位样例：j1 通过；j2 命中外包；j3 薪资低于下限
JOBS = [
    {
        "external_id": "j1",
        "title": "后端工程师",
        "company": "A公司",
        "salary": "25-35K",
        "location": "北京·海淀",
        "welfare_list": [],
        "tags": [],
    },
    {
        "external_id": "j2",
        "title": "外包前端",
        "company": "人力服务",
        "salary": "30-40K",
        "location": "北京·朝阳",
        "welfare_list": [],
        "tags": [],
    },
    {
        "external_id": "j3",
        "title": "运维工程师",
        "company": "C公司",
        "salary": "18-20K",
        "location": "上海·浦东",
        "welfare_list": [],
        "tags": [],
    },
]


# ---------------------------------------------------------------------------
# 全链路（page 提取 → 筛选 → 落库）
# ---------------------------------------------------------------------------
def test_run_page_vue_full_chain() -> None:
    async def scenario() -> SkillResult:
        js, _ = make_job_service()
        adapter = make_adapter(
            script_result=FakeResult(ok=True, data={"ok": True, "jobs": JOBS, "source": "vue", "warnings": []})
        )
        svc = BossExtractService(adapter=adapter, job_service=js, settings_service=make_settings_service())
        return await svc.run(1)

    res = asyncio.run(scenario())
    assert res.ok is True
    data = res.data or {}
    assert data["extracted"] == 3
    assert data["source"] == "vue"
    assert data["passed"] == 1  # 仅 j1
    assert len(data["dropped"]) == 2
    assert data["ingested"] == [1]


def test_run_payload_contains_score_detail() -> None:
    async def scenario() -> None:
        js, created = make_job_service()
        svc = BossExtractService(job_service=js, settings_service=make_settings_service())
        await svc.run(1, source="raw", jobs=JOBS)

        assert len(created) == 1
        payload = created[0]
        assert payload["platform"] == "boss"
        assert payload["external_id"] == "j1"
        assert payload["hr_id"] is None
        sd = payload["score_detail"]
        assert sd["llm_score"] is None
        assert sd["llm_reason"] is None
        assert "salary" in sd["keyword_hits"]
        assert sd["keyword_score"] == 100.0
        assert sd["deductions"] == []

    asyncio.run(scenario())


def test_run_ingest_false_skips_create() -> None:
    js, _ = make_job_service()

    async def scenario() -> SkillResult:
        svc = BossExtractService(job_service=js, settings_service=make_settings_service())
        return await svc.run(1, source="raw", jobs=JOBS, ingest=False)

    res = asyncio.run(scenario())
    assert res.ok is True
    assert res.data["ingested"] == []
    assert js.create.await_count == 0  # ingest=False 时不落库


# ---------------------------------------------------------------------------
# raw 输入 + rules_override
# ---------------------------------------------------------------------------
def test_run_raw_with_rules_override_skips_settings() -> None:
    async def scenario() -> SkillResult:
        js, _ = make_job_service()
        ss = AsyncMock()
        ss.get_job_rule = AsyncMock(side_effect=AssertionError("不应读取 Settings"))
        svc = BossExtractService(job_service=js, settings_service=ss)
        return await svc.run(
            1,
            source="raw",
            jobs=JOBS,
            rules_override=JobRules(min_salary_k=20, preferred_locations=["北京"]),
        )

    res = asyncio.run(scenario())
    assert res.ok is True
    assert res.data["passed"] == 1


def test_run_raw_empty_jobs_fails() -> None:
    async def scenario() -> SkillResult:
        svc = BossExtractService()
        return await svc.run(1, source="raw", jobs=[])

    res = asyncio.run(scenario())
    assert res.ok is False
    assert "未提取到任何岗位" in (res.error or "")


# ---------------------------------------------------------------------------
# 浏览器提取降级
# ---------------------------------------------------------------------------
def test_run_chrome_javascript_fallback_to_dom() -> None:
    html = (
        '<li class="job-card-box">'
        '<a class="job-name" href="/job_detail/dom1.html">Python工程师</a>'
        '<a class="boss-info"><div class="boss-name">某公司</div></a>'
        '<span class="company-location">北京·朝阳</span>'
        "</li>"
    )
    adapter = make_adapter(
        script_result=FakeResult(ok=False, error="高危工具 chrome_javascript 需授权"),
        web_content_result=FakeResult(ok=True, data={"title": "t", "url": "u", "text": "", "html": html}),
    )
    js, _ = make_job_service()

    async def scenario() -> SkillResult:
        svc = BossExtractService(adapter=adapter, job_service=js, settings_service=make_settings_service())
        return await svc.run(1)

    res = asyncio.run(scenario())
    assert res.ok is True
    data = res.data or {}
    assert data["source"] == "dom"
    assert data["extracted"] == 1
    assert data["passed"] == 1
    assert data["ingested"] == [1]
    assert any("DOM 兜底" in w for w in data["warnings"])
    # 落库载荷里薪资为空 + warning 已注明
    assert (js.create.call_args.args[1]["salary"]) is None


def test_run_page_extract_empty_returns_error() -> None:
    adapter = make_adapter(
        script_result=FakeResult(ok=True, data={"ok": True, "jobs": [], "source": "vue", "warnings": []})
    )

    async def scenario() -> SkillResult:
        svc = BossExtractService(adapter=adapter, settings_service=make_settings_service())
        return await svc.run(1)

    res = asyncio.run(scenario())
    assert res.ok is False
    # error 上抛根因（页面无卡片），而非泛化的「未提取到任何岗位」
    assert "页面无岗位卡片" in (res.error or "")


def test_run_page_without_adapter_errors() -> None:
    async def scenario() -> SkillResult:
        svc = BossExtractService()  # 未接线 adapter
        return await svc.run(1)

    res = asyncio.run(scenario())
    assert res.ok is False
    assert "浏览器适配器未接线" in (res.error or "")


def test_run_page_script_reads_real_js() -> None:
    """验证 extract-jobs.js 被真实读取并传给 chrome_javascript。"""
    adapter = make_adapter(
        script_result=FakeResult(ok=True, data={"ok": True, "jobs": JOBS, "source": "vue", "warnings": []})
    )

    async def scenario() -> SkillResult:
        svc = BossExtractService(adapter=adapter, settings_service=make_settings_service())
        return await svc.run(1)

    asyncio.run(scenario())
    call = adapter.call_tool.await_args_list[0]
    assert call.args[0] == "chrome_javascript"
    code = call.args[1]["code"]
    assert "jobList" in code
    assert "job-card-box" in code


# ---------------------------------------------------------------------------
# 单条落库失败不中断
# ---------------------------------------------------------------------------
def test_ingest_single_failure_does_not_break() -> None:
    # 用两条「默认规则下都通过」的干净岗位（JOBS 里的 j2 是外包，会被硬筛掉）
    clean = [
        {
            "external_id": "c1",
            "title": "后端工程师",
            "company": "A公司",
            "salary": "25-35K",
            "location": "北京·海淀",
            "welfare_list": [],
            "tags": [],
        },
        {
            "external_id": "c2",
            "title": "算法工程师",
            "company": "B公司",
            "salary": "30-40K",
            "location": "北京·朝阳",
            "welfare_list": [],
            "tags": [],
        },
    ]

    async def scenario() -> SkillResult:
        js = AsyncMock()

        async def flaky_create(_user_id: int, payload: dict) -> dict:
            if payload["external_id"] == "c1":
                db_error = "DB 连接断开"
                raise RuntimeError(db_error)
            return {"id": 9, "external_id": payload["external_id"]}

        js.create.side_effect = flaky_create
        svc = BossExtractService(job_service=js, settings_service=make_settings_service())
        return await svc.run(1, source="raw", jobs=clean, rules_override=JobRules())

    res = asyncio.run(scenario())
    assert res.ok is True  # 整体不因单条失败而中断
    data = res.data or {}
    assert len(data["errors"]) == 1
    assert data["errors"][0]["external_id"] == "c1"
    assert data["ingested"] == [9]


# ---------------------------------------------------------------------------
# limit 截断
# ---------------------------------------------------------------------------
def test_run_respects_limit() -> None:
    many_jobs = [
        {
            "external_id": f"j{i}",
            "title": "岗位",
            "company": "公司",
            "salary": "25-35K",
            "location": "北京·海淀",
            "welfare_list": [],
            "tags": [],
        }
        for i in range(20)
    ]

    async def scenario() -> SkillResult:
        js, _ = make_job_service()
        svc = BossExtractService(job_service=js, settings_service=make_settings_service())
        return await svc.run(1, source="raw", jobs=many_jobs, rules_override=JobRules(), limit=5)

    res = asyncio.run(scenario())
    assert res.data["extracted"] == 5
