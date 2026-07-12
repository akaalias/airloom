"""100 Hz point-mass flight simulator (3 translational DOF, quasi-static
attitude).

The vehicle is a point mass with a thrust vector: a cascaded controller turns
velocity error into a commanded acceleration, the required thrust vector
(gravity + drag + rain effects + commanded acceleration) sets the tilt --
i.e. the quad leans into the relative wind (mean wind + Dryden gusts + its own
airspeed) -- and rotor speeds are solved each step from the UIUC coefficient
tables to satisfy the force balance. Electrical energy is integrated to Wh.

Simplifications (documented in README): instantaneous attitude (no rotational
dynamics), identical rotor loading (no per-rotor mixing), gusts synthesized at
the commanded cruise speed, no rotor-rotor interaction.

Rain (all knobs in config/scenarios.yaml, empirical -- see NASA TP-2671,
Dunham et al., "The Influence of Heavy Rain on Airfoil Performance", and NASA
heavy-rain flight research): (a) a water film adds mass proportional to the
top-projected area, (b) rain adds momentum drag via an equivalent suspended
water density rho_rain = flux / v_terminal plus a vertical impact force on the
top area, (c) rotor thrust coefficient is derated 15%.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .aero import DragTable
from .config import Mission, RainModel, Scenario
from .dryden import dryden_gusts
from .rotor_model import RotorModel

G = 9.80665
KP_VEL = 2.0          # velocity-loop gain, 1/s
KP_ALT = 1.0          # altitude-loop gain, 1/s
CLIMB_LIMIT = 3.0     # m/s
SAT_TIME_LIMIT = 0.5  # cumulative seconds of saturated rotors -> invalid


@dataclass(frozen=True)
class ScenarioResult:
    scenario: str
    valid: bool
    failure_reason: str | None
    wh_per_km: float
    energy_wh: float
    avg_power_w: float
    flight_time_s: float
    peak_rotor_thrust_n: float
    max_tilt_deg: float
    sat_time_s: float


def _fail(name: str, reason: str, energy_wh: float = math.inf,
          peak: float = 0.0) -> ScenarioResult:
    return ScenarioResult(name, False, reason, math.inf, energy_wh, math.inf,
                          math.inf, peak, 90.0, math.inf)


def simulate_scenario(total_mass: float, drag: DragTable, rotor: RotorModel,
                      scenario: Scenario, mission: Mission,
                      rain_model: RainModel) -> ScenarioResult:
    dt = 1.0 / mission.sim_rate_hz
    vc = mission.cruise_speed_ms
    rho = scenario.air_density
    diam = rotor.diameter
    disk_area = math.pi * (diam / 2.0) ** 2

    nominal_t = sum(abs(x) for x in mission.legs_m) / vc
    max_steps = int((nominal_t * mission.time_factor_limit + 30.0) / dt)

    # -- steady wind + frozen per-scenario gust history (NED, z up)
    wind_n, wind_e = scenario.wind_ne
    gusts = dryden_gusts(max_steps, dt, vc, mission.altitude_m,
                         scenario.turbulence_w20_ms, scenario.seed)
    if scenario.wind_speed_ms > 1e-6:
        ux, uy = wind_n / scenario.wind_speed_ms, wind_e / scenario.wind_speed_ms
    else:
        ux, uy = 1.0, 0.0  # align gust axes north if there is no mean wind
    gu, gv, gw = gusts[0], gusts[1], gusts[2]

    # -- rain terms
    raining = scenario.rain_mm_h > 0.0
    ct_scale = 1.0 - rain_model.thrust_efficiency_penalty if raining else 1.0
    flux = scenario.rain_mm_h / 3600.0  # kg/(m^2 s) of water
    rho_rain = flux / rain_model.drop_terminal_velocity_ms if raining else 0.0
    m_eff = total_mass + (rain_model.film_mass_kg_m2 * drag.a_top if raining else 0.0)
    f_rain_z = rho_rain * rain_model.drop_terminal_velocity_ms ** 2 * drag.a_top
    weight = m_eff * G

    # -- mission legs along the north axis
    legs = []
    target = 0.0
    for leg in mission.legs_m:
        target += leg
        legs.append((target, 1.0 if leg > 0 else -1.0))

    # -- state
    x = y = 0.0
    z = mission.altitude_m
    vx = vy = vz = 0.0
    leg_i = 0
    tilt = 0.0
    n_rotor = rotor.solve_n(weight / 4.0, 0.0, rho, ct_scale=ct_scale)
    energy_j = 0.0
    sat_time = 0.0
    peak_thrust = 0.0
    max_tilt = 0.0
    a_lim = mission.accel_limit_ms2
    ct_grid, cp_grid = rotor.ct_grid, rotor.cp_grid  # noqa: F841 (locals for speed)
    step = 0

    while step < max_steps:
        leg_target, heading = legs[leg_i]
        remaining = (leg_target - x) * heading
        if remaining <= 0.5:
            leg_i += 1
            if leg_i >= len(legs):
                break
            continue

        # -- commanded velocity: cruise, braking parabola near the leg end
        v_des = heading * min(vc, math.sqrt(max(2.0 * a_lim * remaining, 0.0)))
        vz_des = KP_ALT * (mission.altitude_m - z)
        if vz_des > CLIMB_LIMIT:
            vz_des = CLIMB_LIMIT
        elif vz_des < -CLIMB_LIMIT:
            vz_des = -CLIMB_LIMIT

        ax_c = KP_VEL * (v_des - vx)
        ay_c = KP_VEL * (0.0 - vy)
        az_c = KP_VEL * (vz_des - vz)
        ah = math.hypot(ax_c, ay_c)
        if ah > a_lim:
            s = a_lim / ah
            ax_c *= s; ay_c *= s
        if az_c > a_lim:
            az_c = a_lim
        elif az_c < -a_lim:
            az_c = -a_lim

        # -- relative wind (vehicle velocity minus air velocity)
        wn = wind_n + gu[step] * ux - gv[step] * uy
        we = wind_e + gu[step] * uy + gv[step] * ux
        vax = vx - wn
        vay = vy - we
        vaz = vz - gw[step]
        va2 = vax * vax + vay * vay + vaz * vaz
        va = math.sqrt(va2)

        # -- parasite drag from the rasterized CdA table (previous-step tilt)
        if va > 1e-6:
            # azimuth of the relative wind w.r.t. body x (= heading, north/south)
            bx = vax * heading
            by = vay * heading
            azim = math.atan2(abs(by), abs(bx))
            cda = drag.cda(tilt, azim)
            qf = -0.5 * (rho + rho_rain) * cda * va
            dx_ = qf * vax; dy_ = qf * vay; dz_ = qf * vaz
        else:
            dx_ = dy_ = dz_ = 0.0

        # -- thrust vector required for the commanded acceleration
        tx = m_eff * ax_c - dx_
        ty = m_eff * ay_c - dy_
        tz = m_eff * az_c + weight - dz_ + f_rain_z
        if tz < 0.1 * weight:  # never command negative/level-inverted thrust
            tz = 0.1 * weight
        t_mag = math.sqrt(tx * tx + ty * ty + tz * tz)
        tilt = math.acos(tz / t_mag)
        if tilt > max_tilt:
            max_tilt = tilt

        # -- rotor wash pressing on the arm planform under the disks
        v_i = math.sqrt(t_mag / (8.0 * rho * disk_area))  # T/4 per rotor
        f_wash = 0.5 * rho * v_i * v_i * drag.wash_cda
        t_req = t_mag + f_wash
        t_per = t_req / 4.0

        # -- rotor speed from the measured CT(J) tables
        ux_t, uy_t, uz_t = tx / t_mag, ty / t_mag, tz / t_mag
        v_axial = vax * ux_t + vay * uy_t + vaz * uz_t
        if v_axial < 0.0:
            v_axial = 0.0
        n = rotor.solve_n(t_per, v_axial, rho, ct_scale=ct_scale, n_guess=n_rotor)

        saturated = n > rotor.max_rps
        if saturated:
            n = rotor.max_rps
            sat_time += dt
        n_rotor = n
        p_one = rotor.electrical_power(n, v_axial, rho)
        if p_one > rotor.max_motor_power_w and not saturated:
            sat_time += dt
        energy_j += 4.0 * p_one * dt

        j_adv = v_axial / (n * diam)
        t_act_per = rho * n * n * diam ** 4 * rotor.ct(j_adv) * ct_scale
        if t_act_per > peak_thrust:
            peak_thrust = t_act_per
        t_act = 4.0 * t_act_per - f_wash

        # -- integrate (semi-implicit Euler)
        axx = (t_act * ux_t + dx_) / m_eff
        ayy = (t_act * uy_t + dy_) / m_eff
        azz = (t_act * uz_t + dz_ - weight - f_rain_z) / m_eff
        vx += axx * dt; vy += ayy * dt; vz += azz * dt
        x += vx * dt; y += vy * dt; z += vz * dt

        if sat_time > SAT_TIME_LIMIT:
            return _fail(scenario.name, "rotor saturation (cannot hold commanded speed)",
                         energy_j / 3600.0, peak_thrust)
        if abs(y) > 50.0 or abs(z - mission.altitude_m) > 20.0:
            return _fail(scenario.name, "control divergence", energy_j / 3600.0,
                         peak_thrust)
        step += 1

    if leg_i < len(legs):
        return _fail(scenario.name, "mission not completed in time (speed not held)",
                     energy_j / 3600.0, peak_thrust)

    t_total = step * dt
    energy_wh = energy_j / 3600.0
    return ScenarioResult(
        scenario=scenario.name, valid=True, failure_reason=None,
        wh_per_km=energy_wh / mission.total_km, energy_wh=energy_wh,
        avg_power_w=energy_j / t_total, flight_time_s=t_total,
        peak_rotor_thrust_n=peak_thrust, max_tilt_deg=math.degrees(max_tilt),
        sat_time_s=sat_time)
