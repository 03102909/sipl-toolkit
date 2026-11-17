import json
import re
from collections.abc import Mapping

VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ExecutionState:
    def __init__(self, initial: Mapping[str, int] | None = None) -> None:
        self.values: dict[str, int] = {}
        if initial is not None:
            for name, value in initial.items():
                self.set(name, value)

    def get(self, name: str) -> int | None:
        return self.values.get(name)

    def set(self, name: str, value: int) -> tuple[int | None, int]:
        if not isinstance(name, str) or not VAR_NAME_RE.match(name):
            raise ValueError(f"Invalid SIPL variable name: {name!r}")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"SIPL variable '{name}' must hold an integer, got {type(value).__name__}")
        old = self.values.get(name)
        self.values[name] = value
        return old, value

    def snapshot(self) -> dict[str, int]:
        return {key: self.values[key] for key in sorted(self.values)}

    def format_practicum(self) -> str:
        pairs = ", ".join(f"{k} ↦ {v}" for k, v in self.snapshot().items())
        return f"[{pairs}]"

    def __repr__(self) -> str:
        return f"ExecutionState({self.snapshot()!r})"


def parse_state_arg(raw: str | None) -> dict[str, int]:
    if raw is None or not raw.strip():
        return {}
    stripped = raw.strip()
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("JSON state must be an object mapping variable names to integers")
        result: dict[str, int] = {}
        for k, v in parsed.items():
            if not isinstance(k, str) or not VAR_NAME_RE.match(k):
                raise ValueError(f"Invalid variable name in state: {k!r}")
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValueError(f"State value for '{k}' must be an integer, got {v!r}")
            result[k] = v
        return result

    result = {}
    for part in stripped.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Invalid state entry '{item}'; expected KEY=VALUE")
        key, val_str = item.split("=", 1)
        key = key.strip()
        val_str = val_str.strip()
        if not VAR_NAME_RE.match(key):
            raise ValueError(f"Invalid variable name '{key}' in state")
        try:
            val = int(val_str)
        except ValueError as exc:
            raise ValueError(f"State value for '{key}' must be an integer, got '{val_str}'") from exc
        result[key] = val
    return result
