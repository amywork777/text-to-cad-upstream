"""``empty_operation``: an operation whose toolpath cuts nothing (rapids alone, or no moves at all).

A planner that cannot cut its feature says so itself (a :class:`~cadgen._internal.cam.job_errors.PlanError` of kind
``empty_operation``, ``tool_too_large``, ...); this is the net under every planner: an operation the job asked for
that put no cutting move in the program is an error, never a silent row. From the parallel cam build.
"""

from __future__ import annotations

from cadgen._internal.cam.checks.base import finding

__all__ = ["run"]


def run(ctx) -> list[dict]:
    from cadgen._internal.cam.ir import DWELL, RAPID

    out = []
    for op in ctx.ops:
        if "plan_error" in op.meta:
            continue            # its own finding says why
        plan = ctx.setup_plan(op.setup)
        moves = plan.toolpath.moves[op.start:op.end] if plan.toolpath is not None else ()
        if any(int(kind) not in (RAPID, DWELL) for kind in (moves["kind"] if len(moves) else ())):
            continue
        out.append(finding(
            "empty_operation", "error", "empty_operation",
            f"operation {op.index + 1} ({op.summary}, setup {op.setup}) cuts nothing: its toolpath has no cutting move",
            "check the faces or region it names, its depth, and what the operations before it already took off; drop "
            "the operation if nothing is left to do",
            [{"setup": op.setup, "operation": op.index}]))
    return out
