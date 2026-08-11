"""
Factory aisle-network graph.

Design rationale (documented honestly in the report):
- 30 nodes arranged as a 6 x 5 Manhattan grid, matching the "30-node aisle
  network" in the brief. A grid is the simplest layout that gives every
  node degree <= 4, admits cycles (needed for deadlock to be possible at
  all), and is a standard stylisation of aisle networks in the AGV
  literature (e.g. Vivaldini et al. 2016; Zou et al. 2018).
- 12 of the 30 nodes are pick-up/drop-off STATIONS (S1-S12); the rest are
  free-standing junction/aisle nodes that AGVs pass through but that never
  originate or receive a transport request.
- 2 nodes are designated CHARGING stations (each modelled as a resource
  with a small number of charging bays).
- Every edge represents a single-lane aisle segment: capacity 1, i.e. only
  one AGV may occupy a given node at a time. This is the standard
  "zone control" abstraction (Fanti & Zhou, 2004; Fanti et al., 2018) used
  to keep the collision/right-of-way model tractable while still producing
  genuine congestion and deadlock.
"""
import networkx as nx
import itertools

ROWS, COLS = 5, 6  # 30 nodes
SEGMENT_LENGTH_M = 12.0     # metres per aisle segment (assumption)
AGV_SPEED_MPS = 1.4         # m/s, typical warehouse AGV cruise speed (assumption)
# All simulation time is in MINUTES (sim_duration_min, request rate/hour,
# battery minutes, etc.) so edge traversal time must be converted from
# seconds (distance / speed) to minutes here, once, at the source.
SEGMENT_TIME_MIN = (SEGMENT_LENGTH_M / AGV_SPEED_MPS) / 60.0


def node_id(r, c):
    return f"N{r}_{c}"


def build_graph():
    G = nx.Graph()
    for r in range(ROWS):
        for c in range(COLS):
            G.add_node(node_id(r, c), row=r, col=c, kind="junction")

    # grid edges (Manhattan aisles)
    for r in range(ROWS):
        for c in range(COLS):
            if c + 1 < COLS:
                G.add_edge(node_id(r, c), node_id(r, c + 1),
                           length=SEGMENT_LENGTH_M,
                           time=SEGMENT_TIME_MIN)
            if r + 1 < ROWS:
                G.add_edge(node_id(r, c), node_id(r + 1, c),
                           length=SEGMENT_LENGTH_M,
                           time=SEGMENT_TIME_MIN)

    # 12 stations, chosen on a checkerboard sub-lattice (row+col even) so
    # that NO two stations are ever directly graph-adjacent. This is a
    # deliberate layout choice: adjacent single-edge station pairs create a
    # brittle degree-2 chokepoint where two opposing AGVs can only ever
    # resolve a head-on conflict by one of them reversing off the station
    # itself - an unrealistic, single point-of-failure layout that a real
    # facility designer would avoid. Spacing stations out is the honest
    # analogue of "P/D points sit at work-cell perimeters with an aisle
    # buffer around them", not on a shared single-lane spur.
    station_coords = [
        (0, 2), (0, 4),
        (1, 1), (1, 3), (1, 5),
        (2, 0), (2, 4),
        (3, 1), (3, 3), (3, 5),
        (4, 2), (4, 4),
    ]
    assert len(station_coords) == 12
    stations = []
    for i, (r, c) in enumerate(station_coords, start=1):
        nid = node_id(r, c)
        G.nodes[nid]["kind"] = "station"
        G.nodes[nid]["label"] = f"S{i}"
        stations.append(nid)

    # 2 charging nodes, chosen away from the busiest through-routes but
    # reachable from all quadrants (assumption: dedicated charging bays
    # co-located with junctions near the centre of each half of the plant).
    charge_coords = [(1, 2), (3, 2)]
    chargers = []
    for (r, c) in charge_coords:
        nid = node_id(r, c)
        G.nodes[nid]["kind"] = "charger" if G.nodes[nid]["kind"] == "junction" else G.nodes[nid]["kind"]
        G.nodes[nid]["charger"] = True
        chargers.append(nid)

    return G, stations, chargers


if __name__ == "__main__":
    G, stations, chargers = build_graph()
    print("nodes:", G.number_of_nodes(), "edges:", G.number_of_edges())
    print("stations:", stations)
    print("chargers:", chargers)
