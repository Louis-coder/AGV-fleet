# AGV-fleet
# AGV Fleet Sizing Simulation — How to Run



## Files

| File | What it does |
|---|---|
| `factory_graph.py` | Builds the 30-node aisle network (12 stations, 2 charging nodes). |
| `agv_sim.py` | The simulation engine itself (agents, locks, dispatch, deadlock, charging). |
| `run_experiments.py` | Runs the full experiment sweep (224 + 80 simulation runs) and writes CSVs. |
| `plot_network.py` | Draws the network topology diagram (Figure 1 in the report). |
| `plot_results.py` | Draws the throughput/wait/congestion/variability figures (Figures 2–5). |
| `plot_deadlock.py` | Draws the deadlock-comparison figures (Figures 6–8). |
| `plot_recommendation.py` | Draws the centralized-vs-decentralized recommendation-range figure (Figure 9). |

## 1. Install dependencies

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

(or individually: `pip install simpy networkx matplotlib pandas numpy`)

## 2. Sanity-check the network graph

```bash
python3 factory_graph.py
```
Expected output:
```
nodes: 30 edges: 49
stations: ['N0_2', 'N0_4', 'N1_1', ...]
chargers: ['N1_2', 'N3_2']
```

## 3. Run a single simulation

`agv_sim.py` has a runnable example at the bottom (`__main__` block):

```bash
python3 agv_sim.py
```
This runs one 240-minute simulation (fleet=15, centralized, avoidance mode,
seed=1) and prints a dict of results (throughput, wait times, congestion,
deadlock counts, etc.) plus wall-clock elapsed time (typically ~0.15s).



```python
from agv_sim import SimConfig, run_once

cfg = SimConfig(
    fleet_size=6,              # 5-30, per the assignment brief
    dispatch_mode="centralized",   # or "decentralized"
    deadlock_mode="avoidance",     # or "naive"
    seed=42,                       # any int, for reproducibility
    sim_duration_min=360,          # 6 simulated hours
    warmup_min=60,                 # discard first hour (steady-state only)
)
result = run_once(cfg)
print(result)
```

`result` is a dict with keys: `throughput_per_h`, `mean_wait_min`,
`p95_wait_min`, `mean_cycle_min`, `frac_time_blocked`, `n_deadlock_events`,
`deadlock_events_per_h`, `manual_interventions`, `reroutes`, and more —
see the `summarize()` method in `agv_sim.py` for the full list.

## 4. Run the full experiment sweep (reproduces the report's data)

```bash
python3 run_experiments.py
```

This runs:
- **Experiment 1** (224 runs): fleet sizes {3,4,5,6,7,8,10,12,15,18,20,23,26,29} ×
  {centralized, decentralized} × 8 random seeds → `results_exp1_throughput.csv`
- **Experiment 2** (80 runs): fleet sizes {5,10,15,20,25} ×
  {avoidance, naive} × 8 random seeds → `results_exp2_deadlock.csv`

Takes about **75–90 seconds** total on a typical machine (progress is
printed every 20 runs). No GPU or special hardware needed — the whole
30-node/30-AGV simulation is lightweight.

## 5. Generate the figures

```bash
python3 plot_network.py         # Figure 1: network topology diagram
python3 plot_results.py         # Figures 2-5: throughput, wait, congestion, seed variability
python3 plot_deadlock.py        # Figures 6-8: deadlock frequency, throughput, recovery breakdown
python3 plot_recommendation.py  # Figure 9: centralized vs decentralized (recommended range, fleet 4-8)
```

All figures are written to a `figs/` subfolder (created automatically) as
170 DPI PNGs, ready to drop into a report or slides. `FLEET_SIZES_MAIN` in
`run_experiments.py` includes fleet sizes 4, 6 and 7 specifically so that
`plot_recommendation.py` (Figure 9) and the sharp peak in `plot_results.py`
(Figure 2) have the resolution they need around the saturation point.

## 6. Everything at once

```bash
pip install -r requirements.txt
python3 run_experiments.py
python3 plot_network.py
python3 plot_results.py
python3 plot_deadlock.py
python3 plot_recommendation.py
```

Total run time: roughly 1.5-2 minutes.

## Adjusting parameters

- Change demand rate, battery, charging, or timing constants: edit the
  constants near the top of `agv_sim.py` (e.g. `BATTERY_CAPACITY_MIN`,
  `CHARGE_DURATION_MIN`, `DEADLOCK_SCAN_PERIOD_MIN`).
- Change network layout, station placement, or edge length/speed: edit
  `factory_graph.py`.
- Change which fleet sizes / seeds / dispatch modes are swept: edit the
  `FLEET_SIZES_MAIN`, `FLEET_SIZES_DEADLOCK`, and `N_SEEDS` constants near
  the top of `run_experiments.py`.
