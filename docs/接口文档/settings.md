# 系统配置模块（Settings）

> 前缀：`/api/v1/settings` · 代码：`backend/app/api/v1/settings.py` · DTO：`backend/app/schema/setting.py`

提供四类配置的查询与更新：**LLM、Agent 策略、求职规则、回复风格**。所有配置按用户隔离，落库结构为
`Setting(category, key, value={"value": <实际值>})`，缺失项返回默认值。

**配置分类 `category`**：`llm` / `agent` / `job_rule` / `reply_style`（定义于 `SettingsService.CONFIG_DEFAULTS`）。

## 接口列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/settings` | 获取全部分组配置 |
| GET | `/api/v1/settings/llm` | 获取 LLM 配置 |
| PUT | `/api/v1/settings/llm` | 更新 LLM 配置 |
| GET | `/api/v1/settings/agent` | 获取 Agent 策略配置 |
| PUT | `/api/v1/settings/agent` | 更新 Agent 策略配置 |
| GET | `/api/v1/settings/job-rule` | 获取求职规则配置 |
| PUT | `/api/v1/settings/job-rule` | 更新求职规则配置 |
| GET | `/api/v1/settings/reply-style` | 获取回复风格配置 |
| PUT | `/api/v1/settings/reply-style` | 更新回复风格配置 |
| PUT | `/api/v1/settings/batch` | 批量更新（同一分类，事务原子性） |
| POST | `/api/v1/settings/validate-llm` | 验证 LLM 配置连通性 |

---

## 1. GET /settings — 全部分组配置

返回按 `category` 分组的完整配置列表，缺失项自动填充默认值。

**响应 200** — `list[SettingCategoryResponse]`

```json
[
  {
    "category": "llm",
    "settings": [
      { "key": "provider", "value": "openai" },
      { "key": "base_url", "value": null },
      { "key": "model", "value": "gpt-4o-mini" },
      { "key": "api_key", "value": "sk-...xxxx" },
      { "key": "temperature", "value": 0.7 },
      { "key": "max_tokens", "value": null }
    ]
  },
  { "category": "agent", "settings": [ "..."] },
  { "category": "job_rule", "settings": [ "..."] },
  { "category": "reply_style", "settings": [ "..."] }
]
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `category` | string | 配置分类（固定 4 个） |
| `settings` | array | 配置项列表，`{key, value}`，value 为任意 JSON 类型 |

> ✅ **已修复（安全）**：`llm.api_key` 在本接口同样返回**掩码**（仅显示首尾 4 字符，与
> `GET /settings/llm` 一致），不再泄露明文。存储侧为对称加密（见 PUT /settings/llm 的 `api_key` 说明）。

---

## 2. GET /settings/llm — 获取 LLM 配置

**响应 200** — `LLMConfigResponse`

```json
{
  "provider": "openai",
  "base_url": null,
  "model": "gpt-4o-mini",
  "api_key_masked": "sk-...xxxx",
  "temperature": 0.7
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `provider` | string | LLM 提供商（默认 openai） |
| `base_url` | string\|null | API Base URL（代理场景） |
| `model` | string | 模型名称（默认 gpt-4o-mini） |
| `api_key_masked` | string\|null | API Key 掩码，**不返回明文**；≤8 位时为 `****` |
| `temperature` | float | 采样温度 0–2（默认 0.7） |

## 3. PUT /settings/llm — 更新 LLM 配置

**请求体** — `LLMConfigUpdate`

```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "api_key": "sk-xxxx",
  "temperature": 0.7,
  "max_tokens": 2048
}
```

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `provider` | string | 否 | openai | - |
| `base_url` | string\|null | 否 | null | - |
| `model` | string | 否 | gpt-4o-mini | - |
| `api_key` | string | **是** | - | 落库前对称加密（Fernet，密钥由 `settings.jwt_secret_key` 派生）；读取侧解密后返回掩码 |
| `temperature` | float | 否 | 0.7 | 0–2 |
| `max_tokens` | int\|null | 否 | null | ≥1；**为 null 时不落库** |

**响应 200** — `LLMConfigResponse`（同 GET，返回掩码 key）

---

## 4. GET /settings/agent — 获取 Agent 策略配置

**响应 200** — `AgentConfigResponse`

```json
{
  "concurrency_limit": 3,
  "auto_reply_enabled": false,
  "auto_approval_threshold": 0.9,
  "approval_timeout_seconds": 20,
  "max_retries": 2
}
```

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `concurrency_limit` | int | 3 | 并发任务数限制 |
| `auto_reply_enabled` | bool | false | 是否启用自动回复 |
| `auto_approval_threshold` | float | 0.9 | 自动确认置信度阈值 0–1 |
| `approval_timeout_seconds` | int | 20 | 人工确认超时时间（秒） |
| `max_retries` | int | 2 | 任务失败最大重试次数 |

## 5. PUT /settings/agent — 更新 Agent 策略配置

**请求体** — `AgentConfigUpdate`（字段同上，均带默认值）

| 字段 | 约束 |
| --- | --- |
| `concurrency_limit` | 1–10 |
| `auto_approval_threshold` | 0–1 |
| `approval_timeout_seconds` | 10–120 |
| `max_retries` | 0–5 |

```json
{
  "concurrency_limit": 3,
  "auto_reply_enabled": true,
  "auto_approval_threshold": 0.9,
  "approval_timeout_seconds": 20,
  "max_retries": 2
}
```

**响应 200** — `AgentConfigResponse`

---

## 6. GET /settings/job-rule — 获取求职规则配置

**响应 200** — `JobRuleConfigResponse`

```json
{
  "min_salary": null,
  "max_salary": null,
  "preferred_locations": null,
  "overtime_allowed": false,
  "outsourcing_allowed": false,
  "offsite_allowed": false
}
```

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `min_salary` | int\|null | null | 最低期望月薪（K） |
| `max_salary` | int\|null | null | 最高期望月薪（K） |
| `preferred_locations` | array\|null | null | 期望地点列表 |
| `overtime_allowed` | bool | false | 是否接受加班 |
| `outsourcing_allowed` | bool | false | 是否接受外包 |
| `offsite_allowed` | bool | false | 是否接受异地办公 |

## 7. PUT /settings/job-rule — 更新求职规则配置

**请求体** — `JobRuleConfigUpdate`（字段同上，`min_salary`/`max_salary` ≥0）。
**未配置项（null）即为 Approval 触发条件**：即这些条件不满足时，Agent 会进入 `waiting_approval` 状态请求人工确认。

```json
{
  "min_salary": 20,
  "max_salary": 40,
  "preferred_locations": ["上海", "杭州"],
  "overtime_allowed": true,
  "outsourcing_allowed": false,
  "offsite_allowed": false
}
```

**响应 200** — `JobRuleConfigResponse`

---

## 8. GET /settings/reply-style — 获取回复风格配置

**响应 200** — `ReplyStyleConfigResponse`

```json
{
  "tone": "professional",
  "formality": "formal",
  "length_preference": "medium",
  "include_greeting": true,
  "include_closing": true
}
```

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `tone` | string | professional | professional / friendly / concise |
| `formality` | string | formal | formal / neutral / casual |
| `length_preference` | string | medium | short / medium / long |
| `include_greeting` | bool | true | 是否包含问候语 |
| `include_closing` | bool | true | 是否包含结束语 |

## 9. PUT /settings/reply-style — 更新回复风格配置

**请求体** — `ReplyStyleConfigUpdate`（字段同上，带默认值）

```json
{
  "tone": "friendly",
  "formality": "casual",
  "length_preference": "short",
  "include_greeting": true,
  "include_closing": false
}
```

**响应 200** — `ReplyStyleConfigResponse`

---

## 10. PUT /settings/batch — 批量更新配置

同一分类下多个键值一次性更新，`@transactional` 保证原子性（全部成功或全部回滚）。

**请求体** — `SettingBatchUpdate`

```json
{
  "category": "agent",
  "updates": [
    { "key": "auto_reply_enabled", "value": true },
    { "key": "concurrency_limit", "value": 5 }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `category` | string | 是 | 配置分类，必须为 llm/agent/job_rule/reply_style 之一，否则 **400 `bad_request`** |
| `updates` | array | 是（非空） | `{key, value}` 列表；**未知 key 被静默跳过**（仅记日志），不属于错误 |

**响应 200**

```json
{ "status": "ok", "updated": 2 }
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | 固定 `ok` |
| `updated` | int | 实际更新的配置项数量（`len(updated_keys)`，不含被跳过的未知 key） |

---

## 11. POST /settings/validate-llm — 验证 LLM 配置

无请求体。基于当前已保存的 LLM 配置做连通性检查。

> ⚠️ **当前为 stub**：`validate_llm_settings` 未实际调用 LLM API。
> - `api_key` 未配置 → 返回 `ok=false, detail="API Key 未配置"`；
> - 已配置 → 返回 `ok=true, detail="配置已保存，连通性测试待实现"`。

**响应 200**

```json
{ "ok": true, "detail": "配置已保存，连通性测试待实现" }
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | bool | 配置是否有效 |
| `detail` | string\|null | 验证结果说明 / 错误信息 |
