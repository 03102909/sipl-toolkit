import re
from typing import Any

from sipl.lexer import ParseNode
from sipl.parser import ParseResult
from sipl.visualization.ast_viz import render_ast_svg
from sipl.visualization.parse_tree import render_parse_tree_svg, verify_parse_tree_yield


def build_comparison_report(parse_result: ParseResult) -> dict[str, Any]:
    pt_nodes = list(parse_result.parse_tree.walk())
    ast_nodes = list(parse_result.ast.walk())
    leaves = parse_result.parse_tree.leaves()
    pt_by_ast: dict[str, list[ParseNode]] = {}
    for pt in pt_nodes:
        if pt.ast_node_id:
            pt_by_ast.setdefault(pt.ast_node_id, []).append(pt)

    mappings = [
        {
            "ast_node_id": n.node_id,
            "ast_label": n.display_label(),
            "rule_id": n.rule_id,
            "span": n.span.format_short(),
            "parse_node_ids": [p.id for p in pt_by_ast.get(n.node_id, [])],
        }
        for n in ast_nodes
    ]

    yr = verify_parse_tree_yield(parse_result.parse_tree, parse_result.tokens)
    pt_count, ast_count = len(pt_nodes), len(ast_nodes)
    red_pct = round(((pt_count - ast_count) / pt_count) * 100.0, 1) if pt_count else 0.0
    return {
        "metrics": {
            "parse_tree_nodes": pt_count,
            "terminal_leaves": len(leaves),
            "ast_nodes": ast_count,
            "eliminated_concrete_nodes": pt_count - ast_count,
            "reduction_percent": red_pct,
        },
        "yield_verification": yr.to_dict(),
        "node_mappings": mappings,
    }


def render_comparison_json(parse_result: ParseResult) -> dict[str, Any]:
    rep = build_comparison_report(parse_result)
    return {
        "kind": "ParseTreeVsASTComparison",
        "metrics": rep["metrics"],
        "yield_verification": rep["yield_verification"],
        "node_mappings": rep["node_mappings"],
    }


def render_comparison_text(parse_result: ParseResult) -> str:
    rep = build_comparison_report(parse_result)
    m = rep["metrics"]
    lines = [
        f"Parse Tree: {m['parse_tree_nodes']} nodes ({m['terminal_leaves']} leaves) -> AST: {m['ast_nodes']} nodes (-{m['reduction_percent']}%)",
        f"Yield: {'MATCH' if rep['yield_verification']['matches'] else 'MISMATCH'} ({m['terminal_leaves']} tokens)",
    ]
    for item in rep["node_mappings"]:
        lines.append(f"  {item['ast_node_id']:<6} {item['ast_label']:<15} <- {', '.join(item['parse_node_ids'])}")
    return "\n".join(lines)


def _svg_size(svg: str) -> tuple[float, float]:
    m = re.search(r'width="([0-9.]+)"\s+height="([0-9.]+)"', svg)
    return (float(m.group(1)), float(m.group(2))) if m else (400.0, 300.0)


def render_comparison_svg(parse_result: ParseResult) -> str:
    m = build_comparison_report(parse_result)["metrics"]
    pt_svg = render_parse_tree_svg(parse_result.parse_tree, parse_result.source)
    ast_svg = render_ast_svg(parse_result.ast, parse_result.source)
    pw, ph = _svg_size(pt_svg)
    aw, ah = _svg_size(ast_svg)
    tw, th = pw + aw + 48.0, max(ph, ah) + 56.0
    title = (
        f"Parse Tree ({m['parse_tree_nodes']} nodes) vs AST ({m['ast_nodes']} nodes, "
        f"-{m['eliminated_concrete_nodes']} / -{m['reduction_percent']}%)"
    )
    pt_inner = pt_svg.replace("<svg ", '<svg x="16" y="40" ', 1)
    ast_inner = ast_svg.replace("<svg ", f'<svg x="{pw + 32:.1f}" y="40" ', 1)
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {tw:.1f} {th:.1f}" width="{tw:.1f}" height="{th:.1f}">',
            f'<text x="{tw / 2.0:.1f}" y="24" text-anchor="middle">{title}</text>',
            pt_inner,
            ast_inner,
            "</svg>",
        ]
    )
