"""Typed configuration loaded from config/*.yaml."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

R_AIR = 287.05  # J/(kg K)
P0 = 101325.0   # Pa
T0 = 288.15     # K
LAPSE = 0.0065  # K/m
G = 9.80665     # m/s^2

# MIL-F-8785C low-altitude turbulence intensity: sigma_w = 0.1 * W20,
# with W20 (wind speed at 20 ft) of 15 / 30 / 45 kt.
TURBULENCE_W20_MS = {"none": 0.0, "light": 7.72, "moderate": 15.43, "severe": 23.15}


def isa_density(altitude_m: float) -> float:
    t = T0 - LAPSE * altitude_m
    p = P0 * (t / T0) ** (G / (R_AIR * LAPSE))
    return p / (R_AIR * t)


@dataclass(frozen=True)
class Battery:
    capacity_mah: float
    voltage_nominal: float
    mass_kg: float
    size_m: tuple[float, float, float]
    fit_clearance_m: float
    support_frac: float


@dataclass(frozen=True)
class Propulsion:
    prop_name: str
    prop_diameter_m: float
    n_rotors: int
    motor_mass_kg: float
    motor_esc_efficiency: float
    max_rpm: float
    max_motor_power_w: float
    uiuc_data_dir: Path
    uiuc_static_file: str
    uiuc_dynamic_files: tuple[str, ...]

    @property
    def max_rps(self) -> float:
        return self.max_rpm / 60.0


@dataclass(frozen=True)
class Material:
    name: str
    density_kg_m3: float
    tensile_strength_pa: float
    youngs_modulus_pa: float


@dataclass(frozen=True)
class Platform:
    battery: Battery
    propulsion: Propulsion
    materials: tuple[Material, ...]
    fc_mount_flat_m: float
    fc_stack_height_m: float
    fc_mass_kg: float
    wiring_mass_kg: float
    safety_factor: float
    max_tip_deflection_frac: float
    resonance_band_frac: float
    plate_base_m: float
    standoff_radius_m: float
    standoff_mass_per_m: float
    rotor_tip_clearance_m: float
    motor_pad_radius_m: float
    motor_pad_height_m: float
    motor_body_radius_m: float
    motor_body_height_m: float

    def material_for(self, gene_value: float) -> Material:
        """Map the continuous material gene in [0, 1) to a library entry."""
        idx = min(int(gene_value * len(self.materials)), len(self.materials) - 1)
        return self.materials[idx]

    @property
    def fixed_mass_kg(self) -> float:
        """Everything that is not the frame."""
        return (self.battery.mass_kg
                + self.propulsion.n_rotors * self.propulsion.motor_mass_kg
                + self.fc_mass_kg + self.wiring_mass_kg)


@dataclass(frozen=True)
class Mission:
    legs_m: tuple[float, ...]
    cruise_speed_ms: float
    altitude_m: float
    accel_limit_ms2: float
    sim_rate_hz: float
    time_factor_limit: float

    @property
    def total_km(self) -> float:
        return sum(abs(x) for x in self.legs_m) / 1000.0


@dataclass(frozen=True)
class RainModel:
    drop_terminal_velocity_ms: float
    thrust_efficiency_penalty: float
    film_mass_kg_m2: float


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    temperature_c: float
    wind_speed_ms: float
    wind_from_deg: float
    turbulence: str
    rain_mm_h: float
    seed: int
    density_altitude_m: float | None = None

    @property
    def air_density(self) -> float:
        if self.density_altitude_m is not None:
            return isa_density(self.density_altitude_m)
        return P0 / (R_AIR * (self.temperature_c + 273.15))

    @property
    def wind_ne(self) -> tuple[float, float]:
        """Mean wind velocity vector (north, east). 'from' 0 deg blows south."""
        rad = math.radians(self.wind_from_deg)
        return (-self.wind_speed_ms * math.cos(rad), -self.wind_speed_ms * math.sin(rad))

    @property
    def turbulence_w20_ms(self) -> float:
        return TURBULENCE_W20_MS[self.turbulence]


@dataclass(frozen=True)
class Aggregation:
    mode: str            # mean_plus_worst | minimax
    lambda_worst: float
    target_whkm: float | None  # class benchmark shown in the gallery chart
    record_whkm: float | None  # record-class stretch line


@dataclass(frozen=True)
class EarlyReject:
    enabled: bool
    margin: float
    penalty_factor: float


@dataclass(frozen=True)
class Patience:
    enabled: bool
    generations: int
    min_rel_improvement: float
    pivot_fraction: float
    sigma_boost: float
    decent_factor: float


@dataclass(frozen=True)
class GAParams:
    tournament_k: int
    elitism: int
    crossover_prob: float
    sbx_eta: float
    mutation_prob_per_gene: float
    mutation_sigma0: float
    mutation_sigma_decay: float
    mutation_sigma_min: float
    immigrant_prob: float
    patience: Patience


@dataclass(frozen=True)
class Designer:
    enabled: bool
    every_generations: int
    candidates: int
    gen0_candidates: int  # designed slots in the initial population (0 = off)
    model: str
    timeout_s: float


@dataclass(frozen=True)
class Narrator:
    enabled: bool
    model: str
    timeout_s: float


@dataclass(frozen=True)
class Evolution:
    optimizer: str
    population: int
    generations: int
    seed: int | None  # None = draw a fresh random seed per new run
    ga: GAParams
    cmaes_sigma0: float
    designer: Designer
    narrator: Narrator
    workers: int
    task_timeout_s: float
    results_dir: Path


@dataclass(frozen=True)
class Config:
    root: Path
    platform: Platform
    mission: Mission
    scenarios: tuple[Scenario, ...]
    aggregation: Aggregation
    early_reject: EarlyReject
    rain: RainModel
    evolution: Evolution
    baseline_scenario: str = "calm_warm"

    def scenario(self, name: str) -> Scenario:
        for s in self.scenarios:
            if s.name == name:
                return s
        raise KeyError(name)


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def load_config(root: Path | str = ".", config_dir: str = "config",
                **overrides: Any) -> Config:
    """Load platform/scenarios/evolution YAML into one Config.

    overrides: population, generations, seed, optimizer, workers, results_dir.
    """
    root = Path(root).resolve()
    cdir = root / config_dir
    plat = _load_yaml(cdir / "platform.yaml")
    scen = _load_yaml(cdir / "scenarios.yaml")
    evo = _load_yaml(cdir / "evolution.yaml")

    b = plat["battery"]
    battery = Battery(
        capacity_mah=float(b["capacity_mah"]),
        voltage_nominal=float(b["voltage_nominal"]),
        mass_kg=float(b["mass_kg"]),
        size_m=tuple(float(x) for x in b["size_m"]),  # type: ignore[arg-type]
        fit_clearance_m=float(b["fit_clearance_m"]),
        support_frac=float(b["support_frac"]),
    )
    p = plat["propulsion"]
    propulsion = Propulsion(
        prop_name=str(p["prop_name"]),
        prop_diameter_m=float(p["prop_diameter_m"]),
        n_rotors=int(p["n_rotors"]),
        motor_mass_kg=float(p["motor_mass_kg"]),
        motor_esc_efficiency=float(p["motor_esc_efficiency"]),
        max_rpm=float(p["max_rpm"]),
        max_motor_power_w=float(p["max_motor_power_w"]),
        uiuc_data_dir=root / str(p["uiuc_data_dir"]),
        uiuc_static_file=str(p["uiuc_static_file"]),
        uiuc_dynamic_files=tuple(str(x) for x in p["uiuc_dynamic_files"]),
    )
    materials = tuple(
        Material(name=str(m["name"]), density_kg_m3=float(m["density_kg_m3"]),
                 tensile_strength_pa=float(m["tensile_strength_pa"]),
                 youngs_modulus_pa=float(m["youngs_modulus_pa"]))
        for m in plat["materials"])
    fc, st, ge = plat["flight_controller"], plat["structure"], plat["geometry"]
    platform = Platform(
        battery=battery, propulsion=propulsion, materials=materials,
        fc_mount_flat_m=float(fc["mount_flat_m"]),
        fc_stack_height_m=float(fc["stack_height_m"]),
        fc_mass_kg=float(fc["mass_kg"]),
        wiring_mass_kg=float(fc["wiring_receiver_mass_kg"]),
        safety_factor=float(st["safety_factor"]),
        max_tip_deflection_frac=float(st["max_tip_deflection_frac"]),
        resonance_band_frac=float(st["resonance_band_frac"]),
        plate_base_m=float(st["plate_base_m"]),
        standoff_radius_m=float(st["standoff_radius_m"]),
        standoff_mass_per_m=float(st["standoff_mass_per_m"]),
        rotor_tip_clearance_m=float(ge["rotor_tip_clearance_m"]),
        motor_pad_radius_m=float(ge["motor_pad_radius_m"]),
        motor_pad_height_m=float(ge["motor_pad_height_m"]),
        motor_body_radius_m=float(ge["motor_body_radius_m"]),
        motor_body_height_m=float(ge["motor_body_height_m"]),
    )

    mi = scen["mission"]
    mission = Mission(
        legs_m=tuple(float(x) for x in mi["legs_m"]),
        cruise_speed_ms=float(mi["cruise_speed_ms"]),
        altitude_m=float(mi["altitude_m"]),
        accel_limit_ms2=float(mi["accel_limit_ms2"]),
        sim_rate_hz=float(mi["sim_rate_hz"]),
        time_factor_limit=float(mi["time_factor_limit"]),
    )
    scenarios = tuple(
        Scenario(
            name=name,
            description=str(sc.get("description", "")),
            temperature_c=float(sc["temperature_c"]),
            wind_speed_ms=float(sc["wind_speed_ms"]),
            wind_from_deg=float(sc["wind_from_deg"]),
            turbulence=str(sc["turbulence"]),
            rain_mm_h=float(sc["rain_mm_h"]),
            seed=int(sc["seed"]),
            density_altitude_m=(float(sc["density_altitude_m"])
                                if "density_altitude_m" in sc else None),
        )
        for name, sc in scen["scenarios"].items()
    )
    ag = scen["aggregation"]
    aggregation = Aggregation(
        mode=str(ag["mode"]), lambda_worst=float(ag["lambda_worst"]),
        target_whkm=(float(ag["target_aggregate_whkm"])
                     if ag.get("target_aggregate_whkm") else None),
        record_whkm=(float(ag["record_aggregate_whkm"])
                     if ag.get("record_aggregate_whkm") else None))
    er = scen["early_reject"]
    early = EarlyReject(bool(er["enabled"]), float(er["margin"]), float(er["penalty_factor"]))
    rm = scen["rain_model"]
    rain = RainModel(float(rm["drop_terminal_velocity_ms"]),
                     float(rm["thrust_efficiency_penalty"]),
                     float(rm["film_mass_kg_m2"]))

    ga = evo["ga"]
    pt = ga.get("patience", {})
    patience = Patience(
        enabled=bool(pt.get("enabled", False)),
        generations=int(pt.get("generations", 6)),
        min_rel_improvement=float(pt.get("min_rel_improvement", 0.005)),
        pivot_fraction=float(pt.get("pivot_fraction", 0.5)),
        sigma_boost=float(pt.get("sigma_boost", 3.0)),
        decent_factor=float(pt.get("decent_factor", 1.3)),
    )
    ga_params = GAParams(
        tournament_k=int(ga["tournament_k"]), elitism=int(ga["elitism"]),
        crossover_prob=float(ga["crossover_prob"]), sbx_eta=float(ga["sbx_eta"]),
        mutation_prob_per_gene=float(ga["mutation_prob_per_gene"]),
        mutation_sigma0=float(ga["mutation_sigma0"]),
        mutation_sigma_decay=float(ga["mutation_sigma_decay"]),
        mutation_sigma_min=float(ga["mutation_sigma_min"]),
        immigrant_prob=float(ga["immigrant_prob"]),
        patience=patience,
    )
    ex = evo["execution"]
    workers = overrides.get("workers")
    if workers in (None, 0):
        workers = ex["workers"]
    if workers == "auto":
        import os
        workers = os.cpu_count() or 4
    results_dir = Path(overrides.get("results_dir") or ex["results_dir"])
    if not results_dir.is_absolute():
        results_dir = root / results_dir
    nr = evo.get("narrator", {})
    narrator = Narrator(
        enabled=bool(nr.get("enabled", False)),
        model=str(nr.get("model", "") or ""),
        timeout_s=float(nr.get("timeout_s", 300)),
    )
    dz = evo.get("designer", {})
    designer = Designer(
        enabled=bool(dz.get("enabled", False)),
        every_generations=int(dz.get("every_generations", 6)),
        candidates=int(dz.get("candidates", 3)),
        gen0_candidates=int(dz.get("gen0_candidates", 0)),
        model=str(dz.get("model", "") or ""),
        timeout_s=float(dz.get("timeout_s", 300)),
    )
    evolution = Evolution(
        optimizer=str(overrides.get("optimizer") or evo["optimizer"]),
        population=int(overrides.get("population") or evo["population"]),
        generations=int(overrides.get("generations") or evo["generations"]),
        seed=int(overrides["seed"]) if overrides.get("seed") is not None
        else (int(evo["seed"]) if evo.get("seed") is not None else None),
        ga=ga_params,
        cmaes_sigma0=float(evo["cmaes"]["sigma0"]),
        designer=designer,
        narrator=narrator,
        workers=int(workers),
        task_timeout_s=float(ex["task_timeout_s"]),
        results_dir=results_dir,
    )
    return Config(root=root, platform=platform, mission=mission, scenarios=scenarios,
                  aggregation=aggregation, early_reject=early, rain=rain,
                  evolution=evolution)
