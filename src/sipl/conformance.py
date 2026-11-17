import json
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sipl.ast import SIPLRuntimeError, SIPLSyntaxError
from sipl.interpreter.runtime import Interpreter
from sipl.parser import parse


@dataclass(frozen=True)
class CaseResult:
    id: str
    category: str
    passed: bool
    message: str
    details: dict[str, Any]


@dataclass(frozen=True)
class SuiteResult:
    suite_path: str
    total: int
    passed_count: int
    failed_count: int
    passed: bool
    results: tuple[CaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "results": [asdict(r) for r in self.results]}


def default_suite_path() -> Path:
    for path in (Path(__file__).resolve().parents[2] / "tests" / "suite.json", Path.cwd() / "tests" / "suite.json"):
        if path.is_file():
            return path
    return Path.cwd() / "tests" / "suite.json"


def match_ast_subset(actual: Any, expected: Any, path: str = "ast") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected dict, got {type(actual).__name__}"]
        errs: list[str] = []
        for k, v in expected.items():
            msg = [f"{path}.{k}: missing field"] if k not in actual else match_ast_subset(actual[k], v, f"{path}.{k}")
            errs.extend(msg)
        return errs
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [f"{path}: list length mismatch"]
        pairs = enumerate(zip(actual, expected, strict=True))
        return [m for i, (a, e) in pairs for m in match_ast_subset(a, e, f"{path}[{i}]")]
    return [] if actual == expected else [f"{path}: expected {expected!r}, got {actual!r}"]


def _sub_cmd(cmd: list[str], src: str) -> tuple[int, dict[str, Any], str]:
    p = subprocess.run(cmd, input=src, text=True, capture_output=True, check=False)
    data = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    return p.returncode, data, p.stderr.strip()


def run_case(src: str, init_st: dict[str, int], max_steps: int, ext_cmd: str | None) -> tuple[int, Any, Any, Any]:
    if not ext_cmd:
        try:
            ast_root = parse(src)
        except SIPLSyntaxError as exc:
            return 2, None, None, exc.diagnostic.to_dict()
        ast_d = ast_root.to_dict()
        try:
            return 0, ast_d, Interpreter(max_steps=max_steps).run(ast_root, initial_state=init_st).final_state, None
        except SIPLRuntimeError as exc:
            return 1, ast_d, None, exc.diagnostic.to_dict()

    base = shlex.split(ext_cmd)
    c1, pj, err1 = _sub_cmd([*base, "parse", "-", "--json"], src)
    if c1 != 0:
        return c1, pj.get("ast"), None, pj.get("error") or {"message": err1}
    run_cmd = [*base, "run", "-", "--state", json.dumps(init_st), "--max-steps", str(max_steps), "--json"]
    c2, rj, _ = _sub_cmd(run_cmd, src)
    return (0, pj.get("ast"), rj.get("final_state"), None) if c2 == 0 else (c2, pj.get("ast"), None, rj.get("error"))


def evaluate_case(case: dict[str, Any], external_cmd: str | None = None) -> CaseResult:
    cid, cat = str(case["id"]), str(case.get("category", "execution"))
    src, exp = str(case["source"]), dict(case["expected"])
    init_st, max_steps = dict(case.get("initial_state", {})), int(case.get("max_steps", 10_000))
    code, ast_d, fin_st, err_d = run_case(src, init_st, max_steps, external_cmd)
    fails: list[str] = []
    if exp.get("exit_code") is not None and code != exp["exit_code"]:
        fails.append(f"exit_code expected {exp['exit_code']}, got {code}")
    if "final_state" in exp and fin_st != exp["final_state"]:
        fails.append(f"final_state expected {exp['final_state']}, got {fin_st}")
    if "ast" in exp:
        fails.extend(["expected AST, parsing failed"] if ast_d is None else match_ast_subset(ast_d, exp["ast"]))
    if "error_code" in exp and (err_d or {}).get("code") != exp["error_code"]:
        fails.append(f"error_code expected {exp['error_code']!r}, got {(err_d or {}).get('code')!r}")
    if "error_line" in exp:
        span = err_d.get("span") if isinstance(err_d, dict) else None
        line = span.get("line") if isinstance(span, dict) else None
        if line != exp["error_line"]:
            fails.append(f"error_line expected {exp['error_line']}, got {line}")
    details = {"exit_code": code, **({"error": err_d, "final_state": fin_st} if fails else {})}
    return CaseResult(cid, cat, not fails, "; ".join(fails) if fails else "OK", details)


def run_conformance_suite(suite_path: Path | str | None = None, external_cmd: str | None = None) -> SuiteResult:
    path = Path(suite_path) if suite_path is not None else default_suite_path()
    if not path.is_file():
        raise FileNotFoundError(f"Conformance suite file not found: {path}")
    suite_data = json.loads(path.read_text(encoding="utf-8"))
    results = tuple(evaluate_case(c, external_cmd=external_cmd) for c in suite_data.get("cases", []))
    passed_count = sum(1 for r in results if r.passed)
    all_ok = passed_count == len(results) > 0
    return SuiteResult(str(path), len(results), passed_count, len(results) - passed_count, all_ok, results)
