"""Lineage: ancestor-chain queries, Graphviz DOT export, and a pure-Python
SVG family tree (no graphviz binary required).

Layout: one row per generation showing that generation's population sorted by
fitness; filled nodes are births (colored dark = better fitness), hollow nodes
are invalid candidates, small pass-through nodes are elite carry-overs
connected by vertical edges. Parent edges are colored by operator.
"""
from __future__ import annotations

import html
import math
from pathlib import Path

from .dbstore import Store

OPERATOR_COLORS = {
    "crossover": "#4a6fa5",
    "mutation": "#b3574a",
    "immigrant": "#7a915a",
    "elite": "#999188",
    "seed": "#bbb4ac",
    "cmaes": "#888888",
}


def format_lineage(store: Store, run_id: str, h: str) -> str:
    """Human-readable ancestor chain of a candidate, fitness at each step."""
    rows = store.ancestor_rows(run_id, h)
    if not rows:
        return f"no candidate {h} in run {run_id}"
    lines = [f"ancestry of {h} (run {run_id}), nearest first:"]
    for r in rows:
        fit = store.fitness_of(r)
        fit_s = f"{fit:8.3f} Wh/km-agg" if math.isfinite(fit) else "  invalid"
        parents = " + ".join(x for x in (r["parent_a"], r["parent_b"]) if x) or "-"
        mut = f"  mut={r['mutation_mag']:.3f}" if r["mutation_mag"] else ""
        note = f"  [{r['failure_reason']}]" if r["failure_reason"] else ""
        lines.append(
            f"  depth {r['depth']}: {r['hash']}  gen {r['generation_born']:3d}"
            f"  {r['operator']:<9s} {fit_s}  parents: {parents}{mut}{note}")
    return "\n".join(lines)


def _fitness_color(fit: float, lo: float, hi: float) -> str:
    """Dark = better. Maps fitness onto a light->dark ramp."""
    if not math.isfinite(fit):
        return "#ffffff"
    x = 0.0 if hi <= lo else (fit - lo) / (hi - lo)
    # interpolate #14324f (best) -> #cfdceb (worst)
    c0, c1 = (0x14, 0x32, 0x4f), (0xcf, 0xdc, 0xeb)
    rgb = tuple(round(a + (b - a) * x) for a, b in zip(c0, c1))
    return "#%02x%02x%02x" % rgb


def write_dot(store: Store, run_id: str, results_dir: Path) -> Path:
    cands = store.candidates_for_run(run_id)
    fits = [store.fitness_of(r) for r in cands]
    finite = [f for f in fits if math.isfinite(f)]
    lo, hi = (min(finite), max(finite)) if finite else (0.0, 1.0)

    lines = ["digraph lineage {",
             '  rankdir=TB; node [shape=circle, style=filled, fontsize=8];']
    by_gen: dict[int, list[str]] = {}
    for r, fit in zip(cands, fits):
        color = _fitness_color(fit, lo, hi)
        style = "filled" if math.isfinite(fit) else "solid"  # hollow = invalid
        label = f"{r['hash'][:6]}\\n{fit:.2f}" if math.isfinite(fit) \
            else f"{r['hash'][:6]}\\ninv"
        font = "white" if math.isfinite(fit) and (fit - lo) < 0.5 * (hi - lo + 1e-9) \
            else "black"
        lines.append(f'  "{r["hash"]}" [label="{label}", fillcolor="{color}",'
                     f' style="{style}", fontcolor={font}];')
        by_gen.setdefault(r["generation_born"], []).append(r["hash"])
        for parent, tag in ((r["parent_a"], "a"), (r["parent_b"], "b")):
            if parent:
                col = OPERATOR_COLORS.get(r["operator"], "#888888")
                lines.append(f'  "{parent}" -> "{r["hash"]}"'
                             f' [label="{r["operator"]}", color="{col}", fontsize=7];')
    for gen, hs in sorted(by_gen.items()):
        ranked = "; ".join(f'"{h}"' for h in hs)
        lines.append(f"  {{ rank=same; {ranked} }}")
    # elite pass-through: same hash present in consecutive populations
    gens = store.generations_with_population(run_id)
    for g0, g1 in zip(gens, gens[1:]):
        prev = {r["hash"] for r in store.population(run_id, g0)}
        for r in store.population(run_id, g1):
            if r["hash"] in prev:
                lines.append(f'  "{r["hash"]}" -> "{r["hash"]}"'
                             f' [style=dotted, color="#999188", label="elite"];')
    lines.append("}")
    out = results_dir / "lineage.dot"
    out.write_text("\n".join(lines))
    return out


def write_svg(store: Store, run_id: str, results_dir: Path) -> Path:
    """Self-contained SVG family tree, laid out generation-by-generation."""
    gens = store.generations_with_population(run_id)
    cands = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    fits = {h: store.fitness_of(r) for h, r in cands.items()}
    finite = [f for f in fits.values() if math.isfinite(f)]
    lo, hi = (min(finite), max(finite)) if finite else (0.0, 1.0)

    xstep, ystep, r_node, margin = 46, 84, 9, 60
    pop_rows = {g: sorted(store.population(run_id, g),
                          key=lambda r: (r["fitness"] is None,
                                         r["fitness"] if r["fitness"] is not None else 0))
                for g in gens}
    width = margin * 2 + max((len(v) for v in pop_rows.values()), default=1) * xstep
    height = margin * 2 + (len(gens)) * ystep

    pos: dict[tuple[int, str], tuple[float, float]] = {}
    birth_pos: dict[str, tuple[float, float]] = {}
    for gi, g in enumerate(gens):
        for si, row in enumerate(pop_rows[g]):
            x = margin + si * xstep + xstep / 2
            y = margin + gi * ystep
            pos[(g, row["hash"])] = (x, y)
            cand = cands.get(row["hash"])
            if cand is not None and cand["generation_born"] == g \
                    and row["hash"] not in birth_pos:
                birth_pos[row["hash"]] = (x, y)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}"'
           f' height="{height}" font-family="Helvetica,Arial,sans-serif">',
           '<rect width="100%" height="100%" fill="#faf9f7"/>']

    # edges first
    for g in gens:
        for row in pop_rows[g]:
            h = row["hash"]
            cand = cands.get(h)
            if cand is None:
                continue
            x1, y1 = pos[(g, h)]
            if cand["generation_born"] == g:
                for parent in (cand["parent_a"], cand["parent_b"]):
                    if parent and (g - 1, parent) in pos:
                        px, py = pos[(g - 1, parent)]
                    elif parent and parent in birth_pos:
                        px, py = birth_pos[parent]
                    else:
                        continue
                    col = OPERATOR_COLORS.get(cand["operator"], "#888")
                    svg.append(f'<path d="M{px:.0f},{py + r_node:.0f}'
                               f' C{px:.0f},{(py + y1) / 2:.0f} {x1:.0f},'
                               f'{(py + y1) / 2:.0f} {x1:.0f},{y1 - r_node:.0f}"'
                               f' stroke="{col}" fill="none" stroke-width="1.1"'
                               f' opacity="0.75"/>')
            elif (g - 1, h) in pos:  # elite pass-through
                px, py = pos[(g - 1, h)]
                svg.append(f'<line x1="{px:.0f}" y1="{py + r_node:.0f}"'
                           f' x2="{x1:.0f}" y2="{y1 - r_node:.0f}"'
                           f' stroke="#999188" stroke-dasharray="3,3"'
                           f' stroke-width="1.2"/>')

    # nodes
    for g in gens:
        for row in pop_rows[g]:
            h = row["hash"]
            x, y = pos[(g, h)]
            cand = cands.get(h)
            fit = fits.get(h, math.inf)
            is_birth = cand is not None and cand["generation_born"] == g
            rr = r_node if is_birth else r_node * 0.55
            if math.isfinite(fit):
                fill = _fitness_color(fit, lo, hi)
                stroke = "#5a6572"
            else:
                fill = "none"  # hollow = invalid
                stroke = "#b0a9a1"
            title = html.escape(
                f"{h} gen{cand['generation_born'] if cand else g} "
                f"{cand['operator'] if cand else ''} "
                + (f"{fit:.3f}" if math.isfinite(fit)
                   else (cand["failure_reason"] or "invalid") if cand else ""))
            svg.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rr:.1f}"'
                       f' fill="{fill}" stroke="{stroke}" stroke-width="1.2">'
                       f'<title>{title}</title></circle>')
        # generation label
    for gi, g in enumerate(gens):
        svg.append(f'<text x="{margin - 44}" y="{margin + gi * ystep + 4}"'
                   f' font-size="11" fill="#8a8580">g{g}</text>')

    # legend
    lx, ly = margin, height - 26
    for name, col in OPERATOR_COLORS.items():
        svg.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 16}" y2="{ly}"'
                   f' stroke="{col}" stroke-width="2"/>')
        svg.append(f'<text x="{lx + 20}" y="{ly + 4}" font-size="10"'
                   f' fill="#5a5650">{name}</text>')
        lx += 30 + 7 * len(name)
    svg.append("</svg>")
    out = results_dir / "lineage.svg"
    out.write_text("\n".join(svg))
    return out
