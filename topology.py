import argparse, json, os, subprocess, sys, time, hashlib
from pathlib import Path
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel
ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(); p.add_argument('--scenario',choices=['cli','normal','failure','server-recovery','concurrent'],default='cli'); p.add_argument('--tag',default='dynamic'); a=p.parse_args()
    os.chdir(ROOT); out=ROOT/'results'/a.tag; out.mkdir(parents=True,exist_ok=True)
    net=Mininet(controller=None,switch=OVSSwitch,link=TCLink)
    net.addController('c0',controller=RemoteController,ip='127.0.0.1',port=6633)
    s={i:net.addSwitch('s%d'%i,dpid='%016x'%i,protocols='OpenFlow10',failMode='secure') for i in range(1,5)}
    h={i:net.addHost('h%d'%i,ip='10.0.0.%d/24'%i,mac='00:00:00:00:00:%02x'%i) for i in range(1,5)}
    for host,sw,port in [(1,1,1),(2,1,2),(3,2,1),(4,4,1)]: net.addLink(h[host],s[sw],port2=port)
    for x,xp,y,yp,delay in [(1,3,2,2,'5ms'),(1,4,3,1,'10ms'),(2,3,4,3,'5ms'),(3,2,4,4,'10ms')]: net.addLink(s[x],s[y],port1=xp,port2=yp,bw=10,delay=delay)
    procs=[]; handles=[]
    def spawn(host,args,name):
        f=open(out/(name+'.log'),'a'); handles.append(f)
        proc=h[host].popen([sys.executable,'-u']+args,stdout=f,stderr=subprocess.STDOUT); procs.append(proc); return proc
    def server(i): return spawn(i,['server.py','--root',str(out/('storage%d'%i))],'server%d'%i)
    def client(i,name,targets): return spawn(i,['client.py',str(payload),'--servers',*targets,'--attempts','10','--pause','0.015','--json',str(out/(name+'.json'))],name)
    try:
        net.start()
        if not net.waitConnected(timeout=15): raise RuntimeError('Start controller first')
        time.sleep(2); loss=net.pingAll(); (out/'ping.json').write_text(json.dumps({'loss_percent':loss}))
        if loss: raise RuntimeError('Connectivity failed; inspect controller')
        sa=server(3); server(4); time.sleep(1)
        payload=out/'sample.bin'; payload.write_bytes(os.urandom(8*1024*1024))
        if a.scenario=='cli':
            print('Try: h1 python3 client.py '+str(payload)+' --json '+str(out/'manual.json')); CLI(net); return
        targets=['10.0.0.3:9000','10.0.0.4:9000'] if a.scenario=='normal' else ['10.0.0.3:9000']
        proc=client(1,'client',targets); event={}
        if a.scenario in ('failure','server-recovery'):
            time.sleep(2); event={'event_epoch':time.time()}
            if a.scenario=='failure': net.configLinkStatus('s1','s2','down'); print('FAILED s1-s2; alternate s1-s3-s4-s2')
            else: sa.terminate(); sa.wait(timeout=5); time.sleep(3); server(3)
        second=client(2,'client2',['10.0.0.4:9000']) if a.scenario=='concurrent' else None
        code=proc.wait(timeout=150)
        if second: second.wait(timeout=150)
        event.update(client_exit=code,scenario=a.scenario); (out/'experiment.json').write_text(json.dumps(event,indent=2))
        print((out/'client.json').read_text() if (out/'client.json').exists() else 'Inspect client.log')
        fid=hashlib.sha256(payload.read_bytes()).hexdigest(); checks={}
        for i in (3,4):
            dest=out/('storage%d'%i)/(fid+'.bin'); checks['server%d'%i]=dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()==fid
        (out/'integrity.json').write_text(json.dumps(checks,indent=2))
    finally:
        for proc in procs:
            if proc.poll() is None: proc.terminate()
        for proc in procs:
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        for f in handles: f.close()
        net.stop()
if __name__=='__main__': setLogLevel('info'); main()
