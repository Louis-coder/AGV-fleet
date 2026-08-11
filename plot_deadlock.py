import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

os.makedirs("figs", exist_ok=True)
df = pd.read_csv("results_exp2_deadlock.csv")

COLORS = {"avoidance": "#1B8F4C", "naive": "#B0271B"}
LABELS = {"avoidance": "Avoidance mode (head-on priority rule + monitor)",
          "naive": "Naive mode (monitor + recovery only)"}

# ---------------------------------------------------------------- Fig 5: deadlock events/h vs fleet
fig, ax = plt.subplots(figsize=(8, 5.2))
for mode in ["avoidance", "naive"]:
    g = df[df.deadlock_mode == mode].groupby("fleet_size").deadlock_events_per_h.agg(["mean", "std"]).reset_index()
    ax.errorbar(g.fleet_size, g["mean"], yerr=g["std"], marker="o", capsize=3,
                color=COLORS[mode], label=LABELS[mode], linewidth=2)
ax.set_xlabel("Fleet size (number of AGVs)")
ax.set_ylabel("Detected deadlock episodes / hour")
ax.set_title("Deadlock frequency vs fleet size:\navoidance rule helps most at low-moderate density")
ax.legend(frameon=False, fontsize=9)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig("figs/fig5_deadlock_events_vs_fleet.png", dpi=170)
plt.close(fig)

# ---------------------------------------------------------------- Fig 6: throughput naive vs avoidance
fig, ax = plt.subplots(figsize=(8, 5.2))
for mode in ["avoidance", "naive"]:
    g = df[df.deadlock_mode == mode].groupby("fleet_size").throughput_per_h.agg(["mean", "std"]).reset_index()
    ax.errorbar(g.fleet_size, g["mean"], yerr=g["std"], marker="o", capsize=3,
                color=COLORS[mode], label=LABELS[mode], linewidth=2)
ax.set_xlabel("Fleet size (number of AGVs)")
ax.set_ylabel("Steady-state throughput (tasks / h)")
ax.set_title("Throughput with vs without the head-on avoidance rule")
ax.legend(frameon=False, fontsize=9)
ax.grid(alpha=0.25)
plt.tight_layout()
plt.savefig("figs/fig6_throughput_avoidance_vs_naive.png", dpi=170)
plt.close(fig)

# ---------------------------------------------------------------- Fig 7: recovery mechanism breakdown
fig, ax = plt.subplots(figsize=(8, 5.2))
width = 0.35
fleets = sorted(df.fleet_size.unique())
avoid_manual = [df[(df.deadlock_mode == "avoidance") & (df.fleet_size == f)].manual_interventions.mean() for f in fleets]
naive_manual = [df[(df.deadlock_mode == "naive") & (df.fleet_size == f)].manual_interventions.mean() for f in fleets]
avoid_reroute = [df[(df.deadlock_mode == "avoidance") & (df.fleet_size == f)].reroutes.mean() for f in fleets]
naive_reroute = [df[(df.deadlock_mode == "naive") & (df.fleet_size == f)].reroutes.mean() for f in fleets]
x = np.arange(len(fleets))
ax.bar(x - width/2, avoid_reroute, width, label="Avoidance: total recoveries", color="#7FC29B")
ax.bar(x - width/2, avoid_manual, width, label="Avoidance: of which supervisory intervention", color="#1B8F4C")
ax.bar(x + width/2, naive_reroute, width, label="Naive: total recoveries", color="#E38B82")
ax.bar(x + width/2, naive_manual, width, label="Naive: of which supervisory intervention", color="#B0271B")
ax.set_xticks(x)
ax.set_xticklabels(fleets)
ax.set_xlabel("Fleet size (number of AGVs)")
ax.set_ylabel("Count over 6 h simulated (mean of 8 seeds)")
ax.set_title("How deadlocks get resolved: local side-step vs.\nsupervisory (whole-network) intervention")
ax.legend(frameon=False, fontsize=8)
ax.grid(alpha=0.25, axis="y")
plt.tight_layout()
plt.savefig("figs/fig7_recovery_breakdown.png", dpi=170)
plt.close(fig)

print("figs 5-7 done")
