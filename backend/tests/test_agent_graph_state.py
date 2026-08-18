"""graph/state.py reducer 单测（doc 06 §4 语义表逐项覆盖）。"""

from app.agent.graph.state import append, append_dedup, plan_reducer


class TestAppend:
    def test_accumulate_keeps_history(self) -> None:
        existing = [{"a": 1}]
        assert append(existing, [{"b": 2}]) == [{"a": 1}, {"b": 2}]
        # 原列表不被原地修改（reducer 必须纯函数）
        assert existing == [{"a": 1}]

    def test_empty_update_returns_existing(self) -> None:
        assert append([{"a": 1}], []) == [{"a": 1}]
        assert append([{"a": 1}], None) == [{"a": 1}]  # type: ignore[arg-type]


class TestAppendDedup:
    def test_dedup_by_message_id(self) -> None:
        existing = [{"message_id": "m1", "text": "hi"}]
        new = [{"message_id": "m1", "text": "hi"}, {"message_id": "m2", "text": "yo"}]
        assert append_dedup(existing, new) == [
            {"message_id": "m1", "text": "hi"},
            {"message_id": "m2", "text": "yo"},
        ]

    def test_without_message_id_appends_without_dedup(self) -> None:
        existing = [{"text": "observe"}]
        new = [{"text": "observe"}]
        assert len(append_dedup(existing, new)) == 2

    def test_empty_update_returns_existing(self) -> None:
        assert append_dedup([{"message_id": "m1"}], []) == [{"message_id": "m1"}]


class TestPlanReducer:
    def test_nonempty_replaces_whole_plan(self) -> None:
        existing = [{"step": 1}, {"step": 2}]
        new = [{"step": 9}]
        assert plan_reducer(existing, new) == [{"step": 9}]

    def test_empty_update_keeps_existing(self) -> None:
        existing = [{"step": 1}]
        assert plan_reducer(existing, []) == [{"step": 1}]
