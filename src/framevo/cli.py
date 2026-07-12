"""framevo command line: run / resume the loop, query lineage, rebuild the
gallery."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import load_config


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", default=".", help="project root containing config/")
    p.add_argument("--results", default=None, help="results directory override")


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.root, population=args.population,
                      generations=args.generations, seed=args.seed,
                      optimizer=args.optimizer, workers=args.workers,
                      results_dir=args.results)
    from .loop import EvolutionLoop
    run_id = args.run_id or time.strftime("run_%Y%m%d_%H%M%S")
    loop = EvolutionLoop(cfg, run_id, resume=args.resume)
    loop.run()
    lb = cfg.evolution.results_dir / "leaderboard.md"
    if lb.exists():
        print()
        print(lb.read_text())
    print(f"gallery: file://{cfg.evolution.results_dir / 'gallery.html'}")
    return 0


def cmd_lineage(args: argparse.Namespace) -> int:
    from .dbstore import Store
    from .lineage import format_lineage
    cfg = load_config(args.root, results_dir=args.results)
    store = Store(cfg.evolution.results_dir / "run.db")
    run_id = args.run_id or store.latest_run_id()
    if run_id is None:
        print("no runs found", file=sys.stderr)
        return 1
    print(format_lineage(store, run_id, args.genome_hash))
    return 0


def cmd_gallery(args: argparse.Namespace) -> int:
    from .dbstore import Store
    from . import gallery, lineage
    cfg = load_config(args.root, results_dir=args.results)
    results = cfg.evolution.results_dir
    store = Store(results / "run.db")
    run_id = args.run_id or store.latest_run_id()
    if run_id is None:
        print("no runs found", file=sys.stderr)
        return 1
    glossary = cfg.root / "docs" / "glossary.html"
    if glossary.exists():
        import shutil
        shutil.copyfile(glossary, results / "glossary.html")
    gallery.write_gallery(store, run_id, results, cfg.aggregation.target_whkm,
                          cfg.aggregation.record_whkm)
    gallery.write_leaderboard(store, run_id, results,
                              [s.name for s in cfg.scenarios])
    gallery.write_convergence(store, run_id, results)
    run = store.get_run(run_id)
    if run and run["optimizer"] != "cmaes":
        lineage.write_dot(store, run_id, results)
        lineage.write_svg(store, run_id, results)
        lineage.write_lineage_page(store, run_id, results)
    print(f"gallery: file://{results / 'gallery.html'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="framevo",
                                 description="evolve quadcopter frames for Wh/km")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="start or resume an evolution run")
    _add_common(p)
    p.add_argument("--generations", type=int, default=None)
    p.add_argument("--population", type=int, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--optimizer", choices=["ga", "cmaes"], default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--resume", action="store_true",
                   help="continue an interrupted run (same --run-id)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("lineage", help="print a candidate's ancestor chain")
    _add_common(p)
    p.add_argument("genome_hash")
    p.add_argument("--run-id", default=None)
    p.set_defaults(fn=cmd_lineage)

    p = sub.add_parser("gallery", help="rebuild gallery/leaderboard/plots from the db")
    _add_common(p)
    p.add_argument("--run-id", default=None)
    p.set_defaults(fn=cmd_gallery)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
