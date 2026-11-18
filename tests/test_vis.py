import io
import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from sipl.cli import EXIT_OK, main
from sipl.parser import parse_all
from sipl.visualization.ast_viz import render_ast_dot, render_ast_json, render_ast_svg, render_ast_text
from sipl.visualization.compare import (
    build_comparison_report,
    render_comparison_json,
    render_comparison_svg,
    render_comparison_text,
)
from sipl.visualization.parse_tree import (
    render_parse_tree_dot,
    render_parse_tree_json,
    render_parse_tree_svg,
    render_parse_tree_text,
    verify_parse_tree_yield,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


class TestVisualization(unittest.TestCase):
    def test_parse_tree_outputs_and_yield_check(self) -> None:
        source = (EXAMPLES_DIR / "power.sipl").read_text(encoding="utf-8")
        res = parse_all(source)

        yield_info = verify_parse_tree_yield(res.parse_tree, res.tokens)
        self.assertTrue(yield_info.matches)
        self.assertEqual(yield_info.leaf_count, 24)
        self.assertTrue(yield_info.numbered_yield.startswith("1 begin 2 R 3 := 4 1 5 ;"))

        text = render_parse_tree_text(res.parse_tree, source)
        self.assertIn("<програма>", text)
        self.assertIn("#1 begin", text)

        js = render_parse_tree_json(res.parse_tree, source, res.tokens)
        self.assertEqual(js["kind"], "ConcreteParseTree")
        self.assertTrue(js["yield_verification"]["matches"])

        dot = render_parse_tree_dot(res.parse_tree, source)
        self.assertIn("digraph SIPLParseTree", dot)

        svg = render_parse_tree_svg(res.parse_tree, source)
        self.assertTrue(ET.fromstring(svg).tag.endswith("svg"))

        dot_bin = shutil.which("dot")
        if dot_bin:
            proc = subprocess.run([dot_bin, "-Tsvg"], input=dot, text=True, capture_output=True, check=False)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("<svg", proc.stdout)

    def test_ast_and_comparison_outputs(self) -> None:
        source = (EXAMPLES_DIR / "division.sipl").read_text(encoding="utf-8")
        res = parse_all(source)

        self.assertIn("Program", render_ast_text(res.ast, source))
        self.assertEqual(render_ast_json(res.ast, source)["kind"], "AbstractSyntaxTree")
        self.assertIn("digraph SIPLAST", render_ast_dot(res.ast, source))
        self.assertTrue(ET.fromstring(render_ast_svg(res.ast, source)).tag.endswith("svg"))

        report = build_comparison_report(res)
        self.assertGreater(report["metrics"]["parse_tree_nodes"], report["metrics"]["ast_nodes"])
        self.assertIn("Parse Tree", render_comparison_text(res))
        self.assertEqual(render_comparison_json(res)["kind"], "ParseTreeVsASTComparison")

        svg_cmp = render_comparison_svg(res)
        self.assertTrue(ET.fromstring(svg_cmp).tag.endswith("svg"))
        self.assertIn("parse-tree-svg", svg_cmp)
        self.assertIn("ast-tree-svg", svg_cmp)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "cmp.svg"
            stdout, stderr = io.StringIO(), io.StringIO()
            args = [
                "viz",
                str(EXAMPLES_DIR / "power.sipl"),
                "--target",
                "compare",
                "--format",
                "svg",
                "-o",
                str(out_file),
                "--json",
            ]
            self.assertEqual(main(args, stdout=stdout, stderr=stderr), EXIT_OK)
            self.assertEqual(json.loads(stdout.getvalue())["format"], "svg")
            self.assertTrue(out_file.is_file())
