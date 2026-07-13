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
    from .dbstore import Store
    from .loop import EvolutionLoop

    # default behavior: pick up where the last run left off. A new run is
    # started when --fresh is passed, no prior run exists, or the latest
    # run's genomes predate the current genome spec.
    store = Store(cfg.evolution.results_dir / "run.db")
    run_id, resume = args.run_id, args.resume
    if run_id is None and not args.fresh:
        latest = store.latest_run_id()
        if latest is not None:
            done = store.get_run(latest)["generations_done"]
            if not store.run_genome_compatible(latest):
                print(f"latest run '{latest}' uses an older genome spec --"
                      " starting a fresh run")
            elif done >= cfg.evolution.generations:
                print(f"latest run '{latest}' already has {done} generations"
                      f" (>= --generations {cfg.evolution.generations});"
                      " raise --generations to continue it or use --fresh")
                return 0
            else:
                run_id, resume = latest, True
    elif run_id is not None and store.get_run(run_id) is not None:
        resume = True  # explicit --run-id of an existing run always resumes
    store.close()
    run_id = run_id or time.strftime("run_%Y%m%d_%H%M%S")
    loop = EvolutionLoop(cfg, run_id, resume=resume)

    # graceful stop: type quit/exit/q + enter, or ctrl-c
    import threading

    stop_event = threading.Event()

    def _watch_stdin() -> None:
        try:
            for line in sys.stdin:
                if line.strip().lower() in ("q", "quit", "exit", "stop"):
                    print("[framevo] stopping gracefully -- finishing the "
                          "tasks in flight...", flush=True)
                    stop_event.set()
                    return
        except Exception:
            pass

    threading.Thread(target=_watch_stdin, daemon=True).start()
    print("[framevo] type 'quit' + enter (or ctrl-c) to stop gracefully; "
          "the run stays resumable", flush=True)
    try:
        loop.run(stop_event=stop_event)
    except KeyboardInterrupt:
        stop_event.set()
        print("\n[framevo] interrupted -- run saved through the last "
              "completed generation; continue with `framevo run`", flush=True)
        return 130
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
                   help="(default behavior) continue the latest/named run")
    p.add_argument("--fresh", action="store_true",
                   help="force a brand-new run instead of resuming the latest")
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
