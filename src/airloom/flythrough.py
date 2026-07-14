"""Flight-telemetry payloads for the gallery's flight tab.

Curation: the champion and every best-so-far setter of a run get their six
scenario flights re-simulated with the telemetry tap on (fixed gust seeds
make this an exact replay of the scored flight) and written as JSONP files
next to the mesh payloads:

    frames/gen_XXXX/<hash>.<scenario>.flight.js
        -> airloomFlight("<hash>", "<scenario>", {hz, x[], y[], z[], ...})

Files are cached by existence, so a gallery refresh only simulates flights
for setters that appeared since the last refresh (~seconds per new setter,
off nobody's critical path). Fail-soft: any error just means no flight tab
for that candidate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

TRACE_HZ = 10.0


def _flight_path(png_path: str, scenario: str) -> Path:
    p = Path(png_path)  # frames/gen_XXXX/<hash>.png
    return p.with_name(f"{p.stem}.{scenario}.flight.js")


def write_flights_for(cfg, genome_dict: dict[str, float], h: str,
                      png_path: str) -> dict[str, str]:
    """Simulate all scenarios for one candidate with telemetry, write one
    .flight.js per scenario (skipping ones already on disk). Returns
    {scenario: absolute path} for every file present afterwards."""
    from .aero import build_drag_table
    from .evaluate import _context
    from .frame_gen import build_frame
    from .genome import Genome
    from .simulator import simulate_scenario

    todo = [s for s in cfg.scenarios
            if not _flight_path(png_path, s.name).exists()]
    out: dict[str, str] = {}
    if todo:
        cfg2, rotor = _context(str(cfg.root))
        frame = build_frame(Genome.from_dict(genome_dict), cfg.platform)
        if frame.valid:
            drag = build_drag_table(frame, cfg.platform)
            for s in todo:
                res = simulate_scenario(frame.total_mass, drag, rotor, s,
                                        cfg.mission, cfg.rain,
                                        battery=cfg.platform.battery,
                                        trace_hz=TRACE_HZ)
                if res.trace is None:
                    continue
                payload = dict(res.trace)
                payload["valid"] = bool(res.valid)
                payload["reason"] = res.failure_reason
                payload["rain"] = s.rain_mm_h
                payload["whkm"] = (round(res.wh_per_km, 3)
                                   if math.isfinite(res.wh_per_km) else None)
                fp = _flight_path(png_path, s.name)
                fp.write_text(f'airloomFlight("{h}","{s.name}",'
                              f"{json.dumps(payload, separators=(',', ':'))});")
    for s in cfg.scenarios:
        fp = _flight_path(png_path, s.name)
        if fp.exists():
            out[s.name] = str(fp)
    return out


def ensure_flights(cfg, store, run_id: str,
                   results_dir: Path) -> dict[str, dict[str, str]]:
    """Flights for the run's champion + all best-so-far setters (the
    curation rule). Returns {hash: {scenario: gallery-relative path}}."""
    from .gallery import _rel

    cands = list(store.candidates_in_eval_order(run_id))
    setters: list[Any] = []
    best = math.inf
    for c in cands:
        f = c["fitness"]
        if f is not None and f < best:
            best = f
            setters.append(c)

    flight_src: dict[str, dict[str, str]] = {}
    for c in setters:
        if not c["png_path"]:
            continue
        try:
            files = write_flights_for(cfg, json.loads(c["genome_json"]),
                                      c["hash"], c["png_path"])
        except Exception:  # fail-soft: no flight tab, gallery still builds
            continue
        if files:
            flight_src[c["hash"]] = {scen: _rel(results_dir, p)
                                     for scen, p in files.items()}
    return flight_src
