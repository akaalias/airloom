"""airloom command line: run / resume the loop, query lineage, rebuild the
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


def _snapshot_results(results, note: str) -> None:
    """Commit the current results folder into its own nested git repo
    (results/.git -- invisible to the main repo, which ignores results/)
    before a run clears or extends it."""
    import subprocess

    results = Path(results)
    if not results.exists() or not any(
            p.name != ".git" for p in results.iterdir()):
        return

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(results),
                               "-c", "user.name=airloom",
                               "-c", "user.email=airloom@local",
                               *a], capture_output=True, text=True)

    try:
        if not (results / ".git").exists():
            git("init", "-q")
        git("add", "-A")
        done = git("commit", "-q", "-m", f"snapshot {note}")
        if done.returncode == 0:
            head = git("rev-parse", "--short", "HEAD").stdout.strip()
            print(f"[airloom] results snapshot committed "
                  f"(results/.git @ {head})", flush=True)
        # nonzero = nothing changed since the last snapshot: fine
    except FileNotFoundError:
        print("[airloom] git not available -- results snapshot skipped",
              flush=True)


def _clear_results(results) -> None:
    """--fresh: empty the results folder (the snapshot repo survives)."""
    import shutil

    results = Path(results)
    if not results.exists():
        return
    for p in results.iterdir():
        if p.name == ".git":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    print("[airloom] results folder cleared for the fresh run "
          "(history in results/.git)", flush=True)


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.root, population=args.population,
                      generations=args.generations, seed=args.seed,
                      optimizer=args.optimizer, workers=args.workers,
                      results_dir=args.results,
                      designer_model=args.designer_model or args.claude_model,
                      narrator_model=args.narrator_model or args.claude_model,
                      designer_enabled=False if args.no_designer else None,
                      narrator_enabled=False if args.no_narrator else None,
                      designer_every=args.designer_every,
                      designer_candidates=args.designer_candidates,
                      patience=args.patience,
                      lambda_worst=args.lambda_worst)
    from .dbstore import Store
    from .loop import EvolutionLoop

    inspiration = None
    if args.inspiration:
        ipath = Path(args.inspiration)
        if not ipath.is_file():
            print(f"inspiration file not found: {ipath}", file=sys.stderr)
            return 1
        inspiration = (str(ipath), ipath.read_text())

    # every run start (fresh or continuing) snapshots results/ first
    _snapshot_results(cfg.evolution.results_dir,
                      f"before {'fresh' if args.fresh else 'continuing'} run "
                      + time.strftime("%Y-%m-%d %H:%M:%S"))
    if args.fresh:
        _clear_results(cfg.evolution.results_dir)

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
    loop = EvolutionLoop(cfg, run_id, resume=resume, inspiration=inspiration)

    # graceful stop: type quit/exit/q + enter, or ctrl-c
    import threading

    stop_event = threading.Event()

    def _watch_stdin() -> None:
        try:
            for line in sys.stdin:
                if line.strip().lower() in ("q", "quit", "exit", "stop"):
                    print("[airloom] stopping gracefully -- finishing the "
                          "tasks in flight...", flush=True)
                    stop_event.set()
                    return
        except Exception:
            pass

    threading.Thread(target=_watch_stdin, daemon=True).start()
    print("[airloom] type 'quit' + enter (or ctrl-c) to stop gracefully; "
          "the run stays resumable", flush=True)
    try:
        loop.run(stop_event=stop_event)
    except KeyboardInterrupt:
        stop_event.set()
        print("\n[airloom] interrupted -- run saved through the last "
              "completed generation; continue with `airloom run`", flush=True)
        return 130
    lb = cfg.evolution.results_dir / "leaderboard.md"
    if lb.exists():
        print()
        print(lb.read_text())
    print(f"landing: file://{cfg.evolution.results_dir / 'index.html'}")
    print(f"research log: file://{cfg.evolution.results_dir / 'log.html'}")
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
    run_id = args.run_id or store.latest_run_id(with_data=True)
    if run_id is None:
        print("no runs found", file=sys.stderr)
        return 1
    glossary = cfg.root / "docs" / "glossary.html"
    if glossary.exists():
        import shutil
        shutil.copyfile(glossary, results / "glossary.html")
    # the champion's flat templates + build spec, before the cards that
    # link to them render
    gallery.export_champion_parts(store, run_id, cfg.platform)
    gallery.write_gallery(store, run_id, results, cfg.aggregation.target_whkm,
                          cfg.aggregation.record_whkm, cfg.evolution, cfg=cfg)
    gallery.write_leaderboard(store, run_id, results,
                              [s.name for s in cfg.scenarios])
    gallery.write_convergence(store, run_id, results)
    run = store.get_run(run_id)
    if run and run["optimizer"] != "cmaes":
        lineage.write_dot(store, run_id, results)
        lineage.write_svg(store, run_id, results)
        lineage.write_lineage_page(store, run_id, results)
    # the landing embeds lineage.svg, so it renders AFTER the tree
    from . import landing
    landing.write_landing(store, run_id, results)
    gallery.publish_docs(results, cfg.root / "docs")
    print(f"landing: file://{results / 'index.html'}")
    print(f"research log: file://{results / 'log.html'}")
    print(f"published: {cfg.root / 'docs' / 'index.html'}")
    return 0


def cmd_cfd_calibrate(args: argparse.Namespace) -> int:
    from .cfd import run_calibration
    cfg = load_config(args.root)
    run_calibration(cfg, Path(args.root).resolve() / "cfd",
                    solve=args.solve, report=args.report, jobs=args.jobs)
    return 0


def cmd_cfd_flow(args: argparse.Namespace) -> int:
    from .cfd import run_flow
    cfg = load_config(args.root, results_dir=args.results)
    run_flow(cfg, Path(args.root).resolve() / "cfd",
             h=args.genome_hash, solve=args.solve, extract=args.extract)
    return 0


def cmd_verify_champions(args: argparse.Namespace) -> int:
    from .champion import verify_champions
    cfg = load_config(args.root, results_dir=args.results)
    summary = verify_champions(cfg, run_id=args.run_id, top=args.top)
    return 0 if summary["n_overstressed"] == 0 else 2


def cmd_robustness(args: argparse.Namespace) -> int:
    from .robustness import run_robustness
    cfg = load_config(args.root, results_dir=args.results,
                      workers=args.workers)
    summary = run_robustness(cfg, run_id=args.run_id, top=args.top)
    return 0 if summary["verdict"] != "FRAGILE" else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="airloom",
                                 description="evolve quadcopter frames for Wh/km")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="start or resume an evolution run")
    _add_common(p)
    p.add_argument("--generations", type=int, default=None)
    p.add_argument("--population", type=int, default=None)
    p.add_argument("--seed", type=int, default=None,
                   help="master RNG seed for a new run (default: random unless"
                        " set in evolution.yaml; resume always reuses the"
                        " run's stored seed)")
    p.add_argument("--optimizer", choices=["ga", "cmaes"], default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--inspiration", default=None, metavar="PATH",
                   help="markdown/text file of ideas for the Claude designer"
                        " to draw on (e.g. 'think of the shapes of frogs');"
                        " stored with the run and shown in the gallery."
                        " On resume it replaces the run's stored inspiration")
    p.add_argument("--resume", action="store_true",
                   help="(default behavior) continue the latest/named run")
    p.add_argument("--fresh", action="store_true",
                   help="force a brand-new run instead of resuming the latest")
    p.add_argument("--claude-model", default=None, metavar="MODEL",
                   help="model for BOTH the designer and narrator claude"
                        " calls (e.g. opus, haiku, or a full model id);"
                        " empty = the claude CLI's default")
    p.add_argument("--designer-model", default=None, metavar="MODEL",
                   help="model for designer rounds (overrides --claude-model)")
    p.add_argument("--narrator-model", default=None, metavar="MODEL",
                   help="model for narrator notes (overrides --claude-model)")
    p.add_argument("--designer-every", type=int, default=None, metavar="K",
                   help="designer round every K generations")
    p.add_argument("--designer-candidates", type=int, default=None,
                   metavar="N", help="candidates per designer round")
    p.add_argument("--no-designer", action="store_true",
                   help="disable Claude designer rounds for this run")
    p.add_argument("--no-narrator", action="store_true",
                   help="disable Claude lab-notebook notes for this run")
    p.add_argument("--patience", type=int, default=None, metavar="GENS",
                   help="plateau generations before a pivot round")
    p.add_argument("--lambda-worst", type=float, default=None,
                   help="worst-scenario weight in the fitness aggregate")
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

    p = sub.add_parser("robustness",
                       help="re-fly top candidates under perturbed model"
                            " knobs; is the ranking a frame property or a"
                            " model artifact? (writes results/robustness.md)")
    _add_common(p)
    p.add_argument("--run-id", default=None)
    p.add_argument("--top", type=int, default=20,
                   help="how many of the best candidates to sweep")
    p.add_argument("--workers", type=int, default=None)
    p.set_defaults(fn=cmd_robustness)

    p = sub.add_parser("verify-champions",
                       help="refined structural check of the top frames:"
                            " bolt-hole/cutout stress concentration +"
                            " as-built strength knockdown + a print-and-test"
                            " protocol (writes results/champion_check.md)")
    _add_common(p)
    p.add_argument("--run-id", default=None)
    p.add_argument("--top", type=int, default=5,
                   help="how many of the best frames to verify")
    p.set_defaults(fn=cmd_verify_champions)

    p = sub.add_parser("cfd-calibrate",
                       help="Phase B milestone 1: generate (and optionally"
                            " solve) the OpenFOAM drag-calibration cases"
                            " under cfd/; --report compares measured CdA"
                            " with the component buildup")
    _add_common(p)
    p.add_argument("--solve", action="store_true",
                   help="run the cases through Docker"
                        " (opencfd/openfoam-default); CPU-heavy")
    p.add_argument("--report", action="store_true",
                   help="parse solved cases and write cfd/calibration.md")
    p.add_argument("--jobs", type=int, default=1,
                   help="concurrent case solves (each is a serial container)")
    p.set_defaults(fn=cmd_cfd_calibrate)

    p = sub.add_parser("cfd-flow",
                       help="real RANS streamlines for a candidate's flight"
                            " views: mesh its assembly once, solve every"
                            " weather scenario's mean relative wind, ship"
                            " <hash>.<scen>.flow.js payloads to the gallery")
    _add_common(p)
    p.add_argument("genome_hash", nargs="?", default=None,
                   help="candidate hash (default: the run champion)")
    p.add_argument("--solve", action="store_true",
                   help="run the cases through Docker; CPU-heavy (~1-2h)")
    p.add_argument("--extract", action="store_true",
                   help="parse already-solved cases into gallery payloads")
    p.set_defaults(fn=cmd_cfd_flow)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
