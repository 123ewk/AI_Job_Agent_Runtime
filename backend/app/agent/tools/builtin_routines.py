"""预写**只读**辅助例程（doc 17 业务例程内容，首条：jobs.load_more）。

与垂直服务（boss.chat / boss_extract_jobs，基于 chrome_javascript 注入）互补：
这些例程走确定性 RoutineRunner——chrome_read_page 读 a11y 树 + 特征匹配 ref，
无 LLM、省 token、无写副作用。只读例程不落库、不写库、不含 Enter/发送，
写操作（发送/投递）一律走垂直服务的 approved 红线（doc 14）。

SkillExecutor 自建 registry 时自动把 `builtin_readonly_routines()` 注册进去；
注入自定义 registry 的调用方需自行决定是否注册（并存互不干扰）。
"""

from __future__ import annotations

from app.agent.tools.routine import Routine, RoutineStep, TargetSpec


def builtin_readonly_routines() -> list[Routine]:
    """返回 SkillExecutor 默认注册的内置只读例程清单。"""
    return [
        Routine(
            id="jobs.load_more",
            skill="browser.load_more",
            description="加载更多：滚动/翻页预算路径，点击「加载更多」按钮（只读，不写库不发送）",
            steps=[
                RoutineStep(
                    tool="chrome_click_element",
                    target=TargetSpec(label_contains="加载更多"),
                    args={},
                ),
            ],
        ),
    ]
