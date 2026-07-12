"""SQLite persistence: runs, candidates (self-referencing lineage),
per-scenario results, per-generation populations. Resumable after a crash.

`candidates` is self-referencing via parent_a/parent_b, so ancestry queries
are a `WITH RECURSIVE` walk (see `ancestor_rows`). Invalid candidates keep
fitness NULL (rendered as infinity in Python).
"""
from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# bump when the schema changes: stale run.db files are reset automatically
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_utc REAL NOT NULL,
    seed INTEGER NOT NULL,
    optimizer TEXT NOT NULL,
    population INTEGER NOT NULL,
    generations_target INTEGER NOT NULL,
    generations_done INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    git_hash TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);
CREATE TABLE IF NOT EXISTS candidates (
    run_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    generation_born INTEGER NOT NULL,
    parent_a TEXT,
    parent_b TEXT,
    operator TEXT NOT NULL,
    mutation_mag REAL,
    genome_json TEXT NOT NULL,
    frame_mass REAL,
    total_mass REAL,
    material TEXT,
    valid INTEGER NOT NULL,
    failure_reason TEXT,
    fitness REAL,
    mean_whkm REAL,
    worst_whkm REAL,
    f1_hz REAL,
    stl_path TEXT,
    png_path TEXT,
    PRIMARY KEY (run_id, hash)
);
CREATE TABLE IF NOT EXISTS scenario_results (
    run_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    scenario TEXT NOT NULL,
    valid INTEGER NOT NULL,
    failure_reason TEXT,
    wh_per_km REAL,
    energy_wh REAL,
    avg_power_w REAL,
    flight_time_s REAL,
    peak_rotor_thrust_n REAL,
    max_tilt_deg REAL,
    PRIMARY KEY (run_id, hash, scenario)
);
CREATE TABLE IF NOT EXISTS populations (
    run_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    hash TEXT NOT NULL,
    fitness REAL,
    PRIMARY KEY (run_id, generation, slot)
);
CREATE TABLE IF NOT EXISTS cma_state (
    run_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    mean_json TEXT NOT NULL,
    sigma REAL NOT NULL,
    state_json TEXT NOT NULL,
    PRIMARY KEY (run_id, generation)
);
"""


def _fit_to_db(f: float) -> float | None:
    return None if f is None or math.isinf(f) or math.isnan(f) else float(f)


def _fit_from_db(f: float | None) -> float:
    return math.inf if f is None else float(f)


def git_hash(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


@dataclass
class CandidateRow:
    hash: str
    generation_born: int
    parent_a: str | None
    parent_b: str | None
    operator: str
    mutation_mag: float | None
    genome: dict[str, float]
    frame_mass: float | None
    total_mass: float | None
    material: str | None
    valid: bool
    failure_reason: str | None
    fitness: float
    mean_whkm: float
    worst_whkm: float
    f1_hz: float | None
    stl_path: str | None
    png_path: str | None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():  # archive databases written by an older schema --
            # computed generations are never deleted, just set aside
            probe = sqlite3.connect(path)
            version = probe.execute("PRAGMA user_version").fetchone()[0]
            probe.close()
            if version != SCHEMA_VERSION:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                backup = path.with_name(f"{path.stem}_schema-v{version}_{stamp}.db.bak")
                path.rename(backup)
                print(f"[framevo] {path} has schema v{version}, expected "
                      f"v{SCHEMA_VERSION} -- archived it as {backup.name}",
                      flush=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    # -- runs ---------------------------------------------------------------
    def create_run(self, run_id: str, seed: int, optimizer: str, population: int,
                   generations: int, config_json: str, root: Path) -> None:
        self.conn.execute(
            "INSERT INTO runs (run_id, created_utc, seed, optimizer, population,"
            " generations_target, config_json, git_hash) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, time.time(), seed, optimizer, population, generations,
             config_json, git_hash(root)))
        self.conn.commit()

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM runs WHERE run_id=?",
                                 (run_id,)).fetchone()

    def latest_run_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT run_id FROM runs ORDER BY created_utc DESC LIMIT 1").fetchone()
        return row["run_id"] if row else None

    def mark_generation_done(self, run_id: str, generation: int) -> None:
        self.conn.execute(
            "UPDATE runs SET generations_done=? WHERE run_id=?",
            (generation + 1, run_id))
        self.conn.commit()

    def finish_run(self, run_id: str, status: str = "finished") -> None:
        self.conn.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
        self.conn.commit()

    # -- candidates ----------------------------------------------------------
    def insert_candidate(self, run_id: str, row: CandidateRow) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO candidates (run_id, hash, generation_born,"
            " parent_a, parent_b, operator, mutation_mag, genome_json, frame_mass,"
            " total_mass, material, valid, failure_reason, fitness, mean_whkm,"
            " worst_whkm, f1_hz, stl_path, png_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, row.hash, row.generation_born, row.parent_a, row.parent_b,
             row.operator, row.mutation_mag, json.dumps(row.genome),
             row.frame_mass, row.total_mass, row.material, int(row.valid),
             row.failure_reason, _fit_to_db(row.fitness), _fit_to_db(row.mean_whkm),
             _fit_to_db(row.worst_whkm), row.f1_hz, row.stl_path, row.png_path))
        self.conn.commit()

    def update_candidate_result(self, run_id: str, h: str, valid: bool,
                                failure_reason: str | None, fitness: float,
                                mean_whkm: float, worst_whkm: float,
                                f1_hz: float | None,
                                stl_path: str | None = None) -> None:
        sets = ("valid=?, failure_reason=?, fitness=?, mean_whkm=?, worst_whkm=?,"
                " f1_hz=?")
        args: list[Any] = [int(valid), failure_reason, _fit_to_db(fitness),
                           _fit_to_db(mean_whkm), _fit_to_db(worst_whkm), f1_hz]
        if stl_path is not None:
            sets += ", stl_path=?"
            args.append(stl_path)
        args += [run_id, h]
        self.conn.execute(f"UPDATE candidates SET {sets} WHERE run_id=? AND hash=?",
                          args)
        self.conn.commit()

    def get_candidate(self, run_id: str, h: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM candidates WHERE run_id=? AND hash=?",
            (run_id, h)).fetchone()

    def candidates_for_run(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM candidates WHERE run_id=? ORDER BY generation_born, hash",
            (run_id,)).fetchall()

    def candidates_in_eval_order(self, run_id: str) -> list[sqlite3.Row]:
        """Insertion (= evaluation) order: the x-axis of the progress chart."""
        return self.conn.execute(
            "SELECT * FROM candidates WHERE run_id=? ORDER BY rowid",
            (run_id,)).fetchall()

    def fitness_of(self, row: sqlite3.Row) -> float:
        return _fit_from_db(row["fitness"])

    # -- scenario results ------------------------------------------------------
    def insert_scenario_result(self, run_id: str, h: str, r: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO scenario_results (run_id, hash, scenario,"
            " valid, failure_reason, wh_per_km, energy_wh, avg_power_w,"
            " flight_time_s, peak_rotor_thrust_n, max_tilt_deg)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, h, r["scenario"], int(r["valid"]), r["failure_reason"],
             _fit_to_db(r["wh_per_km"]), _fit_to_db(r["energy_wh"]),
             _fit_to_db(r["avg_power_w"]), _fit_to_db(r["flight_time_s"]),
             r["peak_rotor_thrust_n"], r["max_tilt_deg"]))
        self.conn.commit()

    def scenario_results_for(self, run_id: str, h: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM scenario_results WHERE run_id=? AND hash=?"
            " ORDER BY scenario", (run_id, h)).fetchall()

    # -- populations -----------------------------------------------------------
    def set_population(self, run_id: str, generation: int,
                       entries: list[tuple[str, float]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO populations (run_id, generation, slot, hash,"
            " fitness) VALUES (?,?,?,?,?)",
            [(run_id, generation, i, h, _fit_to_db(f))
             for i, (h, f) in enumerate(entries)])
        self.conn.commit()

    def population(self, run_id: str, generation: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM populations WHERE run_id=? AND generation=?"
            " ORDER BY slot", (run_id, generation)).fetchall()

    def generations_with_population(self, run_id: str) -> list[int]:
        return [r["generation"] for r in self.conn.execute(
            "SELECT DISTINCT generation FROM populations WHERE run_id=?"
            " ORDER BY generation", (run_id,))]

    # -- lineage ----------------------------------------------------------------
    def ancestor_rows(self, run_id: str, h: str) -> list[sqlite3.Row]:
        """All ancestors of `h` (including itself) with their depth, via the
        self-referencing parent columns and a recursive walk."""
        return self.conn.execute(
            """
            WITH RECURSIVE anc(hash, depth) AS (
                SELECT ?, 0
                UNION
                SELECT c.parent_a, anc.depth + 1
                  FROM candidates c JOIN anc ON c.hash = anc.hash
                 WHERE c.run_id = ? AND c.parent_a IS NOT NULL
                UNION
                SELECT c.parent_b, anc.depth + 1
                  FROM candidates c JOIN anc ON c.hash = anc.hash
                 WHERE c.run_id = ? AND c.parent_b IS NOT NULL
            )
            SELECT c.*, MIN(anc.depth) AS depth
              FROM anc JOIN candidates c ON c.hash = anc.hash AND c.run_id = ?
             GROUP BY c.hash
             ORDER BY depth, c.generation_born
            """, (h, run_id, run_id, run_id)).fetchall()

    # -- cma provenance -----------------------------------------------------------
    def save_cma_state(self, run_id: str, generation: int, mean: list[float],
                       sigma: float, state_json: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cma_state (run_id, generation, mean_json,"
            " sigma, state_json) VALUES (?,?,?,?,?)",
            (run_id, generation, json.dumps(mean), sigma, state_json))
        self.conn.commit()

    def load_cma_state(self, run_id: str, generation: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM cma_state WHERE run_id=? AND generation=?",
            (run_id, generation)).fetchone()

    def close(self) -> None:
        self.conn.close()
