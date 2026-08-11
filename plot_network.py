import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from factory_graph import build_graph

os.makedirs("figs", exist_ok=True)

G, stations, chargers = build_graph()
pos = {n: (d["col"], -d["row"]) for n, d in G.nodes(data=True)}

fig, ax = plt.subplots(figsize=(9, 6))
nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#B0B7C0", width=2.0)

junction_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "junction" and n not in chargers]
station_nodes = stations
charger_nodes = chargers

nx.draw_networkx_nodes(G, pos, nodelist=junction_nodes, node_color="#DDE3E8",
                        edgecolors="#8A93A0", node_size=260, ax=ax)
nx.draw_networkx_nodes(G, pos, nodelist=station_nodes, node_color="#3D6EDB",
                        edgecolors="#1B3D8F", node_size=520, ax=ax)
nx.draw_networkx_nodes(G, pos, nodelist=charger_nodes, node_color="#2FA86A",
                        edgecolors="#166B3F", node_size=420, node_shape="s", ax=ax)

labels = {n: G.nodes[n].get("label", "") for n in station_nodes}
nx.draw_networkx_labels(G, pos, labels=labels, font_size=8, font_color="white", ax=ax)

ax.scatter([], [], c="#3D6EDB", s=180, label="Station (pick-up / drop-off)")
ax.scatter([], [], c="#DDE3E8", s=140, edgecolors="#8A93A0", label="Junction node")
ax.scatter([], [], c="#2FA86A", s=140, marker="s", label="Charging node (2 bays)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=3, frameon=False, fontsize=9)

ax.set_title("Factory aisle network: 30 nodes, 12 stations, 2 charging nodes", fontsize=12, fontweight="bold")
ax.axis("off")
plt.tight_layout()
plt.savefig("figs/network_topology.png", dpi=170, bbox_inches="tight")
print("saved")
