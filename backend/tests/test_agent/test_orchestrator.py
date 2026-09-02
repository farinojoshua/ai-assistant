from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.agent.events import ErrorEvent, TextEvent, ToolEvent
from app.agent.orchestrator import run_turn
from app.config import Settings
from app.db.models import AuditLog, User
from app.llm.base import LLMResponse, ToolCall
from app.llm.fake import FakeProvider
from app.tools.base import ToolContext


@pytest.fixture
def ctx(company_gateway) -> ToolContext:
    tid = uuid.uuid4()
    user = User(
        id=uuid.uuid4(),
        tenant_id=tid,
        email="u@test",
        password_hash="x",
        nama="U",
        role="user",
    )
    return ToolContext(user=user, tenant_id=tid, db=company_gateway)


def _tool_use(name: str, args: dict, call_id: str = "c1") -> LLMResponse:
    return LLMResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
    )


def _stok(nilai: str) -> dict:
    return {
        "view": "v_stok",
        "filter": [{"kolom": "nama", "operator": "contains", "nilai": nilai}],
    }


async def _collect(gen):
    return [e async for e in gen]


async def _audit_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()


async def test_single_tool_then_answer(ctx, db) -> None:
    provider = FakeProvider(
        script=[
            _tool_use("ambil_data", _stok("powerbank")),
            LLMResponse(text="Stok powerbank: 18 + 11.", stop_reason="end_turn"),
        ]
    )
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="stok powerbank?",
        )
    )
    assert isinstance(events[0], ToolEvent)
    assert events[0].name == "ambil_data"
    assert isinstance(events[-1], TextEvent)
    assert "powerbank" in events[-1].text.lower()

    rows = (await db.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tool_name == "ambil_data"
    assert rows[0].row_count == 2
    assert rows[0].error is None

    # the second LLM call must have seen the tool result
    second_call_msgs = provider.calls[1][0]
    assert any(m.role == "tool" for m in second_call_msgs)


async def test_two_tools_in_one_turn(ctx, db) -> None:
    provider = FakeProvider(
        script=[
            LLMResponse(
                stop_reason="tool_use",
                tool_calls=[
                    ToolCall(id="a", name="ambil_data", arguments=_stok("kabel")),
                    ToolCall(id="b", name="ambil_data", arguments=_stok("mouse")),
                ],
            ),
            LLMResponse(text="ok", stop_reason="end_turn"),
        ]
    )
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="cek dua barang",
        )
    )
    assert sum(isinstance(e, ToolEvent) for e in events) == 2
    assert await _audit_count(db) == 2


async def test_max_iterations(ctx, db) -> None:
    provider = FakeProvider(
        script=[_tool_use("ambil_data", _stok("kabel"), f"c{i}") for i in range(10)]
    )
    settings = Settings(agent_max_iterations=3)
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="loop",
            settings=settings,
        )
    )
    assert isinstance(events[-1], ErrorEvent)
    assert provider._i == 3  # stopped after 3 model calls
    assert await _audit_count(db) == 3


async def test_tool_timeout(ctx, db, monkeypatch) -> None:
    import asyncio

    from app.tools.ambil_data import AmbilData

    async def _slow(self, args, ctx):  # noqa: ANN001
        await asyncio.sleep(2)
        return {"rows": []}

    monkeypatch.setattr(AmbilData, "run", _slow)
    provider = FakeProvider(
        script=[
            _tool_use("ambil_data", _stok("kabel")),
            LLMResponse(text="maaf, timeout", stop_reason="end_turn"),
        ]
    )
    settings = Settings(agent_tool_timeout_s=1)
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="x",
            settings=settings,
        )
    )
    assert isinstance(events[-1], TextEvent)
    row = (await db.execute(select(AuditLog))).scalar_one()
    assert row.error == "timeout"


async def test_bad_args_returned_to_model(ctx, db) -> None:
    provider = FakeProvider(
        script=[
            _tool_use("ambil_data", {"view": "v_stok", "limit": 999}),  # > max 200
            LLMResponse(text="argumen kurang", stop_reason="end_turn"),
        ]
    )
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="x",
        )
    )
    assert isinstance(events[-1], TextEvent)
    row = (await db.execute(select(AuditLog))).scalar_one()
    assert "tidak valid" in row.error


async def test_unknown_tool_name(ctx, db) -> None:
    provider = FakeProvider(
        script=[
            _tool_use("tool_hantu", {"x": 1}),
            LLMResponse(text="tidak ada tool itu", stop_reason="end_turn"),
        ]
    )
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="x",
        )
    )
    assert isinstance(events[-1], TextEvent)
    row = (await db.execute(select(AuditLog))).scalar_one()
    assert row.tool_name == "tool_hantu"
    assert "tidak tersedia" in row.error


async def test_llm_error_yields_error_event(ctx, db) -> None:
    provider = FakeProvider(script=[RuntimeError("connection reset")])
    events = await _collect(
        run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=db,
            history=[],
            user_message="x",
        )
    )
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "connection reset" in events[0].message
