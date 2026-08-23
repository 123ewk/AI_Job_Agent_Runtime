"""job_fit 单元测试：薪资解析 + 岗位适配度评估。"""

from __future__ import annotations

import pytest
from job_fit import JobRules, evaluate, parse_salary_desc


def _job(**overrides: object) -> dict:
    job = {
        "external_id": "abc",
        "title": "后端工程师",
        "company": "某公司",
        "salary": "20-30K",
        "location": "北京·海淀·中关村",
        "welfare_list": ["五险一金", "弹性工作"],
        "tags": ["技术大牛"],
    }
    job.update(overrides)
    return job


# ---------------------------------------------------------------------------
# parse_salary_desc
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15-25K", (15.0, 25.0)),
        ("15k-25k", (15.0, 25.0)),
        ("8千-1.2万", (8.0, 12.0)),
        ("1-2万", (10.0, 20.0)),
        ("1.2万-2万", (12.0, 20.0)),
        ("20-30 K", (20.0, 30.0)),  # 含空格
        ("15K以上", (15.0, None)),
        ("120-180元/天", (2.52, 3.78)),  # ×21 工作日折算
        ("200-300元/日", (4.2, 6.3)),
        ("15-25K·14薪", (15.0, 25.0)),  # 去 "·" 后缀
        ("面议", None),
        ("薪资面议", None),
        ("", None),
        (None, None),
        ("随便给", None),  # 无法解析
    ],
)
def test_parse_salary_desc(text: str | None, expected: tuple | None) -> None:
    assert parse_salary_desc(text) == expected


# ---------------------------------------------------------------------------
# evaluate —— 薪资
# ---------------------------------------------------------------------------
def test_salary_above_ceiling_dropped() -> None:
    fit = evaluate(_job(salary="40-50K"), JobRules(max_salary_k=30))
    assert fit.passed is False
    assert "上限" in (fit.drop_reason or "")


def test_salary_below_floor_dropped() -> None:
    fit = evaluate(_job(salary="10-15K"), JobRules(min_salary_k=20))
    assert fit.passed is False
    assert "下限" in (fit.drop_reason or "")


def test_salary_overlap_passes() -> None:
    # 区间重叠即过：20-30K 与 下限25K 有交集
    fit = evaluate(_job(salary="20-30K"), JobRules(min_salary_k=25))
    assert fit.passed is True
    assert "salary" in fit.keyword_hits


def test_salary_unparseable_not_dropped() -> None:
    # 解析失败不硬筛，记 deduction（交 LLM 评分再判）
    fit = evaluate(_job(salary="面议"), JobRules(min_salary_k=20))
    assert fit.passed is True
    assert any("薪资" in d for d in fit.deductions)


def test_salary_rule_disabled_no_deduction() -> None:
    # 规则未启用则不解析薪资，也不产生 deduction
    fit = evaluate(_job(salary="面议"), JobRules())
    assert fit.deductions == []


# ---------------------------------------------------------------------------
# evaluate —— 地点 / 外包 / 异地 / 加班
# ---------------------------------------------------------------------------
def test_location_match_hits() -> None:
    fit = evaluate(_job(location="北京·海淀"), JobRules(preferred_locations=["北京"]))
    assert fit.passed is True
    assert "location" in fit.keyword_hits


def test_location_mismatch_dropped() -> None:
    fit = evaluate(_job(location="上海·浦东"), JobRules(preferred_locations=["北京"]))
    assert fit.passed is False
    assert "地点不匹配" in (fit.drop_reason or "")


def test_location_empty_with_rules_dropped() -> None:
    # 配置了期望地点但岗位没解析出地点 → 保守硬筛（无法确认城市不推荐）
    fit = evaluate(_job(location=None), JobRules(preferred_locations=["北京"]))
    assert fit.passed is False


def test_outsourcing_detected_and_dropped() -> None:
    fit = evaluate(_job(title="外包Java开发"), JobRules())
    assert fit.passed is False
    assert "外包" in (fit.drop_reason or "")


def test_outsourcing_allowed_passes() -> None:
    fit = evaluate(_job(title="外包Java开发", welfare_list=["人力派遣"]), JobRules(outsourcing_allowed=True))
    assert fit.passed is True


def test_offsite_detected_and_dropped() -> None:
    fit = evaluate(_job(title="远程前端工程师"), JobRules())
    assert fit.passed is False


def test_overtime_detected_and_dropped() -> None:
    fit = evaluate(_job(welfare_list=["五险一金", "加班补贴"]), JobRules())
    assert fit.passed is False
    assert "加班" in (fit.drop_reason or "")


def test_overtime_allowed_passes() -> None:
    fit = evaluate(_job(welfare_list=["加班补贴"]), JobRules(overtime_allowed=True))
    assert fit.passed is True


# ---------------------------------------------------------------------------
# evaluate —— keyword_score
# ---------------------------------------------------------------------------
def test_no_rules_all_pass_score_100() -> None:
    fit = evaluate(_job(), JobRules())
    assert fit.passed is True
    assert fit.keyword_score == 100.0
    assert fit.drop_reason is None


def test_all_rules_pass_score_100() -> None:
    rules = JobRules(min_salary_k=10, max_salary_k=40, preferred_locations=["北京"])
    fit = evaluate(_job(), rules)
    assert fit.passed is True
    # salary + location + no_outsourcing + no_offsite + no_overtime = 5/5
    assert fit.keyword_score == 100.0


def test_unparseable_salary_reduces_score() -> None:
    # salary 规则启用但解析失败 → 未命中 → 4/5 = 80
    rules = JobRules(min_salary_k=10, preferred_locations=["北京"])
    fit = evaluate(_job(salary="面议"), rules)
    assert fit.passed is True
    assert fit.keyword_score == 80.0
    assert len(fit.deductions) == 1


def test_dropped_job_still_reports_score() -> None:
    # 被硬筛掉的岗位仍给出 keyword_score（供 LLM 复盘）
    fit = evaluate(_job(salary="10-15K"), JobRules(min_salary_k=20, preferred_locations=["北京"]))
    assert fit.passed is False
    assert fit.keyword_score < 100.0
