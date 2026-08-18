# boss-extract-jobs — Boss 直聘岗位提取垂直工具

把「提取 Boss 岗位 → 按岗位适配度筛选 → 幂等落库」封装为未来 agent（doc 06）可直接编排的垂直领域工具。**先落契约与实现，agent 运行时实现后接线**（见 SKILL.md「接线说明」）。

## 目录结构

```
backend/app/agent/skills/boss-extract-jobs/
├── __init__.py        # 包导出（BossExtractService / SkillResult / JobRules）
├── SKILL.md           # doc 08 Skill 契约（目标/输入/输出/Prompt/Tool 需求/Recovery/接线）
├── extract-jobs.js    # 浏览器提取脚本（MAIN world，注入用，<10000 字符）
├── job_fit.py         # 岗位适配度确定性预筛（纯 stdlib，无 IO）
├── service.py         # 编排：提取 → 筛选 → 落库（依赖注入，self-contained）
├── README.md
└── tests/
    ├── conftest.py    # sys.path 注入，支持独立 pytest
    ├── test_job_fit.py
    └── test_service.py
```

## 数据流

```
浏览器(列表页) --chrome_javascript 注入--> extract-jobs.js
   -> Vue $data.jobList（主） / DOM（兜底） -> RawJob[]（明文 salaryDesc）
   -> job_fit.evaluate(job, rules)         # 硬规则 hard-drop + keyword_score
   -> job_service.create(payload_dict)     # JobCreate 形状，external_id 幂等去重
   -> score_detail{llm_*:None, keyword_hits, keyword_score, deductions}
```

- 提取**零新增 zhipin 请求**：读页面已加载的 Vue `$data.jobList`，绕过反爬字体（方案文档 §8 红线）。
- MCP 通用工具兜底：`chrome_get_web_content`（DOM 解析）；LLM 交互兜底（滚动分页）待 agent 运行时接线。
- 筛选权重：LLM 80% + 关键词 20%（用户已确认，覆盖 doc 08 的 40%）。列表页无 JD，本工具只做**确定性预筛**，LLM 评分由后续 `boss.score_job` 补齐。

## 独立运行测试

```bash
# 从仓库根（用 backend venv 跑，与 backend 测试同一解释器）
backend/.venv/Scripts/python.exe -m pytest backend/app/agent/skills/boss-extract-jobs/tests -v

# 或进目录独立跑（conftest 自动注入 sys.path）
cd backend/app/agent/skills/boss-extract-jobs && python -m pytest tests -v
```

## 快速试跑（不连浏览器）

```python
import asyncio

# 目录名含连字符，不能直接 import（含 app.agent.skills.boss_extract_jobs 点号路径）。
# 未接线时：进技能目录顶层导入（conftest 注入 sys.path），或 importlib 用文件系统路径动态加载。
# 正式接线时：将目录重命名为合法包名 boss_extract_jobs，即可 `from app.agent.skills.boss_extract_jobs import ...`。
import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend/app/agent/skills/boss-extract-jobs").resolve()))
from job_fit import JobRules  # noqa: E402
from service import BossExtractService  # noqa: E402


async def main():
    jobs = [
        {
            "external_id": "a1",
            "title": "后端工程师",
            "company": "某公司",
            "salary": "20-30K",
            "location": "北京·海淀",
            "welfare_list": [],
            "tags": [],
        },
        {
            "external_id": "a2",
            "title": "外包前端",
            "company": "人力公司",
            "salary": "15-20K",
            "location": "北京·朝阳",
            "welfare_list": [],
            "tags": [],
        },
    ]
    svc = BossExtractService()  # 未接线：仅筛选不落库
    res = await svc.run(
        1, source="raw", jobs=jobs, rules_override=JobRules(min_salary_k=20, preferred_locations=["北京"])
    )
    print(res)
    # passed 仅 a1（a2 薪资低于下限且命中外包）；ingest=False 不落库


asyncio.run(main())
```

## 接线路径（落地顺序）

1. `chrome_javascript` 从 `BROWSER_MCP_RISK_TOOLS` 移除或加 Skill 级授权（`backend/app/core/config.py`）。
2. 注入三件套：`BrowserToolAdapter` / `JobServiceAdapter`（见 SKILL.md）/ `SettingsService`。
3. doc 06 skill_router `map_goal_to_skill` 挂 `boss.extract_jobs`。
4. （后续）`boss.score_job` 补 LLM 评分写入 `score_detail.llm_*`，再按阈值产出 `JobScored`。

## 设计要点（为什么这样写）

| 决定 | 理由 |
|---|---|
| 脚本以 `return` 结尾 | 注入端包装为 `(function(){ <code> })()`，函数体须显式 return；Node CommonJS 同理会话亦合法 |
| 提取主走 Vue `$data` | 明文 `salaryDesc`、零请求，规避反爬字体；DOM 文本薪资是乱码 |
| 薪资解析失败「不硬筛只扣分」 | 列表页信息不全，保守放行交给 LLM 评分，避免误杀；地点相反是硬筛（无法验证城市=不推荐跨城） |
| `skill/` 自包含 | 不与 backend 耦合，mock 依赖即可单测；接线时才做 schema 映射 |
