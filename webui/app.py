#!/usr/bin/env python3
"""Browser control plane for the CN Backup Project. Run with sudo python3 webui/app.py."""
import json, os, re, signal, subprocess, sys, threading, time
from pathlib import Path
from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent
UPLOADS = ROOT / 'webui' / 'uploads'
RUNTIME = ROOT / 'results' / 'webui'
UPLOADS.mkdir(parents=True, exist_ok=True); RUNTIME.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024
lock = threading.RLock()
netlock = threading.Lock()   # Mininet node.cmd() shares one shell per node: never run two at once
sample = {'latency': None, 'flows': {}}
state = {'running': False, 'starting': False, 'mode': 'dynamic', 'started_at': None,
         'controller': None, 'net': None, 'servers': {}, 'transfers': [], 'events': [], 'error': None, 'topology_links': [], 'switch_states': {}, 'link_states': {}, 'gen': 0}

def event(message, kind='info'):
    with lock:
        state['events'].insert(0, {'time': time.strftime('%H:%M:%S'), 'message': message, 'kind': kind})
        del state['events'][100:]

def sampler(gen):
    """Measure latency and flow counts in the background so /api/status never blocks on Mininet."""
    while True:
        with lock:
            net = state['net'] if (state['running'] and state['gen'] == gen) else None
        if net is None:
            sample['latency'] = None; sample['flows'] = {}
            return
        latency = None; flows = {}
        try:
            with netlock:
                raw = net.get('h1').cmd('ping -c 1 -W 1 10.0.0.3')
            m = re.search(r'time=([0-9.]+) ms', raw); latency = float(m.group(1)) if m else None
        except Exception: pass
        for sw in ('s1', 's2', 's3', 's4'):
            try:
                with netlock:
                    raw = net.get(sw).cmd('ovs-ofctl -O OpenFlow10 dump-flows ' + sw)
                flows[sw] = sum(1 for line in raw.splitlines() if 'actions=' in line and 'actions=CONTROLLER' not in line)
            except Exception: flows[sw] = 0
        sample['latency'] = latency; sample['flows'] = flows
        time.sleep(2)

def start_network(mode, gen):
    def cancelled():
        with lock: return state['gen'] != gen
    try:
        from mininet.net import Mininet
        from mininet.node import RemoteController, OVSSwitch
        from mininet.link import TCLink
        from mininet.log import setLogLevel
        setLogLevel('warning')
        event('Starting POX controller (' + mode + ' routing)')
        (RUNTIME / 'routes.json').unlink(missing_ok=True)   # never show routes from a previous run
        log = (RUNTIME / 'controller.log').open('a')
        ctrl = subprocess.Popen(['bash', str(ROOT/'run_controller.sh'), mode], cwd=ROOT,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        with lock: state['controller'] = ctrl
        time.sleep(2)
        if cancelled(): return
        if ctrl.poll() is not None: raise RuntimeError('POX controller exited; inspect results/webui/controller.log')
        net = Mininet(controller=None, switch=OVSSwitch, link=TCLink)
        with lock: state['net'] = net           # registered early so Stop can always clean it up
        net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)
        s = {i: net.addSwitch('s%d'%i, dpid='%016x'%i, protocols='OpenFlow10', failMode='secure') for i in range(1,5)}
        h = {i: net.addHost('h%d'%i, ip='10.0.0.%d/24'%i, mac='00:00:00:00:00:%02x'%i) for i in range(1,5)}
        for host, sw, port in [(1,1,1),(2,1,2),(3,2,1),(4,4,1)]: net.addLink(h[host],s[sw],port2=port)
        for x,xp,y,yp,delay in [(1,3,2,2,'5ms'),(1,4,3,1,'10ms'),(2,3,4,3,'5ms'),(3,2,4,4,'10ms')]:
            net.addLink(s[x],s[y],port1=xp,port2=yp,bw=10,delay=delay)
        net.start()
        if cancelled(): return
        # Keep the actual Mininet interface mapping for live per-link counters.
        link_map = []
        for link in net.links:
            a, b = link.intf1, link.intf2
            na, nb = a.node.name, b.node.name
            if na.startswith('s') or nb.startswith('s'):
                link_map.append({'a': na, 'b': nb, 'intf_a': a.name, 'intf_b': b.name})
        with lock:
            state['topology_links'] = link_map
            state['switch_states'] = {f's{i}': 'up' for i in range(1,5)}
            state['link_states'] = {edge['intf_a']+'__'+edge['intf_b']: 'up' for edge in link_map}
        if not net.waitConnected(timeout=15): raise RuntimeError('Switches did not connect to POX')
        time.sleep(2)
        if cancelled(): return
        with netlock:
            lost = net.pingAll()
        if lost > 0: raise RuntimeError('Mininet connectivity check failed; see controller log')
        for host, server_id in [(3,'A'),(4,'B')]:
            storage = RUNTIME / ('storage'+server_id); storage.mkdir(parents=True, exist_ok=True)
            proc = net.get('h%d'%host).popen([sys.executable, '-u', str(ROOT/'server.py'), '--host','0.0.0.0','--port','9000','--root',str(storage)],
                                            stdout=(RUNTIME/('server'+server_id+'.log')).open('a'), stderr=subprocess.STDOUT)
            with lock: state['servers'][server_id] = proc
        time.sleep(1)
        if cancelled(): return
        if any(p.poll() is not None for p in state['servers'].values()): raise RuntimeError('A backup server failed to start')
        with lock:
            state['running'] = True; state['starting'] = False; state['started_at'] = time.time(); state['error'] = None
        threading.Thread(target=sampler, args=(gen,), daemon=True).start()
        event('Network online: 4 switches, 2 clients, 2 backup servers', 'success')
    except Exception as exc:
        if cancelled(): return
        with lock: state['error'] = str(exc)
        event('Startup failed: '+str(exc), 'error')
        stop_network()

@app.get('/')
def index(): return render_template('index.html')

@app.post('/api/start')
def start():
    mode = request.json.get('mode','dynamic') if request.is_json else 'dynamic'
    if mode not in ('dynamic','static'): return jsonify(error='Invalid routing mode'),400
    with lock:
        if state['running'] or state['starting']: return jsonify(ok=False,error='Network is already running or starting'),409
        state['starting']=True; state['mode']=mode; state['error']=None; state['gen']+=1; gen=state['gen']
    threading.Thread(target=start_network,args=(mode,gen),daemon=True).start()
    return jsonify(ok=True,message='Network startup initiated')

@app.post('/api/stop')
def stop():
    stop_network(); event('Network stopped'); return jsonify(ok=True)

def stop_network():
    with lock:
        net=state.get('net'); ctrl=state.get('controller'); servers=list(state.get('servers',{}).values())
        state['gen']+=1   # cancels a startup that is still in progress
        state['net']=None; state['controller']=None; state['servers']={}; state['running']=False; state['starting']=False; state['started_at']=None; state['topology_links']=[]; state['switch_states']={}; state['link_states']={}
    for p in servers:
        try: p.terminate()
        except Exception: pass
    if net:
        try:
            with netlock: net.stop()
        except Exception: pass
    if ctrl and ctrl.poll() is None:
        try: os.killpg(ctrl.pid, signal.SIGTERM)
        except Exception:
            try: ctrl.terminate()
            except Exception: pass


@app.post('/api/switch/<name>/<action>')
def control_switch(name, action):
    if name not in ('s1', 's2', 's3', 's4') or action not in ('down', 'up'):
        return jsonify(error='Invalid switch or action'), 400
    if name in ('s1', 's4') and action == 'down':
        return jsonify(error=f'{name} is a protected core switch and cannot be disabled'), 403
    with lock:
        net = state.get('net'); running = state['running']; current = state['switch_states'].get(name, 'up')
    if not running or net is None:
        return jsonify(error='Start the network first'), 400
    if current == action:
        return jsonify(ok=True, status=current, message=f'{name} is already {current}')
    try:
        with netlock:
            sw = net.get(name)
            if action == 'down':
                # Stop the OVS bridge but retain Mininet interfaces for a clean restart.
                sw.stop(deleteIntfs=False)
            else:
                sw.start(net.controllers)
        with lock: state['switch_states'][name] = action
    except Exception as exc:
        return jsonify(error=f'Could not bring {name} {action}: {exc}'), 500
    event(f'Switch {name} taken {action.upper()}', 'error' if action == 'down' else 'success')
    return jsonify(ok=True, status=action)

@app.post('/api/link')
def control_link():
    data = request.get_json(force=True, silent=True) or {}
    link_id, action = data.get('id'), data.get('action')
    if action not in ('down', 'up'):
        return jsonify(error='Action must be down or up'), 400
    if not state['running'] or state.get('net') is None:
        return jsonify(error='Start the network first'), 400
    edge = next((e for e in state.get('topology_links', []) if e['intf_a']+'__'+e['intf_b'] == link_id), None)
    if edge is None:
        return jsonify(error='Unknown link'), 404
    if not edge['a'].startswith('s') or not edge['b'].startswith('s'):
        return jsonify(error='Only inter-switch links can be controlled here'), 400
    try:
        with netlock:
            for node_name, intf_name in ((edge['a'], edge['intf_a']), (edge['b'], edge['intf_b'])):
                intf = state['net'].get(node_name).intf(intf_name)
                intf.ifconfig('down' if action == 'down' else 'up')
        with lock: state['link_states'][link_id] = action
    except Exception as exc:
        return jsonify(error=f'Could not set link {action}: {exc}'), 500
    label = edge['a']+' ↔ '+edge['b']
    event(f'Link {label} set {action.upper()}', 'error' if action == 'down' else 'success')
    return jsonify(ok=True, status=action)

@app.post('/api/upload')
def upload():
    if not state['running']: return jsonify(error='Start the SDN network first'),400
    f=request.files.get('file')
    if not f or not f.filename: return jsonify(error='Choose a file'),400
    safe=re.sub(r'[^\w.\- ()]','_',Path(f.filename.replace('\\','/')).name).lstrip('.')[:120] or 'upload.bin'
    dest=UPLOADS/(str(int(time.time()*1000))+'_'+safe)
    f.save(dest)
    return jsonify(ok=True, name=safe, path=str(dest), size=dest.stat().st_size)

ENDPOINTS={'A':'10.0.0.3:9000','B':'10.0.0.4:9000'}
SERVER_OF={v:k for k,v in ENDPOINTS.items()}

@app.post('/api/transfer')
def transfer():
    if not state['running']: return jsonify(error='Network is not running'),400
    data=request.get_json(force=True,silent=True) or {}; path=Path(data.get('path','')).resolve(); server=data.get('server','both'); flip_bit=bool(data.get('flip_bit', False))
    if not path.is_file() or UPLOADS.resolve() not in path.parents: return jsonify(error='Invalid upload reference'),400
    endpoints={'A':[ENDPOINTS['A']],'B':[ENDPOINTS['B']],'both':[ENDPOINTS['A'],ENDPOINTS['B']]}.get(server)
    if not endpoints: return jsonify(error='Invalid server selection'),400
    net=state['net']; tid=str(int(time.time()*1000)); out=RUNTIME/(tid+'.json'); log=RUNTIME/(tid+'.log')
    # The client sends to every selected server at once and keeps retrying a server for ~1 minute of
    # consecutive failures, so one unreachable server cannot hold up (or fail) the other copy.
    cmd=[sys.executable,'-u',str(ROOT/'client.py'),str(path),'--servers',*endpoints,'--attempts','12','--timeout','4','--json',str(out)]
    if flip_bit: cmd.append('--flip-bit')
    proc=net.get('h1').popen(cmd,stdout=log.open('w'),stderr=subprocess.STDOUT)
    routes_now = json.loads((RUNTIME/'routes.json').read_text()).get('routes', {}) if (RUNTIME/'routes.json').exists() else {}
    item={'id':tid,'filename':path.name.split('_',1)[-1],'size':path.stat().st_size,'server':server,'status':'running','started':time.time(),'result':None,'process':proc,'json':out,'log':log,'routes_at_start':routes_now,'progress':{},'flip_bit':flip_bit,'_pos':0}
    with lock: state['transfers'].insert(0,item)
    event('Transfer started: '+item['filename']+' → '+server)
    threading.Thread(target=watch_transfer,args=(item,),daemon=True).start()
    return jsonify(ok=True,id=tid)

plock=threading.Lock()

def update_progress(item):
    with plock: _update_progress(item)

def _update_progress(item):
    """Read only the new complete lines of the transfer log; keep the newest PROGRESS record per server."""
    try:
        with item['log'].open('rb') as f:
            f.seek(item['_pos']); chunk=f.read()
    except OSError: return
    end=chunk.rfind(b'\n')
    if end < 0: return
    item['_pos']+=end+1
    for line in chunk[:end].decode(errors='replace').splitlines():
        if line.startswith('PROGRESS '):
            try: rec=json.loads(line[9:])
            except ValueError: continue
            key=SERVER_OF.get(rec.get('endpoint'))
            if key:
                item['progress'][key]=rec
                if rec.get('state') == 'checksum_failure' and not item.get('_checksum_event_'+key):
                    item['_checksum_event_'+key]=True
                    event('Server '+key+' rejected a corrupted chunk checksum for '+item['filename']+'; client is retrying the original data', 'error')

def watch_transfer(item):
    code=item['process'].wait()
    try: result=json.loads(item['json'].read_text())
    except Exception: result=[]
    update_progress(item)
    item['result']=result; item['exit_code']=code
    ok=[r for r in result if r.get('success')]
    item['status']='completed' if code==0 and result else 'partial' if ok else 'failed'
    names=lambda rs:', '.join('Server '+SERVER_OF.get(r.get('endpoint'),'?') for r in rs)
    if item['status']=='completed': event('Transfer completed: '+item['filename'],'success')
    elif item['status']=='partial': event('Transfer partly completed: '+item['filename']+' stored on '+names(ok)+'; failed on '+names([r for r in result if not r.get('success')]),'error')
    else: event('Transfer failed: '+item['filename'],'error')

@app.get('/api/status')
def status():
    with lock:
        net=state.get('net'); servers=dict(state.get('servers',{})); running=state['running']
        topo=list(state.get('topology_links',[])); link_states=dict(state.get('link_states',{}))
        switches=dict(state.get('switch_states',{})); transfers_src=list(state['transfers'][:30]); events=list(state['events'][:30])
    live_links=[]
    if net and running:
        # Linux interface byte counters on the actual Mininet switch ports (read from /sys, no Mininet shell needed).
        # RX means peer -> switch; TX means switch -> peer.
        for edge in topo:
            lid=edge['intf_a']+'__'+edge['intf_b']
            for side in ('a','b'):
                node=edge[side]
                if not node.startswith('s'):
                    continue
                intf=edge['intf_'+side]
                base=Path('/sys/class/net')/intf/'statistics'
                peer=edge['b' if side=='a' else 'a']
                try:
                    rec={'rx_bytes':int((base/'rx_bytes').read_text()),'tx_bytes':int((base/'tx_bytes').read_text()),
                         'rx_packets':int((base/'rx_packets').read_text()),'tx_packets':int((base/'tx_packets').read_text())}
                except (OSError, ValueError):
                    rec={'rx_bytes':0,'tx_bytes':0,'rx_packets':0,'tx_packets':0}
                live_links.append({'id':lid,'switch':node,'peer':peer,'status':link_states.get(lid,'up'),**rec})
    server_info={k:{'running':(k in servers and servers[k].poll() is None),'files':list_files(RUNTIME/('storage'+k))} for k in ('A','B')}
    try:
        route_state=json.loads((RUNTIME/'routes.json').read_text())
    except Exception:
        route_state={'mode':state['mode'],'routes':{}}
    transfers=[]
    for t in transfers_src:
        if t['status']=='running': update_progress(t)
        transfers.append({k:t.get(k) for k in ('id','filename','size','server','status','started','exit_code')} | {'result':t.get('result') or [],'progress':t.get('progress',{}),'routes':t.get('routes_at_start',{}),'flip_bit':t.get('flip_bit',False)})
    return jsonify(running=running,starting=state['starting'],mode=state['mode'],switches=switches,link_states=link_states,uptime=(time.time()-state['started_at'] if state['started_at'] else 0),
                   latency_ms=sample['latency'] if running else None,flows=sample['flows'] if running else {},links=live_links,servers=server_info,routes=route_state.get('routes',{}),link_metrics=route_state.get('link_metrics',[]),cost_model=route_state.get('cost_model'),transfers=transfers,events=events,error=state['error'])

@app.errorhandler(413)
def too_large(_): return jsonify(error='File is larger than the 1 GiB limit'),413

@app.errorhandler(500)
def server_error(exc): return jsonify(error='Internal error: '+str(exc)),500

def list_files(root):
    if not root.exists(): return []
    out=[]
    for p in sorted(root.glob('*.bin'),key=lambda x:x.stat().st_mtime,reverse=True):
        out.append({'name':p.name,'size':p.stat().st_size,'modified':time.strftime('%H:%M:%S',time.localtime(p.stat().st_mtime))})
    return out

@app.get('/api/file/<server>/<name>')
def download(server,name):
    from flask import send_file, abort
    if server not in ('A','B'): abort(404)
    p=(RUNTIME/('storage'+server)/Path(name).name).resolve()
    if not p.is_file() or p.parent != (RUNTIME/('storage'+server)).resolve(): abort(404)
    return send_file(p,as_attachment=True)

if __name__=='__main__':
    if os.geteuid()!=0:
        print('Run with: sudo python3 webui/app.py'); raise SystemExit(1)
    app.run(host='0.0.0.0',port=8080,threaded=True)
