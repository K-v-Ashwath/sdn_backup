"""Windows/Linux socket-only test; not an SDN demo."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
from client import backup
if __name__=='__main__':
    procs=[]
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder); file=root/'demo.bin'; file.write_bytes(os.urandom(256*1024))
        try:
            for port in (19001,19002): procs.append(subprocess.Popen([sys.executable,'server.py','--host','127.0.0.1','--port',str(port),'--root',str(root/str(port))]))
            time.sleep(1)
            results=[backup(file,'127.0.0.1:'+str(p)) for p in (19001,19002)]
            assert all(r['success'] for r in results)
            print(json.dumps(results,indent=2)); print('PASS: two TCP replicas. SDN still requires Mininet.')
        finally:
            for p in procs: p.terminate()
            for p in procs: p.wait()
