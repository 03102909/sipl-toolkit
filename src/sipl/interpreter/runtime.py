from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sipl import ast
from sipl.ast import AExpr, BExpr, Diagnostic, Program, SIPLRuntimeError, SourceSpan, Stmt, format_expr
from sipl.interpreter import trace
from sipl.interpreter.state import ExecutionState
from sipl.interpreter.trace import ExecutionTrace, TraceEvent, TraceEventType
from sipl.parser import parse

ARITH_OPS: dict[str, Callable[[int, int], int]] = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "div": lambda a, b: a // b,
    "mod": lambda a, b: a % b,
}
REL_OPS: dict[str, Callable[[int, int], bool]] = {
    "=": lambda a, b: a == b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "!=": lambda a, b: a != b,
}


@dataclass(frozen=True)
class ExecutionResult:
    ast: Program
    initial_state: dict[str, int]
    final_state: dict[str, int]
    steps_executed: int
    trace: ExecutionTrace

    def to_dict(self, include_trace: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "initial_state": dict(self.initial_state),
            "final_state": dict(self.final_state),
            "steps_executed": self.steps_executed,
            "status": self.trace.status,
        }
        if include_trace:
            data["trace"] = self.trace.to_dict()
        return data


class Interpreter:
    def __init__(
        self, max_steps: int = 10_000, listeners: Sequence[Callable[[TraceEvent], None]] | None = None
    ) -> None:
        if max_steps <= 0:
            raise ValueError(f"max_steps must be positive, got {max_steps}")
        self.max_steps = max_steps
        self.listeners = list(listeners or [])
        self.last_trace: ExecutionTrace | None = None
        self.events: list[TraceEvent] = []
        self.steps = 0

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)
        for listener in self.listeners:
            listener(event)

    def tick(self, span: SourceSpan) -> int:
        self.steps += 1
        if self.steps > self.max_steps:
            msg = f"Execution exceeded maximum step limit ({self.max_steps})"
            raise SIPLRuntimeError(
                Diagnostic("RUN003", "error", msg, span, "Increase --max-steps or fix infinite loop.")
            )
        return self.steps

    def _finish(
        self, status: str, root: Program, init_s: dict[str, int], final_s: dict[str, int], diag: Diagnostic | None
    ) -> ExecutionTrace:
        err_dict = diag.to_dict() if diag else None
        event = trace.ExecutionFinished(
            TraceEventType.EXECUTION_FINISHED,
            self.steps,
            root.node_id,
            root.span,
            self.steps,
            status,
            final_s,
            err_dict,
        )
        self.emit(event)
        self.last_trace = ExecutionTrace(init_s, final_s, self.steps, status, tuple(self.events), diag)
        return self.last_trace

    def run(self, program: Program | str, initial_state: Mapping[str, int] | None = None) -> ExecutionResult:
        ast_root = parse(program) if isinstance(program, str) else program
        state = ExecutionState(initial_state)
        init_snap = state.snapshot()
        self.events = []
        self.steps = 0

        try:
            self.exec_stmt(ast_root.body, state)
        except SIPLRuntimeError as exc:
            self._finish("error", ast_root, init_snap, state.snapshot(), exc.diagnostic)
            raise

        final_snap = state.snapshot()
        tr = self._finish("completed", ast_root, init_snap, final_snap, None)
        return ExecutionResult(ast_root, init_snap, final_snap, self.steps, tr)

    def exec_stmt(self, stmt: Stmt, state: ExecutionState) -> None:
        step = self.tick(stmt.span)
        self.emit(
            trace.BeforeStatement(
                TraceEventType.BEFORE_STATEMENT,
                step,
                stmt.node_id,
                stmt.span,
                stmt.kind,
                stmt.rule_id,
                state.snapshot(),
            )
        )

        if isinstance(stmt, ast.Assign):
            old_val, new_val = state.set(stmt.var, self.eval_aexpr(stmt.expr, state))
            self.emit(
                trace.VariableChanged(
                    TraceEventType.VARIABLE_CHANGED, step, stmt.node_id, stmt.span, stmt.var, old_val, new_val
                )
            )
        elif isinstance(stmt, ast.Seq):
            self.exec_stmt(stmt.first, state)
            self.exec_stmt(stmt.second, state)
        elif isinstance(stmt, ast.IfThenElse):
            branch = stmt.then_branch if self.eval_cond_with_trace(stmt.condition, state, step) else stmt.else_branch
            self.exec_stmt(branch, state)
        elif isinstance(stmt, ast.WhileDo):
            cond_step = step
            while self.eval_cond_with_trace(stmt.condition, state, cond_step):
                self.exec_stmt(stmt.body, state)
                cond_step = self.tick(stmt.condition.span)
        elif isinstance(stmt, ast.Block):
            self.exec_stmt(stmt.body, state)
        elif not isinstance(stmt, ast.Skip):
            raise AssertionError(f"Unsupported statement AST node: {type(stmt).__name__}")

        self.emit(
            trace.AfterStatement(
                TraceEventType.AFTER_STATEMENT,
                self.steps,
                stmt.node_id,
                stmt.span,
                stmt.kind,
                stmt.rule_id,
                state.snapshot(),
            )
        )

    def eval_cond_with_trace(self, cond: BExpr, state: ExecutionState, step: int) -> bool:
        result = self.eval_bexpr(cond, state)
        self.emit(
            trace.ConditionEvaluated(
                TraceEventType.CONDITION_EVALUATED,
                step,
                cond.node_id,
                cond.span,
                format_expr(cond),
                result,
                state.snapshot(),
            )
        )
        return result

    def eval_aexpr(self, expr: AExpr, state: ExecutionState) -> int:
        if isinstance(expr, ast.NumberLiteral):
            return expr.value
        if isinstance(expr, ast.VariableRef):
            val = state.get(expr.name)
            if val is None:
                hint = f"Initialize '{expr.name}' before reading it."
                raise SIPLRuntimeError(
                    Diagnostic("RUN001", "error", f"Undefined variable '{expr.name}'", expr.span, hint)
                )
            return val
        if isinstance(expr, ast.UnaryArithOp):
            operand = self.eval_aexpr(expr.operand, state)
            if expr.op == "-":
                return -operand
            raise AssertionError(f"Unsupported unary operator: {expr.op}")
        if isinstance(expr, ast.BinaryArithOp):
            left = self.eval_aexpr(expr.left, state)
            right = self.eval_aexpr(expr.right, state)
            if expr.op in ("div", "mod") and right == 0:
                kind_name = "division" if expr.op == "div" else "modulo"
                raise SIPLRuntimeError(Diagnostic("RUN002", "error", f"Integer {kind_name} by zero", expr.span))
            return ARITH_OPS[expr.op](left, right)
        raise AssertionError(f"Unsupported arithmetic AST node: {type(expr).__name__}")

    def eval_bexpr(self, expr: BExpr, state: ExecutionState) -> bool:
        if isinstance(expr, ast.RelOp):
            return REL_OPS[expr.op](self.eval_aexpr(expr.left, state), self.eval_aexpr(expr.right, state))
        if isinstance(expr, ast.BoolNot):
            return not self.eval_bexpr(expr.operand, state)
        if isinstance(expr, ast.BoolBinaryOp):
            if expr.op == "or":
                return self.eval_bexpr(expr.left, state) or self.eval_bexpr(expr.right, state)
            if expr.op == "and":
                return self.eval_bexpr(expr.left, state) and self.eval_bexpr(expr.right, state)
        raise AssertionError(f"Unsupported boolean AST node: {type(expr).__name__}")


def run_program(
    program: Program | str, initial_state: Mapping[str, int] | None = None, max_steps: int = 10_000
) -> ExecutionResult:
    return Interpreter(max_steps=max_steps).run(program, initial_state=initial_state)
