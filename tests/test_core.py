import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sipl import ast
from sipl.ast import SIPLRuntimeError, SIPLSyntaxError, format_expr
from sipl.cli import EXIT_OK, EXIT_RUNTIME_OR_FAIL, EXIT_SYNTAX_ERROR, EXIT_USAGE_ERROR, main
from sipl.conformance import run_conformance_suite
from sipl.interpreter import trace
from sipl.interpreter.runtime import Interpreter, run_program
from sipl.interpreter.state import ExecutionState, parse_state_arg
from sipl.interpreter.trace import TraceEvent, TraceEventType
from sipl.parser import load_grammar, parse, parse_all

ROOT_DIR = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT_DIR / "examples"

POSITIVE_PROGRAMS = [
    ("skip", "begin skip end"),
    ("assign", "begin X := 42 end"),
    ("neg", "begin X := -17; Y := X + -3 end"),
    ("power", "begin R := 1; while Y > 0 do begin R := R * X; Y := Y - 1 end end"),
    ("div_loop", "begin R := 0; while X >= Y do begin X := X - Y; R := R + 1 end end"),
    ("blocks", "begin begin X := 1; Y := 2 end; begin Z := X + Y end end"),
    ("if_else", "begin if X > 0 then R := X else R := 0 - X end"),
    ("unicode", "begin if ¬(X = 0 ∨ Y > 5) ∧ (X ≥ 1 ∨ Y ≤ 2) then skip else R := X ∗ 2 − 1 end"),
    ("ascii_ops", "begin if not (A == 0 or B != 3) and (C < 10 and D <= 20) then R := A div 2 + B mod 3 else skip end"),
    ("parens", "begin if ((X + 1) * (Y - 2) > 0) then R := ((X + Y) * 2) else R := 0 end"),
    ("comments", "# line\nbegin // c\n /* b */ X := 1; Y := X + 2 end"),
    ("idents", "begin _tmp1 := 5; Var_2 := _tmp1 * 2 end"),
]

NEGATIVE_PROGRAMS = [
    ("empty", ""),
    ("only_comments", "# c\n/* b */"),
    ("no_begin", "X := 1"),
    ("no_end", "begin X := 1"),
    ("trailing_semi", "begin X := 1; end"),
    ("double_semi", "begin X := 1;; Y := 2 end"),
    ("single_eq", "begin X = 1 end"),
    ("kw_var", "begin while := 1 end"),
    ("if_no_else", "begin if X > 0 then X := 1 end"),
    ("while_no_do", "begin while X > 0 X := 1 end"),
    ("unclosed_paren", "begin X := (1 + 2 end"),
    ("trailing_tok", "begin skip end skip"),
    ("bad_char", "begin X := 1 @ 2 end"),
    ("unclosed_comment", "begin /* unclosed skip end"),
    ("digit_ident", "begin 1abc := 5 end"),
]


def invoke_cli(argv: list[str], stdin_text: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdin=io.StringIO(stdin_text), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class TestSIPLCore(unittest.TestCase):
    def test_grammar_and_examples(self) -> None:
        g = load_grammar()
        for rule in ("program:", "?stmt:", "?aexp:", "?bexp:"):
            self.assertIn(rule, g)
        self.assertIn("while", g)
        self.assertGreaterEqual(len(POSITIVE_PROGRAMS), 10)
        for name, src in POSITIVE_PROGRAMS:
            with self.subTest(pos=name):
                self.assertEqual(parse(src).kind, "Program")
        self.assertGreaterEqual(len(NEGATIVE_PROGRAMS), 10)
        for name, src in NEGATIVE_PROGRAMS:
            with self.subTest(neg=name):
                with self.assertRaises(SIPLSyntaxError):
                    parse(src)
        files = sorted(EXAMPLES_DIR.glob("*.sipl"))
        self.assertEqual(len(files), 3)
        for p in files:
            self.assertEqual(parse(p.read_text(encoding="utf-8")).kind, "Program")

    def test_ast_spans_precedence_and_diagnostics(self) -> None:
        src = "begin\n  R := 1;\n  X := R + 2 * 3\nend"
        res = parse_all(src)
        self.assertIsInstance(res.ast, ast.Program)
        self.assertEqual(res.ast.span.extract(src), src)
        assert isinstance(res.ast.body, ast.Seq) and isinstance(res.ast.body.second, ast.Assign)
        self.assertIsInstance(res.ast.body.second.expr, ast.BinaryArithOp)
        self.assertEqual(format_expr(res.ast.body.second.expr), "(R + (2 * 3))")

        wseq = parse("begin while X > 0 do X := X - 1; R := X end")
        assert isinstance(wseq.body, ast.Seq)
        self.assertIsInstance(wseq.body.first, ast.WhileDo)

        cast = parse("begin if ((X + 1) * 2 > 10) and not (Y = 0) then begin skip end else skip end")
        assert isinstance(cast.body, ast.IfThenElse) and isinstance(cast.body.condition, ast.BoolBinaryOp)
        self.assertIsInstance(cast.body.condition.left, ast.RelOp)
        self.assertIsInstance(cast.body.condition.right, ast.BoolNot)
        self.assertIsInstance(cast.body.then_branch, ast.Block)
        self.assertIsInstance(cast.body.else_branch, ast.Skip)

        neg = parse("begin A := -5; B := -X; C := A-1 end")
        assert isinstance(neg.body, ast.Seq) and isinstance(neg.body.first, ast.Seq)
        s1, s2, s3 = neg.body.first.first, neg.body.first.second, neg.body.second
        assert isinstance(s1, ast.Assign) and isinstance(s2, ast.Assign) and isinstance(s3, ast.Assign)
        self.assertIsInstance(s1.expr, ast.NumberLiteral)
        self.assertIsInstance(s2.expr, ast.UnaryArithOp)
        self.assertIsInstance(s3.expr, ast.BinaryArithOp)

        with self.assertRaises(SIPLSyntaxError) as ctx:
            parse("begin\n  X := 10;\n  Y = 20\nend")
        self.assertEqual(ctx.exception.diagnostic.span.line, 3)
        self.assertIn("Y = 20", ctx.exception.diagnostic.format_human("begin\n  X := 10;\n  Y = 20\nend"))

    def test_interpreter_and_errors(self) -> None:
        self.assertEqual(
            run_program((EXAMPLES_DIR / "power.sipl").read_text(encoding="utf-8"), {"X": 5, "Y": 2}).final_state,
            {"R": 25, "X": 5, "Y": 0},
        )
        self.assertEqual(
            run_program((EXAMPLES_DIR / "division.sipl").read_text(encoding="utf-8"), {"X": 7, "Y": 4}).final_state,
            {"R": 1, "X": 3, "Y": 4},
        )
        self.assertEqual(
            run_program((EXAMPLES_DIR / "factorial.sipl").read_text(encoding="utf-8"), {"N": 6}).final_state["R"], 720
        )
        ops = "begin A := 10 + 2 * 3 - 4; B := A div 3; C := A mod 5; D := -B; if (B = 4 and C != 0) or not (D > 0) then if C <= 2 and A >= 12 and D < 0 then OK := 1 else OK := 2 else OK := 0 end"
        self.assertEqual(run_program(ops).final_state, {"A": 12, "B": 4, "C": 2, "D": -4, "OK": 1})

        with self.assertRaises(SIPLRuntimeError) as u:
            run_program("begin\n  R := Missing + 1\nend")
        self.assertEqual((u.exception.diagnostic.code, u.exception.diagnostic.span.line), ("RUN001", 2))
        with self.assertRaises(SIPLRuntimeError) as d1:
            run_program("begin X := 10 div 0 end")
        self.assertEqual(d1.exception.diagnostic.code, "RUN002")
        with self.assertRaises(SIPLRuntimeError) as d2:
            run_program("begin X := 10 mod 0 end")
        self.assertEqual(d2.exception.diagnostic.code, "RUN002")

        interp = Interpreter(max_steps=20)
        with self.assertRaises(SIPLRuntimeError) as m:
            interp.run("begin while 1 = 1 do skip end")
        self.assertEqual(m.exception.diagnostic.code, "RUN003")
        assert interp.last_trace is not None and interp.last_trace.status == "error"

        st = ExecutionState({"X": 5, "R": 25})
        self.assertEqual(st.format_practicum(), "[R ↦ 25, X ↦ 5]")
        self.assertEqual(parse_state_arg("X=5, Y=-2"), {"X": 5, "Y": -2})
        self.assertEqual(parse_state_arg('{"X": 5}'), {"X": 5})
        with self.assertRaises(ValueError):
            parse_state_arg("X=abc")

    def test_trace_and_cli(self) -> None:
        seen: list[TraceEvent] = []
        src = (EXAMPLES_DIR / "power.sipl").read_text(encoding="utf-8")
        res = Interpreter(listeners=[seen.append]).run(src, {"X": 5, "Y": 2})
        self.assertEqual(seen, list(res.trace.events))
        expected_types = {
            TraceEventType.BEFORE_STATEMENT,
            TraceEventType.AFTER_STATEMENT,
            TraceEventType.VARIABLE_CHANGED,
            TraceEventType.CONDITION_EVALUATED,
            TraceEventType.EXECUTION_FINISHED,
        }
        self.assertEqual({ev.event_type for ev in res.trace.events}, expected_types)
        conds = res.trace.filter_by_type(TraceEventType.CONDITION_EVALUATED)
        self.assertEqual([ev.result for ev in conds if isinstance(ev, trace.ConditionEvaluated)], [True, True, False])
        self.assertIsInstance(res.trace.events[0], trace.BeforeStatement)
        self.assertIsInstance(res.trace.events[-2], trace.AfterStatement)
        self.assertIsInstance(res.trace.events[-1], trace.ExecutionFinished)
        self.assertTrue(any(isinstance(ev, trace.VariableChanged) for ev in res.trace.events))
        self.assertIn("ConditionEvaluated", res.trace.format_text())

        p = str(EXAMPLES_DIR / "power.sipl")
        self.assertEqual(invoke_cli(["parse", p, "--concrete", "--json"])[0], EXIT_OK)
        c, out, _ = invoke_cli(["check", p, "--json"])
        self.assertEqual((c, json.loads(out)["token_count"]), (EXIT_OK, 24))
        c, out, _ = invoke_cli(["run", p, "--state", "X=5,Y=2", "--json"])
        self.assertEqual((c, json.loads(out)["final_state"]), (EXIT_OK, {"R": 25, "X": 5, "Y": 0}))
        c, out, _ = invoke_cli(["trace", "-", "--state", "X=2,Y=3", "--json"], stdin_text=src)
        self.assertEqual((c, json.loads(out)["final_state"]["R"]), (EXIT_OK, 8))
        self.assertEqual(invoke_cli(["check", "-", "--json"], stdin_text="X := 1")[0], EXIT_SYNTAX_ERROR)
        self.assertEqual(invoke_cli(["run", "-", "--json"], stdin_text="begin X := Undef end")[0], EXIT_RUNTIME_OR_FAIL)
        self.assertEqual(invoke_cli(["run", "/no/such/file.sipl", "--json"])[0], EXIT_USAGE_ERROR)

    def test_conformance_suite(self) -> None:
        self.assertTrue(run_conformance_suite().passed)
        prev = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(ROOT_DIR / "src")
        try:
            self.assertTrue(run_conformance_suite(external_cmd=f"{sys.executable} -m sipl").passed)
        finally:
            if prev is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = prev

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            bad = {"id": "bad", "source": "begin X := 1 end", "expected": {"exit_code": 0, "final_state": {"X": 999}}}
            json.dump({"cases": [bad]}, tf)
            tmp = tf.name
        try:
            self.assertFalse(run_conformance_suite(suite_path=tmp).passed)
        finally:
            Path(tmp).unlink(missing_ok=True)
