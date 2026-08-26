# Code Review 结论：未连通模块清单与修复路线（2026-08-26）

> 本会话只做**排查**，未改代码。此为下一会话的小步修复起点——每修一项，改完代码后在本文
> 对应条目打 `[x]` 并补一行"改了什么 + 测试结果"，收尾再整体过一遍。

**排查手法**：全库 grep TODO/占位/接线点 + 逐个追 import 引用链 + 读关键方法体核实真实实现。
结论分 A/B/C/D 四级，A 与上次 Boss 落库断链同构（P0），其余多为死壳/文档声明/过时注释。

---

## A. P0 — TaskService.retry 重试任务建了却从不入队（真断链） [x] ✅ 已修（2026-08-26）

**现象**：API 端点 `api/v1/tasks.py:116`（`retry_task`，可触达）→ `service/task.py:263 retry()` → 建一条
`pending` 新任务（复用 thread_id）→ **没有 push 到 Redis Stream** → 消费循环（QueueConsumer）永不消费
这条任务，DB 里永久 pending。

**关键证据**：
- 正常创建 `TaskService.create()` 在 `task.py:172` 有 `await queue.enqueue(message)`——所以队列有源头，
  唯独重试路径漏接。
- 重试路径在 `task.py:317` 留 `# TODO: 入队 Redis Stream`，创建完直接 `return`。

**根因**：`retry()` 与 `create()` 的入队逻辑割裂——create 把"落库+入队"做在一起，retry 只复用了落库、
忘了入队。与上次 Boss"读取做了落库没做"是同一类「副作用的最后一步没接」。

**修复（下一会话首项）**：
- 在 `service/task.py` 的重试入队点（317 附近）补 `QueueClient().enqueue(QueueMessage(...))`，参数对齐
  `create()` 第 160-172 行的构造（task_id/thread_id/conversation_id/priority/payload，int 主键转 str）。
- **加测试**：断言 retry 后队列收到消息（可 mock `QueueClient` 或校验 `enqueue` 被调用且参数正确）；
  并覆盖"入队失败不吞掉"的异常路径。

**✅ 改了什么（2026-08-26）**：`app/service/task.py` retry()（原 317 行 TODO）补 `queue_client/queue_message = _get_queue_classes()` → 构造 `QueueMessage`（task_id=str、thread_id 复用 `original_task.thread_id or uuid4()`、conversation_id int 主键化串、priority、payload）→ `await queue.enqueue(message)`，对齐 create() 入队构造。局部变量用小写避免新增 N806（create() 的 CamelCase 属既有债务）。测试 `tests/test_tasks_api.py` 新增 2 条：`test_retry_enqueues_new_task`（mock enqueue 断言入队一次 + 参数正确）/ `test_retry_enqueue_failure_propagates`（enqueue 抛错向上传播 ≥500 不吞）。**结果：`tests/test_tasks_api.py` 18 passed / 1 skipped；ruff 增量全绿**。

---

## B. 零引用的死模块（宣称负责、实际无 import）

以下全部经全库 grep 确认 **零 import**。分两类处置：

### B1. 职责错位（设计层问题，需用户拍板方向）
- **`app/agent/domain/rules.py`**、**`app/agent/domain/guard.py`**：doc 05 声明它们应持有
  「岗位适配度规则、敏感操作清单（触发 Approval）、域名白名单」「前置/后置校验」。但文件是 TODO 空壳，
  且真实红线（send 需 approved、域名白名单）是**内联在 `SkillExecutor` / `tools/router.py` / 技能服务**里的。
  → 两条路（二选一，勿重复实现）：
  1. **收敛**：把内联的红线/白名单收敛进 `domain/`，被 router 引用（大改，动红线段慎行）；
  2. **删除留档**：删这两个空壳 + 在 doc 里注明"规则当前内联在 router/skill，未来属 domain"。
  **推荐先 2 后评估**，避免为凑架构而重排已经跑通的红线。

### B2. 死壳（被别处取代 / backlog，可安全清或留待功能落地）
- **`app/agent/runtime/events.py`**：旧 WS 占位，已被 `ws_hub.py` 完全取代 → 应删。
- **`app/agent/runtime/approval_manager.py`**：审批创建/状态机实际在 `WorkflowEngine` + `ApprovalService` → 应删（或并入)。
- **`app/agent/runtime/memory_store.py`**：pgvector 长期记忆，未实现（backlog）。
- **`app/agent/runtime/scheduler.py`**：APScheduler 周期寻岗，未实现（backlog）。
- **`app/agent/recovery/browser_recovery.py`**：`WorkflowEngine.recover_browser` 的 `_recover_fn` 未接线，
  现 fail-fast 返回"不可恢复"、图走 failed（**有意为之**）——模块空置，恢复能力无。

---

## C. 功能 stub（可达但纯占位，非隐藏断链，backlog）

- **`app/service/memory.py`**：`extract_and_save` 恒返回 0（`api/v1/memory.py:146` 自注）；embedding 返回
  512 维零向量。API 可达但逻辑占位。
- **`app/service/conversation.py:302`**：消息拉取占位——SKILL.md 已声明"真正同步未实现"，非新缺口。
- **`app/service/setting.py:396`**：LLM 连通性 ping 返回"连通性测试待实现"。

---

## D. 过时注释（非缺口，但误导，顺手清理） [x] ✅ 已修（2026-08-26）

- **`app/service/approval.py:134-138`** `create()` 步骤 3/4/5 的 TODO：声称"触发 Interrupt /
  Task->waiting_approval / 推 WS"未做。**实际编排已在 `WorkflowEngine.create_approval`
  （`workflow_engine.py:158-190`）做全**：emit `approval.required` + 落库 + 状态流转都接了。
  → 删这几行 TODO，改为注释"编排在上层 WorkflowEngine，本服务只管落库"。

**✅ 改了什么（2026-08-26）**：`app/service/approval.py` create() 删步骤 3/4/5 三行为证 TODO，改一行注释
「本服务只管落库 + 启动超时定时器；编排（Interrupt/Task->waiting_approval/WS approval.required）已在上层
WorkflowEngine.create_approval 做全」。**结果：ruff 全绿；`tests/test_tasks_api.py -k approval` 5 passed**。

---

## 决策记录

- **用文档文档 + 小步提交**：每修一项先改代码再更新本文，一个功能一个提交（对齐工程规则 13）。
- **domain/ 收敛属于大改红线段，不在本期默认范围**：先删除留档，防架构反噬已跑通逻辑。

## 当前测试基线（收尾快照）

- `tests/` **260 passed / 7 skipped**；boss_chat **15**；boss_extract_jobs **43**（分开进程跑）。
- 上次 Boss 四修提交 `75a07ea..160b552` **本地未推送**，待用户确认。

## 下一会话首个动作

1. 修 **A（retry 入队）**：补 `queue.enqueue` + 测试 → 提交 → 更新本文 `[x]`。
2. 顺手清 **D（approval.py 过时注释）** 与 **B2 的 events.py / approval_manager.py 死壳**。
3. 就 **B1（domain 收敛 vs 删除留档）** 征询用户方向后决定。