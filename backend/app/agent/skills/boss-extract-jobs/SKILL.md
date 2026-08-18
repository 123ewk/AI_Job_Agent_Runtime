# Skill: boss.extract_jobs — Boss 岗位提取落库（垂直领域工具契约）

> 对齐 `docs/AI求职Agent_设计文档_V2.0/08-Boss Skill详细接口设计.md` 的 Goal-Oriented Skill 模板。
> 这是**垂直领域工具**：把「提取 Boss 岗位 → 按岗位适配度筛选 → 落库」封装为 agent 可直接编排的 Skill。
> 与 doc 08 模板的差异：本工具**持有**提取实现（`extract-jobs.js` + 筛选逻辑），
> 因为岗位卡片选择器/提取链路是 Boss 站点的领域知识，封装进工具可被复用与单测；
> 其余（导航/交互等通用浏览器能力）仍走项目通用 chrome-mcp-server 的 `chrome_*` 工具兜底。

---

## 目标（Goal）

把当前浏览器已打开的 **Boss 直聘岗位列表页** 上可见的岗位，按用户求职规则（`job_rule`）做确定性适配度筛选后**幂等落库**（`status=discovered`，`external_id` 去重）。MCP 通用工具作为浏览器能力兜底。

## 输入（Input）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_id` | int | 是 | 目标用户（单用户部署恒为 1，接线后由 agent 传入） |
| `source` | str | 否 | `"page"`（默认，提取当前活动标签页）或 `"raw"`（直接传 `jobs`） |
| `jobs` | list[dict] | source=raw 时必填 | 岗位 dict 列表（键同 `extract-jobs.js` 返回形状） |
| `rules_override` | JobRules/dict | 否 | 跳过 Settings 直接给规则（测试/独立运行用） |
| `ingest` | bool | 否 | 默认 `True`；`False` 只筛选不落库 |
| `limit` | int | 否 | 默认 15；单次最多处理岗位数（分页由 agent 循环滚动调用） |

## 输出（Output）

```json
{
  "ok": true,
  "data": {
    "extracted": 12, "source": "vue",
    "passed": 9, "dropped": [{"external_id": "xxx", "reason": "薪资低于下限"}],
    "ingested": [1, 2, 3], "errors": [],
    "warnings": []
  }
}
```

`dropped.reason` 与 `score_detail.deductions` 供前端/LLM 复盘；`errors` 为单条落库失败的岗位（不中断整体）。

## Prompt（指导 Agent 达成目标）

1. 前置：确认浏览器当前活动标签页是 Boss 岗位**列表页**（`https://www.zhipin.com/web/geek/jobs*`），且已登录。
2. 调用本 Skill（`source="page"`）。若返回 `extracted=0`，先引导用户滚动列表页加载更多，再重试（滚动属交互，由 agent 经 `chrome_*` 交互工具完成，本 Skill 不滚动）。
3. 重复调用直到达到用户要求的岗位数量或页面无更多。
4. 落库结果以 `ingested` 为准；`dropped` 记录不可当作落库成功。
5. 全程仅允许 `zhipin.com` 域（Tool Adapter 已有域名白名单兜底）。

## Tool 需求（浏览器能力类别）

| 能力 | 工具 | 用途 |
|---|---|---|
| 脚本注入（**主路径**） | `chrome_javascript` | 注入 `extract-jobs.js`，读取页面内存 Vue `$data.jobList`（明文薪资，**零新增 zhipin 请求**，绕过反爬字体） |
| 内容读取（**兜底 1**） | `chrome_get_web_content` | `chrome_javascript` 不可用时解析 DOM（best-effort，薪资置空） |
| 内容读取/交互（**兜底 3**，文档化） | `chrome_read_page` / `click_element` | 结构异常时 agent 读页定位、滚动分页后重试（接线后由 ReAct 决策，不在本工具内实现） |

> ⚠️ **前置授权**：`chrome_javascript` 目前被 `BROWSER_MCP_RISK_TOOLS` 拦截（"高危工具需 Skill 级授权"）。
> 接线本 Skill 前需将其从风险列表移除或改为 Skill 级授权放行（`backend/app/core/config.py` → `browser_mcp_risk_tools`），
> 或确认后续 doc 14 Approval 流覆盖该调用。未授权时本 Skill 自动降级走 DOM 兜底并写 `warning`。

## 前置（DomainGuard 约束）

- 用户已在真实 Chrome 打开 Boss 列表页并登录（Cookie 会话有效）。
- 用户 `job_rule` 已配置（未配置则全部规则视为未启用 → 全部通过，仅落库）。
- chrome-mcp-server 桥已连接（扩展 WS 已连 `/ws`、`/ping` 通）。
- `chrome_javascript` 已授权（见上）。

## 后置（成功后的领域状态变更）

- 落库 `Job`（`platform=boss`，`status=discovered`，`external_id` 幂等去重）。
- `score_detail` 写入 `keyword_hits / keyword_score / deductions`；`llm_score / llm_reason` 为 `None`（由后续 `boss.score_job` 补齐，权重 LLM 80% + 关键词 20%，见 memory `job-data-pipeline`）。
- （未来）产出 `JobDiscovered` 事件，触发 score 流水线。

## Recovery（失败恢复，指向 doc 15）

| 失败 | 策略 |
|---|---|
| `chrome_javascript` 被拒/报错 | 自动降级 `chrome_get_web_content` DOM 兜底（薪资置空 + warning）；仍失败 → 返回 `error`，agent 经 `boss.recover_page` 重试 |
| `extracted=0`（页面未加载/未登录） | 不自动重试；返回明确 `error`，通知用户确认页面状态 |
| 提取成功但某条落库失败 | 不中断，记入 `errors`，继续其余岗位 |
| 规则加载失败 | 整体失败返回 `error`；不落库（零信任：规则缺失不默认放行） |

## 异常（可预见的失败与处理）

| 异常 | 处理 |
|---|---|
| 浏览器适配器未接线（`BROWSER_MCP_ENABLED=false`） | `error` 明确提示注入 adapter |
| 非 zhipin 页面 | 提取脚本返回 `ok=false`；提示用户切到列表页 |
| 岗位薪资为「面议」 | 不硬筛，记 `deduction`（score_detail），交给 LLM 评分再判 |
| 期望城市与岗位不符 | hard-drop，`dropped` 记录 reason |
| 外包/异地/加班 命中且不允许 | hard-drop |

---

## 接线说明（对接未来 agent，doc 06 skill_router）

```python
# 未来：skill_router.map_goal_to_skill("提取岗位") -> boss.extract_jobs
# 目录名含连字符，不能直接 `import app.agent.skills.boss_extract_jobs`（语法错误）；
# 打包/接线时建议把目录重命名为合法包名 boss_extract_jobs，
# 届时可 `from app.agent.skills.boss_extract_jobs import BossExtractService, JobRules`。
# 未接线独立运行：进技能目录顶层导入（tests/conftest.py 已注入 sys.path）。
from backend.app.service.browser_tools import BrowserToolAdapter
from backend.app.service.job import JobService
from backend.app.service.setting import SettingsService


class JobServiceAdapter:  # 接线点：把 backend JobService 包成本工具契约
    def __init__(self, svc: JobService):
        self._svc = svc

    async def create(self, user_id, payload):
        from backend.app.schema.job import JobCreate, JobUpdate

        sd = payload.pop("score_detail", None)
        created = await self._svc.create(user_id, JobCreate(**payload))
        if sd is not None:
            await self._svc.update(user_id, created.id, JobUpdate(score_detail=sd))
        return created.model_dump()


service = BossExtractService(
    adapter=BrowserToolAdapter(),
    job_service=JobServiceAdapter(JobService(db)),
    settings_service=SettingsService(db),
)
result = await service.run(user_id=1)
```

**映射契约**（集成层负责）：
- `SettingsService.get_job_rule` → `JobRules`：`min_salary/max_salary`（K）→ `min_salary_k/max_salary_k`；`preferred_locations` 原样；`overtime_allowed/outsourcing_allowed/offsite_allowed` 原样。
- `RawJob`（extract-jobs.js 形状）→ `JobCreate`：`external_id/title/company/salary/location/source_url`；`description/hr_id` 置空；`score_detail` 拆出走 `JobUpdate`。
- 注入的 `job_service.create(user_id, payload_dict)` 接收含 `score_detail` 的完整 dict。
