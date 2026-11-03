"""POX component: topology-aware, failure-aware and load-aware routing.

Link cost combines configured base cost, configured propagation delay and
measured OpenFlow port utilisation. Utilisation is sampled every 2 seconds.
"""
import heapq
import json
import time
from pathlib import Path
from pox.core import core
from pox.lib.recoco import Timer
import pox.openflow.libopenflow_01 as of
from pox.lib.addresses import IPAddr, EthAddr
from pox.lib.packet.ethernet import ethernet
from pox.lib.packet.arp import arp

# (switch, port, switch, port, base_cost, configured_delay_ms, capacity_mbps)
# Port mapping and delay/capacity match topology.py.
EDGES = [
    (1, 3, 2, 2, 1.0, 5.0, 10.0),
    (1, 4, 3, 1, 2.0, 10.0, 10.0),
    (2, 3, 4, 3, 1.0, 5.0, 10.0),
    (3, 2, 4, 4, 2.0, 10.0, 10.0),
]
HOSTS = {
    '10.0.0.1': (1, 1, 1), '10.0.0.2': (1, 2, 2),
    '10.0.0.3': (2, 1, 3), '10.0.0.4': (4, 1, 4),
}
STATS_INTERVAL = 2.0
# Hysteresis for load-aware re-routing. A bulk transfer fills its own path, which makes that
# path look expensive; without damping the flow would be bounced between the two paths every
# few seconds and TCP would keep stalling. A *healthy* path is only abandoned when the new
# one is clearly cheaper and the last change is old enough. A failed path is left at once.
SWITCH_RATIO = 0.6        # new path cost must be <= 60% of the current path cost
HOLD_DOWN_SECONDS = 20.0  # minimum time between two load-driven path changes
UTIL_SMOOTHING = 0.5      # exponential moving average weight of the newest utilisation sample


class Router:
    def __init__(self, mode):
        self.mode = mode
        self.connections = {}
        self.down = set()
        self.port_counters = {}       # (dpid, port) -> (tx_bytes, rx_bytes, sample_time)
        self.port_rates = {}          # (dpid, port) -> tx bytes/sec
        self.link_utilization = {}   # canonical edge -> fraction [0, 1+]
        self.last_paths = {}
        self.last_change = 0.0
        core.openflow.addListeners(self)
        self.stats_timer = Timer(STATS_INTERVAL, self._poll_stats, recurring=True)

    @staticmethod
    def _edge_key(a, ap, b, bp):
        return tuple(sorted(((a, ap), (b, bp))))

    def _link_cost(self, edge):
        a, ap, b, bp, base, delay_ms, capacity_mbps = edge
        if self.mode == 'static':
            return base
        util = self.link_utilization.get(self._edge_key(a, ap, b, bp), 0.0)
        # Delay is the configured TCLink propagation delay, not a live ping RTT.
        # Congestion penalty rises non-linearly so lightly loaded links stay stable.
        delay_component = delay_ms / 5.0
        congestion_component = 12.0 * (util ** 2)
        return base + delay_component + congestion_component

    def path(self, src, dst):
        queue = [(0.0, src, [])]
        best = {}
        while queue:
            cost, node, ports = heapq.heappop(queue)
            if node == dst:
                return ports
            if node in best and cost >= best[node]:
                continue
            best[node] = cost
            for edge in EDGES:
                a, ap, b, bp = edge[:4]
                if (a, ap) in self.down or (b, bp) in self.down:
                    continue
                weight = self._link_cost(edge)
                if node == a and b in self.connections:
                    heapq.heappush(queue, (cost + weight, b, ports + [(a, ap)]))
                elif node == b and a in self.connections:
                    heapq.heappush(queue, (cost + weight, a, ports + [(b, bp)]))
        return None

    def _path_nodes(self, src, ports):
        nodes = [src]
        current = src
        for _, out_port in ports:
            nxt = None
            for edge in EDGES:
                a, ap, b, bp = edge[:4]
                if current == a and out_port == ap:
                    nxt = b
                    break
                if current == b and out_port == bp:
                    nxt = a
                    break
            if nxt is None:
                break
            nodes.append(nxt)
            current = nxt
        return nodes

    def _route_snapshot(self, src, dst):
        ports = self.path(src, dst)
        if ports is None:
            return {'available': False, 'switches': [], 'cost': None, 'links': []}
        nodes = self._path_nodes(src, ports)
        total = 0.0
        links = []
        for i in range(len(nodes) - 1):
            a, b = nodes[i], nodes[i + 1]
            edge = next(e for e in EDGES if {e[0], e[2]} == {a, b})
            util = self.link_utilization.get(self._edge_key(*edge[:4]), 0.0)
            cost = self._link_cost(edge)
            total += cost
            links.append({'from': 's%d' % a, 'to': 's%d' % b,
                          'cost': round(cost, 3), 'utilization_percent': round(util * 100, 2),
                          'configured_delay_ms': edge[5]})
        return {'available': True, 'switches': ['s%d' % n for n in nodes],
                'cost': round(total, 3), 'links': links}

    def _publish_routes(self, log=False):
        routes = {'serverA': self._route_snapshot(1, 2), 'serverB': self._route_snapshot(1, 4)}
        payload = {
            'mode': self.mode,
            'down_ports': sorted([list(x) for x in self.down]),
            'routes': routes,
            'link_metrics': self._all_link_metrics(),
            'stats_interval_seconds': STATS_INTERVAL,
            'cost_model': ('fixed base cost (static mode)' if self.mode == 'static' else 'base_cost + configured_delay_ms/5 + 12*(utilization_fraction^2)'),
        }
        try:
            out = Path('results/webui')
            out.mkdir(parents=True, exist_ok=True)
            tmp = out / 'routes.json.tmp'
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(out / 'routes.json')
        except Exception as exc:
            core.getLogger().warning('Could not publish route state: %s', exc)
        if log:
            core.getLogger().info('ROUTES mode=%s down=%s serverA=%s serverB=%s', self.mode, sorted(self.down), routes['serverA']['switches'], routes['serverB']['switches'])
        return routes

    def _all_link_metrics(self):
        result = []
        for edge in EDGES:
            a, ap, b, bp, base, delay, capacity = edge
            util = self.link_utilization.get(self._edge_key(a, ap, b, bp), 0.0)
            result.append({'link': 's%d-s%d' % (a, b), 'a': [a, ap], 'b': [b, bp],
                           'base_cost': base, 'configured_delay_ms': delay,
                           'capacity_mbps': capacity, 'utilization_percent': round(util * 100, 2),
                           'dynamic_cost': round(self._link_cost(edge), 3),
                           'up': (a, ap) not in self.down and (b, bp) not in self.down})
        return result

    def _current_paths(self):
        paths = {}
        for name, dst in (('serverA', 2), ('serverB', 4)):
            ports = self.path(1, dst)
            paths[name] = tuple(self._path_nodes(1, ports)) if ports is not None else None
        return paths

    def _nodes_cost(self, nodes):
        """Cost of a switch path under the *current* link costs; None if it is no longer usable."""
        if nodes is None or any(n not in self.connections for n in nodes):
            return None
        total = 0.0
        for a, b in zip(nodes, nodes[1:]):
            edge = next((e for e in EDGES if {e[0], e[2]} == {a, b}), None)
            if edge is None or (edge[0], edge[1]) in self.down or (edge[2], edge[3]) in self.down:
                return None
            total += self._link_cost(edge)
        return total

    def _should_switch(self, new_paths):
        for name, new in new_paths.items():
            old = self.last_paths.get(name)
            if old == new:
                continue
            old_cost, new_cost = self._nodes_cost(old), self._nodes_cost(new)
            if old_cost is None or new_cost is None:
                return True               # current path is broken or there is no path any more
            if new_cost <= old_cost * SWITCH_RATIO and time.time() - self.last_change >= HOLD_DOWN_SECONDS:
                return True
        return False

    def _clear(self, conn):
        conn.send(of.ofp_flow_mod(command=of.OFPFC_DELETE))

    def install(self):
        """(Re)write the routing rules on every connected switch.

        Rules are *replaced in place* (OFPFC_ADD overwrites an identical match) instead of
        deleting the whole table first, so there is never an instant where a switch has no
        route and drops the traffic of a transfer that is being re-routed.
        """
        for sw, conn in list(self.connections.items()):
            for ip, (dest, hostport, _) in HOSTS.items():
                match = of.ofp_match(dl_type=0x800, nw_dst=IPAddr(ip))
                route = self.path(sw, dest)
                if route is None:
                    conn.send(of.ofp_flow_mod(command=of.OFPFC_DELETE_STRICT, priority=100, match=match))
                    continue
                port = hostport if sw == dest else route[0][1]
                flow = of.ofp_flow_mod(priority=100, match=match)
                flow.actions.append(of.ofp_action_output(port=port))
                conn.send(flow)
            conn.send(of.ofp_barrier_request())
        self._publish_routes(log=True)
        paths = self._current_paths()
        if paths != self.last_paths:
            self.last_change = time.time()
        self.last_paths = paths

    def _poll_stats(self):
        if not self.connections:
            return
        for conn in list(self.connections.values()):
            try:
                conn.send(of.ofp_stats_request(body=of.ofp_port_stats_request()))
            except Exception as exc:
                core.getLogger().warning('Port stats request failed: %s', exc)

    def _handle_openflow_PortStatsReceived(self, event):
        now = time.time()
        for stat in event.stats:
            key = (event.connection.dpid, stat.port_no)
            previous = self.port_counters.get(key)
            self.port_counters[key] = (stat.tx_bytes, stat.rx_bytes, now)
            if previous:
                old_tx, old_rx, old_time = previous
                elapsed = max(now - old_time, 0.001)
                tx_rate = max(0, stat.tx_bytes - old_tx) / elapsed
                rx_rate = max(0, stat.rx_bytes - old_rx) / elapsed
                self.port_rates[key] = max(tx_rate, rx_rate)
        # Use the larger direction rate on either end of each physical link;
        # this avoids summing the same packets twice (TX at one end == RX at other).
        for a, ap, b, bp, base, delay, capacity in EDGES:
            rate = max(self.port_rates.get((a, ap), 0.0), self.port_rates.get((b, bp), 0.0))
            util = rate * 8.0 / (capacity * 1_000_000.0)
            util = min(max(util, 0.0), 1.5)
            key = self._edge_key(a, ap, b, bp)
            old = self.link_utilization.get(key, 0.0)
            self.link_utilization[key] = UTIL_SMOOTHING * util + (1.0 - UTIL_SMOOTHING) * old
        if self.mode == 'dynamic':
            new_paths = self._current_paths()
            if new_paths != self.last_paths and self._should_switch(new_paths):
                core.getLogger().info('LOAD-AWARE PATH CHANGE old=%s new=%s', self.last_paths, new_paths)
                self.install()
            else:
                self._publish_routes()
        else:
            self._publish_routes()

    def _handle_ConnectionUp(self, event):
        self.connections[event.dpid] = event.connection
        self._clear(event.connection)   # start from an empty table; later changes replace rules in place
        self.install()
        self._poll_stats()

    def _handle_ConnectionDown(self, event):
        self.connections.pop(event.dpid, None)
        self.port_counters = {k: v for k, v in self.port_counters.items() if k[0] != event.dpid}
        self.port_rates = {k: v for k, v in self.port_rates.items() if k[0] != event.dpid}
        core.getLogger().warning('SWITCH DOWN dpid=%s; recomputing routes', event.dpid)
        if self.mode == 'dynamic':
            self.install()

    def _handle_PortStatus(self, event):
        key = (event.dpid, event.ofp.desc.port_no)
        if not any(key in [(a, ap), (b, bp)] for a, ap, b, bp, *_ in EDGES):
            return
        failed = bool(event.ofp.desc.state & of.OFPPS_LINK_DOWN or event.ofp.desc.config & of.OFPPC_PORT_DOWN)
        if failed:
            self.down.add(key)
        else:
            self.down.discard(key)
        core.getLogger().info('LINK %s failed=%s', key, failed)
        if self.mode == 'dynamic':
            self.install()

    def _handle_PacketIn(self, event):
        request = event.parsed.find('arp')
        if not request or request.opcode != arp.REQUEST:
            return
        info = HOSTS.get(str(request.protodst))
        if not info:
            return
        mac = EthAddr('00:00:00:00:00:%02x' % info[2])
        reply = arp(); reply.opcode = arp.REPLY; reply.hwsrc = mac; reply.hwdst = request.hwsrc
        reply.protosrc = request.protodst; reply.protodst = request.protosrc
        frame = ethernet(type=ethernet.ARP_TYPE, src=mac, dst=request.hwsrc); frame.payload = reply
        out = of.ofp_packet_out(data=frame.pack())
        out.actions.append(of.ofp_action_output(port=event.port))
        event.connection.send(out)


def launch(mode='dynamic'):
    if mode not in ('static', 'dynamic'):
        raise ValueError('mode must be static or dynamic')
    core.registerNew(Router, mode)
