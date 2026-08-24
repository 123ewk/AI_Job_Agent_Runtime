"""预写**只读**辅助例程注册表（doc 17 业务例程，当前为空、保留框架）。

与垂直服务（boss.chat / boss_extract_jobs，基于 chrome_javascript 注入）互补：
例程走确定性 RoutineRunner——chrome_read_page 读 a11y 树 + 特征匹配 ref，
无 LLM、省 token、无写副作用。只读例程不落库、不写库、不含 Enter/发送，
写操作（发送/投递）一律走垂直服务的 approved 红线（doc 14）。

**为何当前为空**：曾预写 jobs.load_more（点「加载更多」按钮），已删除——Boss
岗位列表是**无限滚动、无翻页按钮**（逆向文档），且「滚动加载 = 触发新 zhipin 请求」，
违反只读红线（滚动加载新页 = 真人滚动）。Boss 站「加载更多」意图没有安全的自动只读
实现，落入此盘的意图回退 browser.generic（读树 + 双层兜底，都不自动写操作）。
未来新增例程时在下面列表追加（如登录态翻转/只读巡检类）。
"""

from __future__ import annotations

from app.agent.tools.routine import Routine


def builtin_readonly_routines() -> list[Routine]:
    """返回 SkillExecutor 默认注册的内置只读例程清单（当前无）。"""
    return []
