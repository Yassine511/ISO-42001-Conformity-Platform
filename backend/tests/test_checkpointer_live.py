"""Live PostgresSaver smoke test — needs a running postgres (docker compose).

Skipped unless INT102_LIVE_PG=1: CI and the default offline suite never touch
a real database. Run manually after `docker compose up -d postgres`:

    INT102_LIVE_PG=1 LANGGRAPH_STRICT_MSGPACK=true python -m pytest tests/test_checkpointer_live.py -q
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INT102_LIVE_PG") != "1", reason="live postgres test (set INT102_LIVE_PG=1)"
)


def test_checkpointer_writes_and_resumes():
    from langgraph.graph import END, StateGraph
    from typing_extensions import TypedDict

    from app.pipeline.graph import checkpointer_lifespan

    calls = {"a": 0, "b": 0}

    class S(TypedDict, total=False):
        x: int

    def node_a(state: S) -> dict:
        calls["a"] += 1
        return {"x": state.get("x", 0) + 1}

    def node_b(state: S) -> dict:
        calls["b"] += 1
        return {"x": state["x"] + 10}

    with checkpointer_lifespan() as saver:
        g = StateGraph(S)
        g.add_node("a", node_a)
        g.add_node("b", node_b)
        g.set_entry_point("a")
        g.add_edge("a", "b")
        g.add_edge("b", END)
        graph = g.compile(checkpointer=saver, interrupt_before=["b"])

        config = {"configurable": {"thread_id": "live-smoke-test"}}
        graph.invoke({"x": 0}, config)
        assert calls == {"a": 1, "b": 0}  # interrupted before b

        # checkpoint resume: invoke(None, config) — node a must NOT rerun
        final = graph.invoke(None, config)
        assert calls == {"a": 1, "b": 1}
        assert final["x"] == 11
