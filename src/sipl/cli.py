import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from sipl.ast import SIPLDiagnosticError, SIPLRuntimeError, SIPLSyntaxError
from sipl.conformance import run_conformance_suite
from sipl.interpreter.runtime import Interpreter
from sipl.interpreter.state import parse_state_arg
from sipl.parser import ParseResult, parse_all
from sipl.visualization import ast_viz, compare, parse_tree

EXIT_OK = 0
EXIT_RUNTIME_OR_FAIL = 1
EXIT_SYNTAX_ERROR = 2
EXIT_USAGE_ERROR = 3


def emit_json(out: TextIO, payload: dict[str, Any]) -> None:
    out.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def emit_diag(
    err: SIPLDiagnosticError, source: str, cmd: str, as_json: bool, out: TextIO, err_out: TextIO, extra: Any = None
) -> int:
    if as_json:
        emit_json(out, {"ok": False, "command": cmd, "error": err.diagnostic.to_dict(), **(extra or {})})
    else:
        err_out.write(err.diagnostic.format_human(source) + "\n")
    return EXIT_SYNTAX_ERROR if isinstance(err, SIPLSyntaxError) else EXIT_RUNTIME_OR_FAIL


def render_viz_payload(target: str, fmt: str, source: str, parsed: ParseResult) -> str:
    pt = parsed.parse_tree
    root = parsed.ast
    if target == "parse-tree":
        if fmt == "text":
            return parse_tree.render_parse_tree_text(pt, source)
        if fmt == "json":
            return json.dumps(
                parse_tree.render_parse_tree_json(pt, source, parsed.tokens), indent=2, ensure_ascii=False
            )
        if fmt == "dot":
            return parse_tree.render_parse_tree_dot(pt, source)
        if fmt == "svg":
            return parse_tree.render_parse_tree_svg(pt, source)
    elif target == "ast":
        if fmt == "text":
            return ast_viz.render_ast_text(root, source)
        if fmt == "json":
            return json.dumps(ast_viz.render_ast_json(root, source), indent=2, ensure_ascii=False)
        if fmt == "dot":
            return ast_viz.render_ast_dot(root, source)
        if fmt == "svg":
            return ast_viz.render_ast_svg(root, source)
    elif target == "compare":
        if fmt == "text":
            return compare.render_comparison_text(parsed)
        if fmt == "json":
            return json.dumps(compare.render_comparison_json(parsed), indent=2, ensure_ascii=False)
        if fmt == "svg":
            return compare.render_comparison_svg(parsed)
    raise ValueError(f"Unsupported target/format combination: {target}/{fmt}")


def read_source(arg: str, in_s: TextIO) -> str:
    if arg == "-":
        return in_s.read()
    p = Path(arg)
    if not p.is_file():
        raise FileNotFoundError(f"SIPL source file not found: {arg}")
    return p.read_text(encoding="utf-8")


def handle_command(args: argparse.Namespace, in_s: TextIO, out_s: TextIO, err_s: TextIO) -> int:
    if args.command == "conformance":
        res = run_conformance_suite(args.suite, args.cmd)
        if args.json:
            emit_json(out_s, {"ok": res.passed, "command": "conformance", **res.to_dict()})
        else:
            rows = "".join(f"  [{'PASS' if c.passed else 'FAIL'}] {c.id}: {c.message}\n" for c in res.results)
            out_s.write(f"Conformance suite ({res.suite_path}): {res.passed_count}/{res.total} passed\n{rows}")
        return EXIT_OK if res.passed else EXIT_RUNTIME_OR_FAIL

    source = read_source(args.source, in_s)
    try:
        parsed = parse_all(source)
    except SIPLSyntaxError as exc:
        return emit_diag(exc, source, args.command, args.json, out_s, err_s)

    if args.command == "parse":
        if args.json:
            extra = {"parse_tree": parsed.parse_tree.to_dict()} if args.concrete else {}
            emit_json(out_s, {"ok": True, "command": "parse", "ast": parsed.ast.to_dict(), **extra})
        elif args.concrete:
            out_s.write(parse_tree.render_parse_tree_text(parsed.parse_tree, source) + "\n")
        else:
            out_s.write(ast_viz.render_ast_text(parsed.ast, source) + "\n")
    elif args.command == "check":
        toks = len([t for t in parsed.tokens if t.kind != "EOF"])
        asts = sum(1 for _ in parsed.ast.walk())
        pts = sum(1 for _ in parsed.parse_tree.walk())
        if args.json:
            payload = {"ok": True, "command": "check", "valid": True, "token_count": toks, "ast_node_count": asts}
            emit_json(out_s, {**payload, "parse_tree_node_count": pts})
        else:
            out_s.write(f"Syntax OK: {toks} tokens, {pts} parse-tree nodes, {asts} AST nodes.\n")
    elif args.command in ("run", "trace"):
        inc_trace = args.command == "trace"
        interp = Interpreter(max_steps=args.max_steps)
        try:
            run_res = interp.run(parsed.ast, initial_state=parse_state_arg(args.state))
        except SIPLRuntimeError as exc:
            extra = {"trace": interp.last_trace.to_dict()} if inc_trace and interp.last_trace else None
            return emit_diag(exc, source, args.command, args.json, out_s, err_s, extra)
        if args.json:
            emit_json(out_s, {"ok": True, "command": args.command, **run_res.to_dict(include_trace=inc_trace)})
        else:
            summary = f"Completed in {run_res.steps_executed} steps. Final state: {run_res.final_state}"
            out_s.write((run_res.trace.format_text() if inc_trace else summary) + "\n")
    else:
        fmt = args.format or ("svg" if args.target == "compare" else ("json" if args.json else "text"))
        rendered = render_viz_payload(args.target, fmt, source, parsed)
        if args.output:
            p = Path(args.output)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(rendered, encoding="utf-8")
            if args.json:
                info = {"ok": True, "command": "viz", "target": args.target, "format": fmt, "output_path": str(p)}
                emit_json(out_s, info)
            else:
                out_s.write(f"Wrote {args.target} ({fmt}) to {p}\n")
        elif args.json and fmt != "json":
            emit_json(out_s, {"ok": True, "command": "viz", "target": args.target, "format": fmt, "content": rendered})
        else:
            out_s.write(rendered + ("" if rendered.endswith("\n") else "\n"))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    kw: dict[str, Any] = {"color": False} if sys.version_info >= (3, 14) else {}
    parser = argparse.ArgumentParser(prog="sipl", description="SIPL Language Toolkit CLI", **kw)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("parse", "check", "run", "trace", "viz"):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("source")
        sp.add_argument("--json", action="store_true")
        if name == "parse":
            sp.add_argument("--concrete", action="store_true")
        if name in ("run", "trace"):
            sp.add_argument("--state", default="")
            sp.add_argument("--max-steps", type=int, default=10_000)
        if name == "viz":
            sp.add_argument("--target", choices=("parse-tree", "ast", "compare"), default="parse-tree")
            sp.add_argument("--format", choices=("text", "json", "dot", "svg"), default=None)
            sp.add_argument("-o", "--output", default=None)
    sp_c = sub.add_parser("conformance", **kw)
    sp_c.add_argument("--suite", default=None)
    sp_c.add_argument("--cmd", default=None)
    sp_c.add_argument("--json", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    in_s = stdin or sys.stdin
    out_s = stdout or sys.stdout
    err_s = stderr or sys.stderr
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE_ERROR
    try:
        return handle_command(args, in_s, out_s, err_s)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        if getattr(args, "json", False):
            err_d = {"code": "CLI001", "severity": "error", "message": str(exc)}
            emit_json(out_s, {"ok": False, "command": args.command, "error": err_d})
        else:
            err_s.write(f"Error: {exc}\n")
        return EXIT_USAGE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
