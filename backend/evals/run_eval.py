"""Run the eval question set against the live provider + company DB.

    python evals/run_eval.py            # all questions
    python evals/run_eval.py stok       # only a category
    python evals/run_eval.py --json out.json

Scoring per question:
  - tools_ok      : every tool in expect_tools was called
  - answer_ok     : every string in expect_contains appears in the answer
  - no_tool_ok    : (off-topic only) no tool was called
A question PASSES if all applicable checks pass.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from app.agent.events import ErrorEvent, TextEvent, ToolEvent
from app.agent.orchestrator import run_turn
from app.db.app_db import get_sessionmaker
from app.db.company_db import CompanyDbGateway
from app.db.models import User
from app.llm.base import Message
from app.llm.registry import get_provider
from app.tools.base import ToolContext

QUESTIONS = json.loads((Path(__file__).parent / "questions.json").read_text("utf-8"))

C_OK, C_NO, C_DIM, C_RESET = "\033[32m", "\033[31m", "\033[90m", "\033[0m"


async def _ask(provider, ctx, session, question, history):
    tools_called: list[str] = []
    answer = ""
    err = None
    async for ev in run_turn(
        provider=provider,
        ctx=ctx,
        audit_session=session,
        history=history,
        user_message=question,
    ):
        if isinstance(ev, ToolEvent):
            tools_called.append(ev.name)
        elif isinstance(ev, TextEvent):
            answer = ev.text
        elif isinstance(ev, ErrorEvent):
            err = ev.message
    await session.rollback()
    return tools_called, answer, err


def _norm(s: str) -> str:
    """Fold Unicode punctuation the model likes to use into ASCII."""
    for a, b in (
        (" ", " "), (" ", " "), (" ", " "),
        ("‑", "-"), ("–", "-"), ("—", "-"),
        ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
    ):
        s = s.replace(a, b)
    return s.lower()


def _score(q, tools_called, answer):
    checks = {}
    if q.get("expect_tools"):
        checks["tools"] = all(t in tools_called for t in q["expect_tools"])
    if q.get("expect_no_tool"):
        checks["no_tool"] = len(tools_called) == 0
    if q.get("expect_contains"):
        low = _norm(answer)
        checks["answer"] = all(_norm(s) in low for s in q["expect_contains"])
    return checks, all(checks.values()) if checks else True


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    argv = sys.argv[1:]
    json_out = None
    if "--json" in argv:
        i = argv.index("--json")
        json_out = argv[i + 1]
        del argv[i : i + 2]
    positional = [a for a in argv if not a.startswith("--")]
    cat_filter = positional[0] if positional else None

    provider = get_provider()
    gateway = CompanyDbGateway.from_settings()
    user = User(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="eval@test",
        password_hash="x", nama="Eval", role="user",
    )
    ctx = ToolContext(user=user, tenant_id=user.tenant_id, db=gateway)

    answers: dict[str, str] = {}
    results = []

    async with get_sessionmaker()() as session:
        for q in QUESTIONS:
            if cat_filter and q["kategori"] != cat_filter:
                continue
            history: list[Message] = []
            if q.get("history_from"):
                prev = q["history_from"]
                history = [
                    Message(role="user", content=_q_text(prev)),
                    Message(role="assistant", content=answers.get(prev, "")),
                ]
            t0 = time.monotonic()
            tools, answer, err = await _ask(
                provider, ctx, session, q["pertanyaan"], history
            )
            dt = time.monotonic() - t0
            answers[q["id"]] = answer
            checks, passed = _score(q, tools, answer)
            results.append(
                {
                    "id": q["id"], "kategori": q["kategori"], "passed": passed,
                    "checks": checks, "tools_called": tools, "error": err,
                    "answer": answer, "seconds": round(dt, 1),
                }
            )
            mark = f"{C_OK}PASS{C_RESET}" if passed else f"{C_NO}FAIL{C_RESET}"
            detail = " ".join(
                f"{k}={'ok' if v else 'X'}" for k, v in checks.items()
            )
            print(f"{mark}  {q['id']:<28} {detail:<26} {dt:4.1f}s  tools={tools}")
            if not passed:
                print(f"{C_DIM}      → {answer[:160].replace(chr(10),' ')}{C_RESET}")

    await gateway.dispose()

    total = len(results)
    passed = sum(r["passed"] for r in results)
    print(f"\n{'='*60}")
    print(f"TOTAL: {passed}/{total} lulus ({100*passed//max(total,1)}%)")
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["kategori"], []).append(r["passed"])
    for cat, vals in by_cat.items():
        print(f"  {cat:<12} {sum(vals)}/{len(vals)}")
    avg = sum(r["seconds"] for r in results) / max(total, 1)
    print(f"  rata-rata latensi: {avg:.1f}s / pertanyaan")

    if json_out:
        Path(json_out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), "utf-8"
        )
        print(f"\ndetail -> {json_out}")


def _q_text(qid: str) -> str:
    for q in QUESTIONS:
        if q["id"] == qid:
            return q["pertanyaan"]
    return ""


if __name__ == "__main__":
    asyncio.run(main())
