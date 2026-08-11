"""
Full experiment matrix for the AGV fleet-sizing study.

Experiment 1 (throughput vs fleet size, main sweep):
    fleet in FLEET_SIZES x dispatch in {centralized, decentralized}
    x deadlock_mode = avoidance x seeds 0..N-1
    -> used for parts (b) saturation curve and (e) dispatch comparison.

Experiment 2 (deadlock characterisation):
    fleet in a coarser grid x deadlock_mode in {naive, avoidance}
    x dispatch = centralized x seeds 0..N-1
    -> used for part (d).

Both experiments reuse the same underlying run_once() so the numbers are
internally consistent; we simply vary which axis is swept.
"""
import csv
import time
import itertools
import statistics as stats

from agv_sim import SimConfig, run_once

SIM_DURATION_MIN = 360.0   # 6 simulated hours
WARMUP_MIN = 60.0          # discard first hour (fleet ramp-up transient)
N_SEEDS = 8

FLEET_SIZES_MAIN = [3, 4, 5, 6, 7, 8, 10, 12, 15, 18, 20, 23, 26, 29]
FLEET_SIZES_DEADLOCK = [5, 10, 15, 20, 25]

FIELDS = ["fleet_size", "dispatch_mode", "deadlock_mode", "seed",
          "n_completed", "throughput_per_h", "mean_wait_min", "p95_wait_min",
          "mean_cycle_min", "mean_total_min", "avg_n_blocked",
          "frac_time_blocked", "frac_time_travel", "frac_time_idle",
          "frac_time_charging", "n_deadlock_events", "deadlock_events_per_h",
          "reroutes", "manual_interventions"]


def run_experiment_1(path):
    rows = []
    combos = list(itertools.product(FLEET_SIZES_MAIN, ["centralized", "decentralized"], range(N_SEEDS)))
    t0 = time.time()
    for i, (fleet, dispatch, seed) in enumerate(combos):
        cfg = SimConfig(fleet_size=fleet, dispatch_mode=dispatch, deadlock_mode="avoidance",
                         seed=seed, sim_duration_min=SIM_DURATION_MIN, warmup_min=WARMUP_MIN)
        res = run_once(cfg)
        rows.append(res)
        if (i + 1) % 20 == 0:
            print(f"  exp1 {i+1}/{len(combos)}  elapsed={time.time()-t0:.1f}s")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("wrote", path, "rows:", len(rows), "elapsed", round(time.time() - t0, 1), "s")
    return rows


def run_experiment_2(path):
    rows = []
    combos = list(itertools.product(FLEET_SIZES_DEADLOCK, ["avoidance", "naive"], range(N_SEEDS)))
    t0 = time.time()
    for i, (fleet, deadlock, seed) in enumerate(combos):
        cfg = SimConfig(fleet_size=fleet, dispatch_mode="centralized", deadlock_mode=deadlock,
                         seed=seed, sim_duration_min=SIM_DURATION_MIN, warmup_min=WARMUP_MIN)
        res = run_once(cfg)
        rows.append(res)
        if (i + 1) % 20 == 0:
            print(f"  exp2 {i+1}/{len(combos)}  elapsed={time.time()-t0:.1f}s")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("wrote", path, "rows:", len(rows), "elapsed", round(time.time() - t0, 1), "s")
    return rows


if __name__ == "__main__":
    print("=== Experiment 1: throughput vs fleet size (centralized vs decentralized) ===")
    run_experiment_1("results_exp1_throughput.csv")
    print("=== Experiment 2: deadlock characterisation (naive vs avoidance) ===")
    run_experiment_2("results_exp2_deadlock.csv")
