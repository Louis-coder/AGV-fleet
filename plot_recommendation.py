"""
Generates Figure 9: centralized vs decentralized dispatch across the
recommended operating range (fleet 4-8).

Requires results_exp1_throughput.csv to already exist (run
run_experiments.py first) and to include fleet sizes 4-8, which
FLEET_SIZES_MAIN in run_experiments.py covers.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

os.makedirs("figs", exist_ok=True)
df = pd.read_csv("results_exp1_throughput.csv")

fleets = [4, 5, 6, 7, 8]
metrics = ["throughput_per_h", "mean_wait_min", "frac_time_blocked"]
titles = ["Throughput (tasks/h)", "Mean wait (min)", "Blocked time share (%)"]

fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
for ax, met, title in zip(axes, metrics, titles):
    cvals = [df[(df.fleet_size == f) & (df.dispatch_mode == "centralized")][met].mean() for f in fleets]
    dvals = [df[(df.fleet_size == f) & (df.dispatch_mode == "decentralized")][met].mean() for f in fleets]
    if met == "frac_time_blocked":
        cvals = [v * 100 for v in cvals]
        dvals = [v * 100 for v in dvals]
    x = np.arange(len(fleets))
    w = 0.35
    ax.bar(x - w / 2, cvals, w, label="Centralized", color="#1B5FD4")
    ax.bar(x + w / 2, dvals, w, label="Decentralized", color="#D4671B")
    ax.set_xticks(x)
    ax.set_xticklabels(fleets)
    ax.set_xlabel("Fleet size")
    ax.set_title(title, fontsize=10)
    ax.grid(alpha=0.25, axis="y")
axes[0].legend(frameon=False, fontsize=8)
plt.suptitle("Centralized vs decentralized dispatch around the recommended operating range", fontsize=12)
plt.tight_layout()
plt.savefig("figs/fig8_recommendation_range.png", dpi=170)
print("saved figs/fig8_recommendation_range.png")
