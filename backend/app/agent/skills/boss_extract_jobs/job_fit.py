"""岗位适配度确定性预筛选（垂直工具 boss.extract_jobs 的筛选层）。

职责（对齐 memory/job-data-pipeline：关键词权重 20%，LLM 评分 80%）：
- 列表页提取阶段拿不到 JD，无法做完整 LLM 评分 —— 本模块做**确定性预筛选**：
  硬规则（不满足即弃）+ 关键词命中率（keyword_score，供后续 LLM 评分参考）。
- 纯 stdlib、无 IO、自包含数据形状（不 import backend schema）；
  接线时由集成层把 Settings 的 JobRuleConfigResponse / 提取到的 dict 映射进来。

score_detail 契约（写入 JobUpdate.score_detail，llm_* 由后续 boss.score_job 补）：
    {
      "llm_score": None, "llm_reason": None,
      "keyword_hits": [...], "keyword_score": 0-100, "deductions": [...]
    }
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 单位换算基准：1万 = 10K；千 / K / 无单位按 K。
# 日薪 × 21（约一个月工作日）折算为月薪 K。
WORKDAYS_PER_MONTH = 21

OUTSOURCING_KEYWORDS: tuple[str, ...] = ("外包", "劳务派遣", "人力")
OFFSITE_KEYWORDS: tuple[str, ...] = ("远程", "异地", "居家", "在家办公")
OVERTIME_KEYWORD = "加班"

# 命中规则名（写入 keyword_hits / score_detail）
HIT_SALARY = "salary"
HIT_LOCATION = "location"
HIT_NO_OUTSOURCING = "no_outsourcing"
HIT_NO_OFFSITE = "no_offsite"
HIT_NO_OVERTIME = "no_overtime"


@dataclass
class JobRules:
    """用户岗位偏好规则（对应 Settings job_rule 的确定性部分）。

    任一为 None/False 表示「未配置」= 该规则不参与筛选与计分。
    """

    min_salary_k: float | None = None  # 期望月薪下限(K)
    max_salary_k: float | None = None  # 期望月薪上限(K)
    preferred_locations: list[str] | None = None  # 期望工作城市（子串匹配）
    overtime_allowed: bool = False  # 允许加班
    outsourcing_allowed: bool = False  # 允许外包/劳务派遣
    offsite_allowed: bool = False  # 允许异地/远程


@dataclass
class JobFitResult:
    """单个岗位的适配度判定结果。"""

    passed: bool
    keyword_hits: list[str] = field(default_factory=list)
    keyword_score: float = 100.0  # 0-100，命中适用规则数 / 适用规则数
    deductions: list[str] = field(default_factory=list)
    drop_reason: str | None = None


# ---------------------------------------------------------------------------
# 薪资解析
# ---------------------------------------------------------------------------
_SALARY_RANGE = re.compile(r"^(\d+(?:\.\d+)?)(千|万|K|k)?[-~至—](\d+(?:\.\d+)?)(千|万|K|k)?(以上)?$")
_SALARY_SINGLE = re.compile(r"^(\d+(?:\.\d+)?)(千|万|K|k)?(以上|以下)?$")
_DAILY = re.compile(r"^(\d+(?:\.\d+)?)[-~至](\d+(?:\.\d+)?)元?/(天|日)$")


def _to_k(value: float, unit: str | None) -> float:
    """按单位把数值折算为月薪 K。千/K/无单位 → ×1，万 → ×10。"""
    return value * 10 if unit == "万" else value


def parse_salary_desc(salary: str | None) -> tuple[float, float | None] | None:
    """解析 Boss 薪资描述为月薪区间 (min_k, max_k)。

    支持：
      "15-25K" / "8千-1.2万" / "1-2万"  月薪区间（单位只写一次时作用于两侧）
      "15K以上" / "8千以上"               开区间 → (15.0, None)
      "120-180元/天" / "200-300元/日"    日薪 → ×21 折算
      "15-25K·14薪"                     去 "·" 后缀
      None / "" / "面议" / 无法解析        → None（不硬筛，由 evaluate 记 deduction）
    """
    if not salary:
        return None
    s = salary.replace(" ", "")
    if "面议" in s or "面谈" in s:
        return None
    s = s.split("·", 1)[0]  # 去掉 "·14薪" 等后缀

    m = _DAILY.fullmatch(s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return round(lo * WORKDAYS_PER_MONTH / 1000, 2), round(hi * WORKDAYS_PER_MONTH / 1000, 2)

    m = _SALARY_RANGE.fullmatch(s)
    if m:
        lo, u1, hi, u2, tail = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        # 单位只写一侧时作用于两侧；两侧都有则各自换算
        lo_k = _to_k(float(lo), u1 or u2)
        hi_k = _to_k(float(hi), u2 or u1)
        lo_k, hi_k = min(lo_k, hi_k), max(lo_k, hi_k)
        return (lo_k, None) if tail == "以上" else (lo_k, hi_k)

    m = _SALARY_SINGLE.fullmatch(s)
    if m:
        v, u, tail = float(m.group(1)), m.group(2), m.group(3)
        k = _to_k(v, u)
        if tail == "以上":
            return (k, None)
        if tail == "以下":
            return (None, k)
        return (k, k)

    return None


# ---------------------------------------------------------------------------
# 适配度评估
# ---------------------------------------------------------------------------
def evaluate(job: dict, rules: JobRules) -> JobFitResult:
    """评估单个岗位的适配度。

    规则语义（对齐 memory 中已确认的判定）：
      - 薪资：规则启用且解析成功 → 区间无重叠即 hard-drop；解析失败 → 不硬筛 + deduction
      - 地点：preferred_locations 配置 → 无命中即 hard-drop（未解析出地点视为无命中）
      - 外包/异地远程/加班：不允许 且 命中关键词 → hard-drop
    keyword_score = 命中适用规则数 / 适用规则数 × 100；无适用规则 → 100 不筛。
    """
    rules = rules or JobRules()
    deductions: list[str] = []
    hits: list[str] = []
    applicable = 0
    dropped = False
    drop_reason: str | None = None

    # 1) 薪资
    if rules.min_salary_k is not None or rules.max_salary_k is not None:
        applicable += 1
        parsed = parse_salary_desc(job.get("salary"))
        if parsed is None:
            deductions.append(f"薪资格式无法解析: {job.get('salary')!r}（跳过薪资硬筛）")
        else:
            job_lo, job_hi = parsed
            # 区间无重叠即弃：job 上限低于规则下限，或 job 下限高于规则上限
            if rules.min_salary_k is not None and job_hi is not None and job_hi < rules.min_salary_k:
                dropped, drop_reason = True, f"薪资低于下限（期望 ≥{rules.min_salary_k:g}K）"
            elif rules.max_salary_k is not None and job_lo is not None and job_lo > rules.max_salary_k:
                dropped, drop_reason = True, f"薪资高于上限（期望 ≤{rules.max_salary_k:g}K）"
            else:
                hits.append(HIT_SALARY)

    # 2) 地点（未解析出地点视为无命中 → 保守硬筛）
    if rules.preferred_locations:
        applicable += 1
        loc = job.get("location") or ""
        if any(p in loc for p in rules.preferred_locations):
            hits.append(HIT_LOCATION)
        else:
            dropped, drop_reason = True, f"地点不匹配（期望: {'/'.join(rules.preferred_locations)}）"

    # 3) 外包
    if not rules.outsourcing_allowed:
        applicable += 1
        haystack = f"{job.get('title') or ''} {job.get('company') or ''} " + " ".join(job.get("welfare_list") or [])
        if any(kw in haystack for kw in OUTSOURCING_KEYWORDS):
            dropped, drop_reason = True, "疑似外包/劳务派遣（title/company/福利命中）"
        else:
            hits.append(HIT_NO_OUTSOURCING)

    # 4) 异地/远程
    if not rules.offsite_allowed:
        applicable += 1
        haystack = f"{job.get('location') or ''} {job.get('title') or ''}"
        if any(kw in haystack for kw in OFFSITE_KEYWORDS):
            dropped, drop_reason = True, "疑似异地/远程办公（location/title 命中）"
        else:
            hits.append(HIT_NO_OFFSITE)

    # 5) 加班
    if not rules.overtime_allowed:
        applicable += 1
        haystack = " ".join(job.get("welfare_list") or []) + " " + " ".join(job.get("tags") or [])
        if OVERTIME_KEYWORD in haystack:
            dropped, drop_reason = True, "福利/标签含『加班』"
        else:
            hits.append(HIT_NO_OVERTIME)

    keyword_score = round(len(hits) / applicable * 100, 1) if applicable else 100.0

    return JobFitResult(
        passed=not dropped,
        keyword_hits=hits,
        keyword_score=keyword_score,
        deductions=deductions,
        drop_reason=drop_reason,
    )
