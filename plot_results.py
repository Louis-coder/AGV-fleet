import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

os.makedirs("figs", exist_ok=True)
df = pd.read_csv("results_exp1_throughput.csv")

COLORS = {"centralized": "#1B5FD4", "decentralized": "#D4671B"}
LABELS = {"centralized": "Centralized dispatch", "decentralized": "Decentralized (zoned) dispatch"}

# ---------------------------------------------------------------- Fig 1: throughput vs fleet size
fig, ax = plt.subplots(figsize=(8, 5.2))
for mode in ["centralized", "decentralized"]:
    g = df[df.dispatch_mode == mode].groupby("fleet_size").throughput_per_h.agg(["mean", "std"]).reset_index()
    ax.errorbar(g.fleet_size, g["mean"], yerr=g["std"], marker="o", capsize=3,
                color=COLORS[mode], label=LABELS[mode], linewidth=2)
ax.axhline(120, color="gray", linestyle="--", linewidth=1, label="Demand (120 requests/h)")
ax.set_xlabel("Fleet size (number of AGVs)")
ax.set_ylabel("Steady-state throughput (completed tasks / h)")
ax.set_title("Throughput vs fleet size: saturation and congestion collapse\n(mean \u00b1 s.d. over 8 random seeds)")
ax.legend(frameon=False)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig("figs/fig1_throughput_vs_fleet.png", dpi=170)
plt.close(fig)

# ---------------------------------------------------------------- Fig 2: wait time vs fleet size
fig, ax = plt.subplots(figsize=(8, 5.2))
for mode in ["centralized", "decentralized"]:
    g = df[df.dispatch_mode == mode].groupby("fleet_size").mean_wait_min.agg(["mean", "std"]).reset_index()
    ax.errorbar(g.fleet_size, g["mean"], yerr=g["std"], marker="o", capsize=3,
                color=COLORS[mode], label=LABELS[mode], linewidth=2)
ax.set_xlabel("Fleet size (number of AGVs)")
ax.set_ylabel("Mean request wait time before assignment (min)")
ax.set_title("Dispatch queueing delay vs fleet size")
ax.legend(frameon=False)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig("figs/fig2_wait_vs_fleet.png", dpi=170)
plt.close(fig)

# ---------------------------------------------------------------- Fig 3: congestion (frac blocked) vs fleet size
fig, ax = plt.subplots(figsize=(8, 5.2))
for mode in ["centralized", "decentralized"]:
    g = df[df.dispatch_mode == mode].groupby("fleet_size").frac_time_blocked.agg(["mean", "std"]).reset_index()
    ax.errorbar(g.fleet_size, g["mean"] * 100, yerr=g["std"] * 100, marker="o", capsize=3,
                color=COLORS[mode], label=LABELS[mode], linewidth=2)
ax.set_xlabel("Fleet size (number of AGVs)")
ax.set_ylabel("Share of AGV time spent blocked / waiting for right-of-way (%)")
ax.set_title("Emergent congestion vs fleet size")
ax.legend(frameon=False)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig("figs/fig3_congestion_vs_fleet.png", dpi=170)
plt.close(fig)

# ---------------------------------------------------------------- Fig 4: seed-to-seed variability (part c)
fig, ax = plt.subplots(figsize=(8, 5.2))
chosen = [5, 10, 15, 20]
data = [df[(df.dispatch_mode == "centralized") & (df.fleet_size == f)].throughput_per_h.values for f in chosen]
bp = ax.boxplot(data, positions=range(len(chosen)), widths=0.5, patch_artist=True,
                 boxprops=dict(facecolor="#AFC6F0", color="#1B5FD4"),
                 medianprops=dict(color="#0B2E7A"))
for i, d in enumerate(data):
    ax.scatter(np.random.normal(i, 0.05, size=len(d)), d, color="#1B5FD4", alpha=0.7, zorder=3, s=22)
ax.set_xticks(range(len(chosen)))
ax.set_xticklabels([f"N={f}" for f in chosen])
ax.set_ylabel("Steady-state throughput (tasks / h)")
ax.set_title("Congestion is an emergent, seed-sensitive phenomenon\n(8 random seeds per fleet size, centralized dispatch)")
ax.grid(alpha=0.25, axis="y")
plt.tight_layout()
plt.savefig("figs/fig4_seed_variability.png", dpi=170)
plt.close(fig)

print("figs 1-4 done")
