from dataclasses import dataclass, fields
from enum import Enum
from typing import Any

from sipl.ast import Diagnostic, SourceSpan


class TraceEventType(str, Enum):
    BEFORE_STATEMENT = "BeforeStatement"
    AFTER_STATEMENT = "AfterStatement"
    VARIABLE_CHANGED = "VariableChanged"
    CONDITION_EVALUATED = "ConditionEvaluated"
    EXECUTION_FINISHED = "ExecutionFinished"


@dataclass(frozen=True)
class TraceEvent:
    event_type: TraceEventType
    step: int
    ast_node_id: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.event_type.value,
            "step": self.step,
            "span": self.span.format_short(),
        }
        for f in fields(self):
            if f.name in ("event_type", "step", "ast_node_id", "span"):
                continue
            val = getattr(self, f.name)
            out[f.name] = dict(val) if isinstance(val, dict) else val
        return out

    def format_line(self) -> str:
        return f"[step {self.step}] {self.event_type.value} ({self.span.format_short()})"


@dataclass(frozen=True)
class BeforeStatement(TraceEvent):
    stmt_kind: str
    rule_id: str
    state_before: dict[str, int]

    def format_line(self) -> str:
        return f"[{self.step}] BeforeStatement {self.stmt_kind} state={self.state_before}"


@dataclass(frozen=True)
class AfterStatement(TraceEvent):
    stmt_kind: str
    rule_id: str
    state_after: dict[str, int]

    def format_line(self) -> str:
        return f"[{self.step}] AfterStatement  {self.stmt_kind} state={self.state_after}"


@dataclass(frozen=True)
class VariableChanged(TraceEvent):
    variable: str
    old_value: int | None
    new_value: int

    def format_line(self) -> str:
        old_str = "undef" if self.old_value is None else str(self.old_value)
        return f"[{self.step}] VariableChanged {self.variable}: {old_str} -> {self.new_value}"


@dataclass(frozen=True)
class ConditionEvaluated(TraceEvent):
    condition_text: str
    result: bool
    state: dict[str, int]

    def format_line(self) -> str:
        return f"[{self.step}] ConditionEvaluated ({self.condition_text}) -> {self.result}"


@dataclass(frozen=True)
class ExecutionFinished(TraceEvent):
    total_steps: int
    status: str
    final_state: dict[str, int]
    error: dict[str, Any] | None = None

    def format_line(self) -> str:
        return f"[{self.step}] ExecutionFinished status={self.status} steps={self.total_steps} final_state={self.final_state}"


@dataclass(frozen=True)
class ExecutionTrace:
    initial_state: dict[str, int]
    final_state: dict[str, int]
    steps_executed: int
    status: str
    events: tuple[TraceEvent, ...]
    error: Diagnostic | None = None

    def filter_by_type(self, event_type: TraceEventType) -> list[TraceEvent]:
        return [ev for ev in self.events if ev.event_type == event_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_state": dict(self.initial_state),
            "final_state": dict(self.final_state),
            "steps_executed": self.steps_executed,
            "status": self.status,
            "error": self.error.to_dict() if self.error is not None else None,
            "events": [ev.to_dict() for ev in self.events],
        }

    def format_text(self) -> str:
        lines = [f"Initial state: {self.initial_state}"]
        lines.extend(ev.format_line() for ev in self.events)
        lines.append(f"Final state ({self.status}): {self.final_state}")
        return "\n".join(lines)
