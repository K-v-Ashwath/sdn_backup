"""Run with POX root on PYTHONPATH; validates graph and OF message encoding, no switches."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pox.core
pox.core.initialize()
import pox.openflow
pox.openflow.launch()
import backup_controller as b
class Conn:
    def send(self,message): message.pack()
r=b.Router('dynamic'); r.connections={i:Conn() for i in range(1,5)}
assert r.path(1,2)==[(1,3)]
r.down={(1,3)}
assert r.path(1,2)==[(1,4),(3,2),(4,3)]
r.install()
r.down={(1,3),(1,4)}
assert r.path(1,2) is None
r.down=set(); assert r.path(1,2)==[(1,3)]
# Congestion on both links of the nominally-shortest branch must shift Dijkstra to s1-s3-s4-s2.
r.link_utilization[r._edge_key(1,3,2,2)]=0.95
assert r.path(1,2)==[(1,4),(3,2),(4,3)], r.path(1,2)
# Removing congestion restores the lower-cost primary path.
r.link_utilization.clear(); assert r.path(1,2)==[(1,3)]
static=b.Router('static'); static.connections={i:Conn() for i in range(1,5)}
static.link_utilization[static._edge_key(1,3,2,2)]=0.99
assert static.path(1,2)==[(1,3)]
# install() must replace rules in place: no table-wide DELETE (it would leave a window with no route).
import pox.openflow.libopenflow_01 as of
class Rec:
    def __init__(self): self.sent=[]
    def send(self,m): m.pack(); self.sent.append(m)
rr=b.Router('dynamic'); rr.connections={i:Rec() for i in range(1,5)}
rr.install(); rr.down={(1,3),(2,2)}; rr.install()
for c_ in rr.connections.values():
    assert not any(getattr(m,'command',None)==of.OFPFC_DELETE for m in c_.sent), 'install() must not wipe the table'
assert any(getattr(m,'command',None)==of.OFPFC_ADD for m in rr.connections[1].sent)
# Hysteresis: a busy primary path alone must not flap the flow; a failed path is left immediately.
h=b.Router('dynamic'); h.connections={i:Rec() for i in range(1,5)}; h.install()
primary=h.last_paths['serverA']; assert primary==(1,2)
h.link_utilization[h._edge_key(1,3,2,2)]=0.95
new=h._current_paths(); assert new['serverA']!=primary
assert not h._should_switch(new), 'must wait for the hold-down timer'
h.last_change-=b.HOLD_DOWN_SECONDS+1; assert h._should_switch(new)
h.link_utilization.clear(); h.last_change=b.time.time(); h.down={(1,3),(2,2)}
assert h._should_switch(h._current_paths()), 'failed path must be abandoned immediately'
print('PASS: primary/alternate/failure recovery and load-aware route switching; in-place rule replacement; hysteresis; OpenFlow message encoding')
print('This is not a live Mininet integration test.')
