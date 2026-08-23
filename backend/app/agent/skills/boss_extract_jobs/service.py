"""垂直工具 boss.extract_jobs 的编排服务：提取 → 筛选 → 落库。

设计（对齐 doc 08 Boss Skill 契约 + memory/job-data-pipeline）：
- 自包含：与 backend/ 解耦（本文件不 import backend 任何模块），依赖全部经构造参数注入。
- 提取：主路径 chrome_javascript 注入同目录 extract-jobs.js（读 Vue $data.jobList，
  零新增 zhipin 请求）；失败走 chrome_get_web_content DOM 兜底（best-effort，薪资置空）。
- 筛选：job_fit.evaluate 确定性预筛（硬规则 + keyword_score）。
- 落库：job_service.create(user_id, JobCreate 形状 dict) 幂等去重；
  score_detail 写入 keyword 部分，llm_* 留空（LLM 评分由后续 boss.score_job 补齐）。

返回：SkillResult{ok, data, error}，对齐 doc 08。
data = {
  extracted: int, source: "vue"|"dom"|"raw", warnings: list,
  passed: int, dropped: [{external_id, reason}],
  ingested: list, errors: [{external_id, error}],
}

接线点（未来 doc 06 skill_router / tool_executor 注入）：
- settings_service：注入 backend SettingsService（get_job_rule -> JobRuleConfigResponse）
- job_service：注入 backend JobService 的薄封装，create(user_id, payload_dict) 内部做
  JobCreate（去 score_detail）-> create，再 JobUpdate(score_detail) -> update
- adapter：注入 backend BrowserToolAdapter（call_tool 含浏览器锁/超时/审计）
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

try:  # 包内导入（skills 作为包被加载时）
    from .job_fit import JobFitResult, JobRules, evaluate
except ImportError:  # 独立运行（tests conftest 注入 sys.path 后）
    from job_fit import JobFitResult, JobRules, evaluate  # type: ignore

logger = logging.getLogger("boss_extract_jobs")

PLATFORM = "boss"
SCRIPT_PATH = Path(__file__).with_name("extract-jobs.js")

# chrome_get_web_content 兜底：解析 html 里的岗位卡片（反爬字体，薪资置空）
_CARD_RE = re.compile(r'<li[^>]*class="[^"]*job-card-box[^"]*"[^>]*>(.*?)</li>', re.IGNORECASE | re.DOTALL)
_JOB_HREF_RE = re.compile(r"job_detail/([^/\"'<>?#\s]+)\.html")
_RE_JOB_NAME = re.compile(r'<a[^>]*class="[^"]*job-name[^"]*"[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)
_RE_BOSS_NAME = re.compile(r'<a[^>]*class="[^"]*boss-name[^"]*"[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)
_RE_COMPANY_LOCATION = re.compile(
    r'<span[^>]*class="[^"]*company-location[^"]*"[^>]*>.*?</span>', re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


@dataclass
class SkillResult:
    """垂直工具统一返回（对齐 doc 08 SkillResult{ok, data, error}）。"""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class JobServiceLike(Protocol):
    """job_service 注入契约（duck-typing）。

    实际注入对象不必继承本类，只需实现 create(user_id, payload_dict) -> dict|object。
    接线时由集成层把 backend JobService 包成该形状（内部 create + update 写 score_detail）。
    """

    async def create(self, user_id: int, payload: dict[str, Any]) -> object: ...


# ---------------------------------------------------------------------------
# DOM 兜底解析（chrome_get_web_content 返回 {title,url,text,html}）
# ---------------------------------------------------------------------------
def _text_of(card_html: str, el_re: re.Pattern[str]) -> str | None:
    m = el_re.search(card_html)
    if not m:
        return None
    t = _TAG_RE.sub("", m.group(0))
    t = _SPACE_RE.sub(" ", t).strip()
    return t or None


def _parse_dom_html(html: str) -> list[dict[str, Any]]:
    """从 outerHTML 解析 li.job-card-box 卡片。best-effort，薪资置空。"""
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in _CARD_RE.findall(html or ""):
        href_m = _JOB_HREF_RE.search(card)
        if not href_m:
            continue
        external_id = href_m.group(1)
        if external_id in seen:  # 去重（同一卡片可能被外层重复匹配）
            continue
        seen.add(external_id)
        jobs.append(
            {
                "external_id": external_id,
                "title": _text_of(card, _RE_JOB_NAME),
                "company": _text_of(card, _RE_BOSS_NAME),
                "salary": None,  # DOM 薪资为反爬字体，勿入库
                "location": _text_of(card, _RE_COMPANY_LOCATION),
                "source_url": f"https://www.zhipin.com/job_detail/{external_id}.html",
                "welfare_list": [],
                "tags": [],
            }
        )
    return jobs


def _parse_dom_text(text: str) -> list[dict[str, Any]]:
    """html 不可用时仅能取 external_id + source_url（标题等字段缺失）。"""
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _JOB_HREF_RE.finditer(text or ""):
        ext = m.group(1)
        if ext in seen:
            continue
        seen.add(ext)
        jobs.append(
            {
                "external_id": ext,
                "title": None,
                "company": None,
                "salary": None,
                "location": None,
                "source_url": f"https://www.zhipin.com/job_detail/{ext}.html",
                "welfare_list": [],
                "tags": [],
            }
        )
    return jobs


class BossExtractService:
    """Boss 岗位提取编排服务。依赖全部注入；None = 未接线（仍可跑 raw 输入）。"""

    def __init__(
        self,
        *,
        job_service: JobServiceLike | None = None,
        settings_service: object | None = None,
        adapter: object | None = None,
        script_path: str | Path | None = None,
    ) -> None:
        # 接线点：未来 agent skill_router/tool_executor 注入 backend 三件套
        self.job_service = job_service
        self.settings_service = settings_service
        self.adapter = adapter
        self.script_path = Path(script_path) if script_path else SCRIPT_PATH

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    async def run(
        self,
        user_id: int,
        *,
        source: str = "page",
        jobs: list[dict[str, Any]] | None = None,
        rules_override: JobRules | dict[str, Any] | None = None,
        ingest: bool = True,
        limit: int = 15,
    ) -> SkillResult:
        """提取 → 筛选 → 落库。

        :param source: "page"（浏览器提取）或 "raw"（传入 jobs）
        :param jobs: source="raw" 时直接提供的岗位 dict 列表
        :param rules_override: 跳过 settings_service，直接给 JobRules 或同键 dict
        :param ingest: False 则只返回筛选结果，不落库
        :param limit: 本次最多处理岗位数（页面滚动式分页由 agent 循环调用）
        """
        try:
            rules = await self._load_rules(user_id, rules_override)
        except Exception as exc:
            logger.exception("load_rules_failed", extra={"user_id": user_id})
            return SkillResult(ok=False, error=f"加载求职规则失败: {exc}")

        try:
            extracted, warnings, src = await self._obtain(source=source, jobs=jobs)
            if not extracted:
                # 无岗位时把根因（未接线/页面无卡片/兜底失败）作为 error 上抛，而非泛化信息
                reason = warnings[0] if warnings else "未提取到任何岗位"
                return SkillResult(
                    ok=False,
                    error=reason,
                    data={
                        "extracted": 0,
                        "passed": 0,
                        "dropped": [],
                        "ingested": [],
                        "errors": [],
                        "warnings": warnings,
                        "source": src,
                    },
                )

            extracted = extracted[:limit]

            # 筛选
            passed: list[tuple[dict[str, Any], JobFitResult]] = []
            dropped: list[dict[str, Any]] = []
            for job in extracted:
                fit = evaluate(job, rules)
                if fit.passed:
                    passed.append((job, fit))
                else:
                    dropped.append({"external_id": job.get("external_id"), "reason": fit.drop_reason})

            # 落库（单条失败不中断，记录 errors）
            ingested: list[Any] = []
            errors: list[dict[str, Any]] = []
            if ingest and self.job_service is not None:
                for job, fit in passed:
                    try:
                        created = await self.job_service.create(user_id, self._to_create_payload(job, fit))
                        ingested.append(self._extract_id(created))
                    except Exception as exc:
                        logger.warning(
                            "ingest_failed",
                            extra={"user_id": user_id, "external_id": job.get("external_id"), "error": str(exc)},
                        )
                        errors.append({"external_id": job.get("external_id"), "error": str(exc)})
            else:
                logger.info("ingest_skipped", extra={"user_id": user_id, "ingest": ingest})

            return SkillResult(
                ok=True,
                data={
                    "extracted": len(extracted),
                    "source": src,
                    "passed": len(passed),
                    "dropped": dropped,
                    "ingested": ingested,
                    "errors": errors,
                    "warnings": warnings,
                },
            )
        except Exception as exc:
            logger.exception("boss_extract_run_failed", extra={"user_id": user_id})
            return SkillResult(ok=False, error=str(exc))

    # ------------------------------------------------------------------
    # 提取
    # ------------------------------------------------------------------
    async def _obtain(
        self, *, source: str, jobs: list[dict[str, Any]] | None
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        """按 source 取岗位。返回 (jobs, warnings, source_label)。"""
        if source == "raw":
            return list(jobs or []), [], "raw"
        if source != "page":
            return [], [f"未知 source: {source!r}（仅支持 page/raw）"], None
        if self.adapter is None:
            return [], ["浏览器适配器未接线（注入 adapter，或设置 BROWSER_MCP_ENABLED）"], None

        script = await asyncio.to_thread(self.script_path.read_text, encoding="utf-8")
        result = await self.adapter.call_tool("chrome_javascript", {"code": script})

        # 主路径：Vue $data.jobList 或脚本内 DOM 兜底
        if result.ok and isinstance(result.data, dict) and result.data.get("ok") is True:
            page_jobs = result.data.get("jobs") or []
            page_warnings = list(result.data.get("warnings") or [])
            src = result.data.get("source")
            if page_jobs:
                return page_jobs, page_warnings, src
            # 提取成功但无岗位：页面问题（未加载/未登录），DOM 兜底同样为空，直接失败
            return [], page_warnings or ["页面无岗位卡片（未加载/未登录/非列表页）"], src

        # 兜底 1：chrome_javascript 不可用（如未授权）→ chrome_get_web_content DOM 解析
        dom_jobs, dom_warnings = await self._extract_from_dom()
        if dom_jobs:
            return dom_jobs, dom_warnings, "dom"
        return [], [result.error or "提取失败", *dom_warnings], None

    async def _extract_from_dom(self) -> tuple[list[dict[str, Any]], list[str]]:
        """chrome_get_web_content 兜底（best-effort：无浏览器授权风险、零脚本注入）。"""
        result = await self.adapter.call_tool("chrome_get_web_content", {})
        if not result.ok:
            return [], [f"chrome_get_web_content 兜底失败: {result.error}"]
        data = result.data if isinstance(result.data, dict) else {}
        jobs = _parse_dom_html(data.get("html")) if data.get("html") else _parse_dom_text(data.get("text"))
        if not jobs:
            return [], ["DOM 兜底未解析出岗位卡片"]
        return jobs, ["DOM 兜底：salary 置空（反爬字体），title/company/location 为 best-effort 解析"]

    # ------------------------------------------------------------------
    # 规则 / 载荷映射
    # ------------------------------------------------------------------
    async def _load_rules(self, user_id: int, rules_override: JobRules | dict[str, Any] | None) -> JobRules:
        if rules_override is not None:
            return self._coerce_rules(rules_override)
        if self.settings_service is None:
            return JobRules()
        cfg = await self.settings_service.get_job_rule(user_id)
        return self._coerce_rules(cfg)

    @classmethod
    def _coerce_rules(cls, cfg: object) -> JobRules:
        """容忍 JobRules / dict（min_salary_k 或 min_salary 键）/ JobRuleConfigResponse 对象。"""
        if isinstance(cfg, JobRules):
            return cfg
        get = cfg.get if isinstance(cfg, dict) else lambda k, d=None: getattr(cfg, k, d)
        min_k = get("min_salary_k", get("min_salary"))
        max_k = get("max_salary_k", get("max_salary"))
        return JobRules(
            min_salary_k=float(min_k) if min_k is not None else None,
            max_salary_k=float(max_k) if max_k is not None else None,
            preferred_locations=[str(x) for x in (get("preferred_locations") or [])] or None,
            overtime_allowed=bool(get("overtime_allowed")),
            outsourcing_allowed=bool(get("outsourcing_allowed")),
            offsite_allowed=bool(get("offsite_allowed")),
        )

    def _to_create_payload(self, job: dict[str, Any], fit: JobFitResult) -> dict[str, Any]:
        """RawJob → JobCreate 形状 dict。

        接线点：集成层接收此 dict，映射为 backend JobCreate（去掉 score_detail）
        落库后再 JobUpdate(score_detail) 写入评分明细。
        """
        return {
            "platform": PLATFORM,
            "external_id": str(job.get("external_id") or "")[:100],
            "title": job.get("title"),
            "company": job.get("company"),
            "salary": job.get("salary"),
            "location": job.get("location"),
            "description": None,
            "source_url": job.get("source_url"),
            "hr_id": None,
            "score_detail": {
                "llm_score": None,
                "llm_reason": None,
                "keyword_hits": fit.keyword_hits,
                "keyword_score": fit.keyword_score,
                "deductions": fit.deductions,
            },
        }

    @staticmethod
    def _extract_id(created: object) -> object:
        """从 create 返回值取 job id（dict / pydantic 对象 / 标量）。"""
        if isinstance(created, dict):
            return created.get("id", created.get("external_id"))
        return getattr(created, "id", created)
