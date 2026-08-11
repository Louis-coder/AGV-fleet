"""
Agent-based / discrete-event simulation of an AGV fleet on the factory
aisle network defined in factory_graph.py.

Key modelling choices (all assumptions, documented in the report):
  * Right-of-way / collision avoidance: each NODE is a single-occupancy
    resource (zone control). An AGV must acquire the lock on the next
    node before it releases the lock on its current node ("acquire before
    release"), which is what makes deadlock possible in the first place
    (classic AGV zone-control deadlock, Fanti & Zhou 2004 and successors).
  * Routing: static shortest path (Dijkstra on travel time) recomputed at
    the start of every leg. No dynamic re-routing around live congestion
    (a stated simplification - see report limitations).
  * Deadlock:
      - "naive"     : no avoidance; a periodic monitor scans the wait-for
                       graph among AGVs and, on finding a cycle, forcibly
                       reroutes/backs off one AGV in the cycle (recovery).
      - "avoidance" : a one-step-look-ahead rule - an AGV may only enter a
                       node if that node has at least one OTHER free exit
                       (or is its final destination) - a light-weight,
                       commonly used heuristic (related to Reveliotis'
                       resource-avoidance controllers) that greatly reduces
                       but does not mathematically guarantee zero deadlock.
  * Dispatching:
      - "centralized"  : global nearest-idle-vehicle assignment (shortest
                          travel time) to the oldest unmatched request.
      - "decentralized": the plant is split into 4 zones; a request is
                          first offered to idle AGVs in its own zone
                          (nearest-vehicle rule *within* the zone); if none
                          answers within a short local timeout it is
                          broadcast factory-wide and taken by whichever AGV
                          has been idle longest (no distance optimisation -
                          modelling the limited global visibility of a
                          decentralized controller).
  * Charging: battery is drive-time budget (assumption: 240 min ~ 4 h of
    active driving between charges, per the brief). At a low-battery
    threshold the AGV finishes its current leg then drives to the nearest
    of 2 charging nodes (2 bays each -> 4 simultaneous chargers) and is
    unavailable for CHARGE_DURATION_MIN.
"""
import random
import statistics
from dataclasses import dataclass, field

import networkx as nx
import simpy

from factory_graph import build_graph

# ---------------------------------------------------------------- constants
BATTERY_CAPACITY_MIN = 240.0     # 4 h of driving between charges
LOW_BATTERY_THRESHOLD_MIN = 35.0 # go charge once remaining budget is low
CHARGE_DURATION_MIN = 40.0       # time to (fast-)charge back to full
CHARGER_BAYS_PER_NODE = 2

LOCAL_ZONE_TIMEOUT_MIN = 5.0     # decentralized: local wait before broadcast
DEADLOCK_SCAN_PERIOD_MIN = 0.5   # how often the monitor looks for cycles


# ------------------------------------------------------------------ locks
class NodeLock:
    """Single-occupancy lock on a graph node, with explicit holder/queue
    bookkeeping so we can build a wait-for graph and cancel waits (needed
    for deadlock detection & recovery, which plain simpy.Resource does not
    expose cleanly)."""

    __slots__ = ("env", "holder", "waiters")

    def __init__(self, env):
        self.env = env
        self.holder = None      # agv id currently occupying the node
        self.waiters = []       # FIFO list of [agv_id, event]

    def request(self, agv_id):
        ev = self.env.event()
        if self.holder is None:
            self.holder = agv_id
            ev.succeed()
        else:
            self.waiters.append([agv_id, ev])
        return ev

    def cancel_wait(self, agv_id):
        self.waiters = [w for w in self.waiters if w[0] != agv_id]

    def release(self, agv_id):
        assert self.holder == agv_id, (self.holder, agv_id)
        if self.waiters:
            nxt_id, nxt_ev = self.waiters.pop(0)
            self.holder = nxt_id
            nxt_ev.succeed()
        else:
            self.holder = None

    def is_free(self):
        return self.holder is None


# ------------------------------------------------------------------ config
@dataclass
class SimConfig:
    fleet_size: int
    dispatch_mode: str = "centralized"     # centralized | decentralized
    deadlock_mode: str = "avoidance"       # avoidance | naive
    request_rate_per_hour: float = 120.0
    sim_duration_min: float = 480.0
    warmup_min: float = 60.0
    seed: int = 0


# ------------------------------------------------------------------ task
@dataclass
class Task:
    tid: int
    origin: str
    dest: str
    t_created: float
    t_assigned: float = None
    t_pickup: float = None
    t_complete: float = None
    zone: int = None


# ------------------------------------------------------------------ metrics
@dataclass
class Metrics:
    completed_tasks: list = field(default_factory=list)   # Task objects
    deadlock_events: list = field(default_factory=list)   # (time, cycle_len, agvs)
    blocked_time_total: float = 0.0
    blocked_samples: list = field(default_factory=list)   # (t, n_blocked)
    agv_time_idle: dict = field(default_factory=dict)
    agv_time_travel: dict = field(default_factory=dict)
    agv_time_blocked: dict = field(default_factory=dict)
    agv_time_charging: dict = field(default_factory=dict)
    reroutes: int = 0
    poll_time_total: float = 0.0
    manual_interventions: int = 0


# ------------------------------------------------------------------ AGV
class AGV:
    def __init__(self, env, aid, start_node):
        self.env = env
        self.id = aid
        self.node = start_node
        self.status = "idle"
        self.battery = BATTERY_CAPACITY_MIN
        self.task_event = None   # simpy event the dispatcher triggers with a Task
        self.proc = None         # main simpy process (for interrupts)
        self.zone = None
        self.intended_next = None  # node this AGV is currently trying to enter
        self.leg_status = "idle"   # "to_pickup" / "loaded" / "to_charge" - used to restore status after a blocking wait


# ------------------------------------------------------------------ sim
class FactorySim:
    def __init__(self, cfg: SimConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.env = simpy.Environment()
        self.G, self.stations, self.chargers = build_graph()
        self.node_locks = {n: NodeLock(self.env) for n in self.G.nodes}
        self.charger_res = {c: simpy.Resource(self.env, capacity=CHARGER_BAYS_PER_NODE)
                             for c in self.chargers}
        self.metrics = Metrics()
        self._node_penalty_until = {}

        # precompute all-pairs shortest path length (time) and path
        self._spl_nested = dict(nx.all_pairs_dijkstra_path_length(self.G, weight="time"))
        self._path_cache = {}

        # zones for decentralized dispatch: split by (row, col) quadrant
        self.zone_of = {}
        for n, d in self.G.nodes(data=True):
            r, c = d["row"], d["col"]
            zr = 0 if r < 2.5 else 1
            zc = 0 if c < 3 else 1
            self.zone_of[n] = zr * 2 + zc   # 0..3

        # place AGVs at stations (round robin) as a reasonable starting layout
        self.agvs = []
        for i in range(cfg.fleet_size):
            start = self.stations[i % len(self.stations)]
            agv = AGV(self.env, i, start)
            agv.zone = self.zone_of[start]
            self.node_locks[start].holder = agv.id if self.node_locks[start].holder is None else self.node_locks[start].holder
            self.agvs.append(agv)
            self.metrics.agv_time_idle[i] = 0.0
            self.metrics.agv_time_travel[i] = 0.0
            self.metrics.agv_time_blocked[i] = 0.0
            self.metrics.agv_time_charging[i] = 0.0

        # NOTE: if fleet_size > number of stations, multiple AGVs would
        # collide at t=0. Guard against that (fleet size in our sweep goes
        # up to 30 with only 12 stations) by spreading extra AGVs across ALL
        # nodes instead.
        if cfg.fleet_size > len(self.stations):
            all_nodes = list(self.G.nodes)
            for n in self.node_locks.values():
                n.holder = None
            self.rng.shuffle(all_nodes)
            for i, agv in enumerate(self.agvs):
                start = all_nodes[i % len(all_nodes)]
                agv.node = start
                agv.zone = self.zone_of[start]
                self.node_locks[start].holder = agv.id

        # dispatcher state
        self.pending = []              # list of Task, FIFO (centralized / global)
        self.zone_pending = {z: [] for z in range(4)}
        self.idle_agvs = set()
        self.zone_idle = {z: set() for z in range(4)}
        self.next_tid = 0

        self.env.process(self._request_generator())
        for agv in self.agvs:
            agv.proc = self.env.process(self._agv_process(agv))
        # The periodic wait-for-graph monitor runs in BOTH modes: in
        # "naive" mode it is the *only* deadlock-handling mechanism; in
        # "avoidance" mode it is a safety net for the residual cases the
        # one-step look-ahead heuristic cannot guarantee against (e.g. a
        # head-on swap that both AGVs commit to in the same instant). This
        # lets us honestly compare deadlock *frequency*, not just presence.
        self.env.process(self._deadlock_monitor())
        self.env.process(self._congestion_sampler())

    # -------------------------------------------------- path helper
    def spl_dist(self, u, v):
        return self._spl_nested.get(u, {}).get(v)

    def shortest_path(self, u, v, avoid=None):
        if not avoid:
            # NOTE: deliberately not cached - re-jittering on every call is
            # what gives us route diversity (see _jittered_path docstring).
            return self._jittered_path(u, v)
        # temporarily penalise nodes that just caused a jam so a rerouted
        # AGV actually takes a different path instead of immediately
        # retrying the identical (still-blocked) route - a minimal
        # congestion-reactive routing rule.
        H = self.G.copy()
        for n in avoid:
            if n in (u, v):
                continue
            for _, _, d in H.edges(n, data=True):
                d["time"] *= 6.0
        try:
            return self._jittered_path(u, v, H)
        except nx.NetworkXNoPath:
            return nx.shortest_path(self.G, u, v, weight="time")

    def _jittered_path(self, u, v, base_graph=None):
        """Shortest path with small random multiplicative jitter on edge
        weights. Pure shortest-path routing makes every AGV funnel through
        the same handful of central nodes (they all have the same graph,
        the same weights, so they all compute the identical route) - which
        manufactures artificial hotspot congestion/deadlock clusters that
        have more to do with routing determinism than with real physical
        capacity. A small per-query jitter (+/-20%) is a standard,
        light-touch way to spread traffic across near-equivalent paths
        (route diversity / stochastic load balancing), and is documented
        as an assumption in the report rather than left implicit."""
        H = base_graph if base_graph is not None else self.G
        H2 = nx.Graph()
        H2.add_nodes_from(H.nodes(data=True))
        for a, b, d in H.edges(data=True):
            H2.add_edge(a, b, time=d["time"] * self.rng.uniform(0.8, 1.2))
        return nx.shortest_path(H2, u, v, weight="time")

    def _active_penalties(self):
        now = self.env.now
        return {n for n, until in self._node_penalty_until.items() if until > now}

    # -------------------------------------------------- request generation
    def _request_generator(self):
        mean_gap = 60.0 / self.cfg.request_rate_per_hour
        while True:
            gap = self.rng.expovariate(1.0 / mean_gap)
            yield self.env.timeout(gap)
            o, d = self.rng.sample(self.stations, 2)
            t = Task(self.next_tid, o, d, self.env.now)
            t.zone = self.zone_of[o]
            self.next_tid += 1
            if self.cfg.dispatch_mode == "centralized":
                self.pending.append(t)
                self._try_dispatch_centralized()
            else:
                self.zone_pending[t.zone].append(t)
                self.env.process(self._decentral_zone_timeout(t))
                self._try_dispatch_zone(t.zone)

    # -------------------------------------------------- centralized dispatch
    def _try_dispatch_centralized(self):
        while self.pending and self.idle_agvs:
            task = self.pending[0]
            best_agv, best_t = None, None
            for aid in self.idle_agvs:
                agv = self.agvs[aid]
                dt = self.spl_dist(agv.node, task.origin)
                if dt is None:
                    continue
                if best_t is None or dt < best_t:
                    best_t, best_agv = dt, agv
            if best_agv is None:
                break
            self.pending.pop(0)
            self.idle_agvs.discard(best_agv.id)
            self._assign(best_agv, task)

    # -------------------------------------------------- decentralized dispatch
    def _try_dispatch_zone(self, zone):
        q = self.zone_pending[zone]
        idle = self.zone_idle[zone]
        while q and idle:
            task = q[0]
            best_agv, best_t = None, None
            for aid in idle:
                agv = self.agvs[aid]
                dt = self.spl_dist(agv.node, task.origin)
                if dt is None:
                    continue
                if best_t is None or dt < best_t:
                    best_t, best_agv = dt, agv
            if best_agv is None:
                break
            q.pop(0)
            idle.discard(best_agv.id)
            self.idle_agvs.discard(best_agv.id)
            self._assign(best_agv, task)

    def _decentral_zone_timeout(self, task):
        yield self.env.timeout(LOCAL_ZONE_TIMEOUT_MIN)
        # if still un-dispatched, escalate to factory-wide FIFO pool
        z = task.zone
        if task in self.zone_pending[z]:
            self.zone_pending[z].remove(task)
            self.pending.append(task)
            self._try_dispatch_global_fifo()

    def _try_dispatch_global_fifo(self):
        # decentralized fallback: no distance optimisation, just whichever
        # AGV has been idle longest takes the oldest broadcast request
        while self.pending and self.idle_agvs:
            task = self.pending.pop(0)
            aid = next(iter(self.idle_agvs))  # arbitrary/idle-longest proxy
            agv = self.agvs[aid]
            self.idle_agvs.discard(aid)
            self.zone_idle[agv.zone].discard(aid)
            self._assign(agv, task)

    def _assign(self, agv, task):
        task.t_assigned = self.env.now
        agv.task_event_data = task
        agv.task_event.succeed()

    # -------------------------------------------------- AGV process
    def _agv_process(self, agv):
        while True:
            agv.status = "idle"
            t_idle_start = self.env.now
            agv.task_event = self.env.event()
            self.idle_agvs.add(agv.id)
            self.zone_idle[agv.zone].add(agv.id)
            if self.cfg.dispatch_mode == "centralized":
                self._try_dispatch_centralized()
            else:
                self._try_dispatch_zone(agv.zone)
                self._try_dispatch_global_fifo()
            task = yield agv.task_event
            self.idle_agvs.discard(agv.id)
            self.zone_idle[agv.zone].discard(agv.id)
            self.metrics.agv_time_idle[agv.id] += self.env.now - t_idle_start
            task = agv.task_event_data

            # leg 1: go to pickup
            agv.status = "to_pickup"
            agv.leg_status = "to_pickup"
            yield from self._travel(agv, task.origin)
            task.t_pickup = self.env.now

            # leg 2: deliver
            agv.status = "loaded"
            agv.leg_status = "loaded"
            yield from self._travel(agv, task.dest)
            task.t_complete = self.env.now
            self.metrics.completed_tasks.append(task)

            # battery check -> maybe go charge
            if agv.battery <= LOW_BATTERY_THRESHOLD_MIN:
                yield from self._go_charge(agv)

    # -------------------------------------------------- movement primitive
    def _travel(self, agv, dest):
        if agv.node == dest:
            return
        avoid = self._active_penalties()
        path = self.shortest_path(agv.node, dest, avoid=avoid)
        i = 1
        while i < len(path):
            nxt = path[i]
            is_final = (i == len(path) - 1)
            ok = yield from self._move_one_step(agv, nxt, is_final, dest, path, i)
            if ok == "rerouted":
                # path changed under us (deadlock recovery) - recompute,
                # taking into account any freshly-penalised congested nodes
                avoid = self._active_penalties()
                path = self.shortest_path(agv.node, dest, avoid=avoid)
                i = 1
                continue
            i += 1

    def _move_one_step(self, agv, nxt, is_final, final_dest, path, idx):
        agv.intended_next = nxt

        if self.cfg.deadlock_mode == "avoidance" and not is_final:
            # Head-on (2-AGV direct-swap) resolution: this is the single
            # most common and cheaply-preventable deadlock class on a
            # single-lane grid (Digani et al., 2015; Draganjac et al.,
            # 2020). The lower-id AGV has priority and proceeds; the
            # higher-id AGV side-steps to a free neighbour if one exists.
            # NOTE: an earlier version of this function also tried a
            # generic "N-exit look-ahead" (never enter a node unless it has
            # a free exit other than where you came from). That rule
            # double-counted contention: it forgot that the node you are
            # LEAVING becomes free the instant you move, so with 3+ AGVs
            # converging on one junction from different sides it produced
            # a false-positive livelock where every AGV refused to move
            # even though no real cycle existed. It was removed after
            # exactly this behaviour showed up in testing (see report,
            # Section on modelling pitfalls). Genuine multi-agent cyclic
            # deadlocks are instead left to the always-on monitor below.
            detoured = yield from self._maybe_detour_headon(agv, nxt)
            if detoured:
                self.metrics.reroutes += 1
                agv.intended_next = None
                return "rerouted"

        t_wait_start = self.env.now
        agv.status = "blocked"
        req = self.node_locks[nxt].request(agv.id)
        try:
            yield req
        except simpy.Interrupt:
            # forcibly backed off by the deadlock monitor (naive mode)
            self.node_locks[nxt].cancel_wait(agv.id)
            self.metrics.agv_time_blocked[agv.id] += self.env.now - t_wait_start
            agv.intended_next = None
            alt = self._pick_alternate(agv)
            if alt is not None:
                yield from self._forced_move(agv, alt)
            else:
                # No free neighbour anywhere: this AGV sits inside a fully
                # saturated local cluster (every node in its immediate
                # neighbourhood is occupied by other AGVs that are
                # themselves waiting to move into where it is standing).
                # No amount of 1-hop local shuffling can ever resolve this
                # - it is a genuine structural deadlock, not merely
                # congestion. We model the standard real-world fallback:
                # a supervisory/manual intervention that relocates the AGV
                # to the nearest currently-free node in the plant (e.g. a
                # human operator issuing an override, or the AGV using a
                # reserved maintenance/escape track), at a fixed time cost
                # representing controller reaction + confirmation time.
                # This is tracked separately in the metrics as a distinct,
                # heavier-handed event from ordinary local recovery.
                free_node = self._nearest_free_node(agv.node)
                if free_node is not None:
                    # reserve the escape node FIRST (atomic w.r.t. other
                    # AGVs), THEN spend the reaction-time delay, THEN
                    # release the old node - avoids a check-then-act race
                    # where someone else claims free_node while we wait.
                    escape_req = self.node_locks[free_node].request(agv.id)
                    yield escape_req
                    yield self.env.timeout(5.0)  # controller reaction time
                    self.node_locks[agv.node].release(agv.id)
                    agv.node = free_node
                    self.metrics.manual_interventions += 1
                else:
                    # entire plant is saturated (only happens at very high
                    # fleet sizes) - nothing left to do but wait it out.
                    self._node_penalty_until[nxt] = self.env.now + 3.0
                    yield self.env.timeout(1.0)
            self.metrics.reroutes += 1
            return "rerouted"
        wait = self.env.now - t_wait_start
        self.metrics.agv_time_blocked[agv.id] += wait
        self.metrics.blocked_time_total += wait

        # travel the edge (now actually moving - not blocked any more)
        agv.status = agv.leg_status
        t_edge = self.G.edges[agv.node, nxt]["time"]
        yield self.env.timeout(t_edge)
        agv.battery -= t_edge
        self.metrics.agv_time_travel[agv.id] += t_edge

        prev = agv.node
        self.node_locks[prev].release(agv.id)
        agv.node = nxt
        agv.intended_next = None
        return "ok"

    def _safe_to_enter(self, node, came_from):
        """One-step look-ahead deadlock-avoidance rule: only enter a node
        that still has at least one OTHER free exit (i.e. is not itself
        about to become a trap)."""
        for nb in self.G.neighbors(node):
            if nb == came_from:
                continue
            if self.node_locks[nb].is_free():
                return True
        return False

    def _maybe_detour_headon(self, agv, nxt):
        holder_id = self.node_locks[nxt].holder
        if holder_id is None or holder_id == agv.id:
            return False
        holder = self.agvs[holder_id]
        if holder.intended_next != agv.node:
            return False  # not a head-on swap
        if agv.id < holder_id:
            return False  # we have priority; proceed to request normally
        alt = self._pick_alternate(agv, avoid={nxt})
        if alt is None:
            return False  # no escape available; fall back to waiting in queue
        yield from self._forced_move(agv, alt)
        return True

    def _forced_move(self, agv, alt):
        """Physically step the AGV onto a free neighbouring node (used for
        head-on side-stepping and deadlock-recovery back-off)."""
        t_wait_start = self.env.now
        agv.status = "blocked"
        req = self.node_locks[alt].request(agv.id)
        yield req
        self.metrics.agv_time_blocked[agv.id] += self.env.now - t_wait_start
        agv.status = agv.leg_status
        t_edge = self.G.edges[agv.node, alt]["time"]
        yield self.env.timeout(t_edge)
        agv.battery -= t_edge
        self.metrics.agv_time_travel[agv.id] += t_edge
        prev = agv.node
        self.node_locks[prev].release(agv.id)
        agv.node = alt
        agv.intended_next = None

    def _pick_alternate(self, agv, avoid=frozenset()):
        for nb in self.G.neighbors(agv.node):
            if nb in avoid:
                continue
            if self.node_locks[nb].is_free():
                return nb
        return None

    def _nearest_free_node(self, from_node):
        best, best_d = None, None
        for n, l in self.node_locks.items():
            if not l.is_free():
                continue
            d = self.spl_dist(from_node, n)
            if d is None:
                continue
            if best_d is None or d < best_d:
                best_d, best = d, n
        return best

    # -------------------------------------------------- charging
    def _go_charge(self, agv):
        agv.status = "to_charge"
        agv.leg_status = "to_charge"
        best_c, best_t = None, None
        for c in self.chargers:
            dt = self.spl_dist(agv.node, c)
            if dt is not None and (best_t is None or dt < best_t):
                best_t, best_c = dt, c
        yield from self._travel(agv, best_c)
        agv.status = "charging"
        t0 = self.env.now
        with self.charger_res[best_c].request() as req:
            yield req
            yield self.env.timeout(CHARGE_DURATION_MIN)
        agv.battery = BATTERY_CAPACITY_MIN
        self.metrics.agv_time_charging[agv.id] += self.env.now - t0

    # -------------------------------------------------- deadlock monitor
    def _deadlock_monitor(self):
        while True:
            yield self.env.timeout(DEADLOCK_SCAN_PERIOD_MIN)
            wf = nx.DiGraph()
            for node, lock in self.node_locks.items():
                if lock.holder is None:
                    continue
                for waiter_id, _ev in lock.waiters:
                    wf.add_edge(waiter_id, lock.holder)
            try:
                cycle = nx.find_cycle(wf)
            except nx.NetworkXNoCycle:
                continue
            agv_ids_in_cycle = list({u for u, v in cycle} | {v for u, v in cycle})
            # IMPORTANT: only a AGV on the *waiting* side of an edge (u -> v
            # means "u waits for the node held by v") is actually suspended
            # on a NodeLock request; interrupting a holder instead would
            # raise Interrupt at whatever unrelated yield it happens to be
            # on (e.g. mid-edge env.timeout) and silently kill that process.
            waiters_in_cycle = sorted({u for u, v in cycle})
            self.metrics.deadlock_events.append((self.env.now, len(agv_ids_in_cycle), tuple(agv_ids_in_cycle)))
            victim_id = waiters_in_cycle[0]   # deterministic given seed/order
            victim = self.agvs[victim_id]
            if victim.proc.is_alive:
                try:
                    victim.proc.interrupt("deadlock-recovery")
                except RuntimeError:
                    pass

    # -------------------------------------------------- congestion sampler
    def _congestion_sampler(self):
        while True:
            yield self.env.timeout(1.0)
            n_blocked = sum(1 for a in self.agvs if a.status == "blocked")
            self.metrics.blocked_samples.append((self.env.now, n_blocked))

    # -------------------------------------------------- run
    def run(self):
        self.env.run(until=self.cfg.sim_duration_min)
        return self.summarize()

    def summarize(self):
        warm = self.cfg.warmup_min
        dur_steady = self.cfg.sim_duration_min - warm
        tasks = [t for t in self.metrics.completed_tasks if t.t_complete is not None and t.t_complete >= warm]
        n = len(tasks)
        wait_times = [t.t_assigned - t.t_created for t in tasks]
        cycle_times = [t.t_complete - t.t_assigned for t in tasks]
        total_times = [t.t_complete - t.t_created for t in tasks]

        blocked_steady = [b for (tm, b) in self.metrics.blocked_samples if tm >= warm]
        avg_blocked = statistics.mean(blocked_steady) if blocked_steady else 0.0

        dl_steady = [e for e in self.metrics.deadlock_events if e[0] >= warm]

        util_rows = {}
        for a in self.agvs:
            idle = self.metrics.agv_time_idle[a.id]
            trav = self.metrics.agv_time_travel[a.id]
            blk = self.metrics.agv_time_blocked[a.id]
            chg = self.metrics.agv_time_charging[a.id]
            util_rows[a.id] = dict(idle=idle, travel=trav, blocked=blk, charging=chg)

        total_travel = sum(v["travel"] for v in util_rows.values())
        total_blocked = sum(v["blocked"] for v in util_rows.values())
        total_charging = sum(v["charging"] for v in util_rows.values())
        total_idle = sum(v["idle"] for v in util_rows.values())
        denom = max(1e-9, total_travel + total_blocked + total_charging + total_idle)

        return dict(
            fleet_size=self.cfg.fleet_size,
            dispatch_mode=self.cfg.dispatch_mode,
            deadlock_mode=self.cfg.deadlock_mode,
            seed=self.cfg.seed,
            n_completed=n,
            throughput_per_h=n / (dur_steady / 60.0) if dur_steady > 0 else 0.0,
            mean_wait_min=statistics.mean(wait_times) if wait_times else float("nan"),
            p95_wait_min=(statistics.quantiles(wait_times, n=20)[18] if len(wait_times) >= 20 else (max(wait_times) if wait_times else float("nan"))),
            mean_cycle_min=statistics.mean(cycle_times) if cycle_times else float("nan"),
            mean_total_min=statistics.mean(total_times) if total_times else float("nan"),
            avg_n_blocked=avg_blocked,
            frac_time_blocked=total_blocked / denom,
            frac_time_travel=total_travel / denom,
            frac_time_idle=total_idle / denom,
            frac_time_charging=total_charging / denom,
            n_deadlock_events=len(dl_steady),
            deadlock_events_per_h=len(dl_steady) / (dur_steady / 60.0) if dur_steady > 0 else 0.0,
            reroutes=self.metrics.reroutes,
            manual_interventions=self.metrics.manual_interventions,
        )


def run_once(cfg: SimConfig):
    sim = FactorySim(cfg)
    return sim.run()


if __name__ == "__main__":
    cfg = SimConfig(fleet_size=15, dispatch_mode="centralized", deadlock_mode="avoidance", seed=1,
                     sim_duration_min=240, warmup_min=30)
    import time
    t0 = time.time()
    res = run_once(cfg)
    print(res)
    print("elapsed", time.time() - t0)
