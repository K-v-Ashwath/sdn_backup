import hashlib,os,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from client import backup, backup_all
from protocol import send,receive
class Application(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        s=socket.socket(); s.bind(('127.0.0.1',0)); self.port=s.getsockname()[1]; s.close()
        self.p=subprocess.Popen([sys.executable,'server.py','--host','127.0.0.1','--port',str(self.port),'--root',str(self.root/'store')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.endpoint='127.0.0.1:'+str(self.port)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if self.p.poll() is not None:
                self.fail('Backup server exited during startup')
            try:
                with socket.create_connection(('127.0.0.1',self.port),timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        else:
            self.fail('Backup server did not begin listening within 5 seconds')
    def tearDown(self): self.p.terminate(); self.p.wait(); self.tmp.cleanup()
    def file(self,size):
        p=self.root/'input'; p.write_bytes(os.urandom(size)); return p
    def test_transfer_and_idempotence(self):
        p=self.file(200000); self.assertTrue(backup(p,self.endpoint)['success']); r=backup(p,self.endpoint); self.assertTrue(r['success']); self.assertEqual(r['resumed_offset'],200000)
    def test_interrupted_resume(self):
        p=self.file(200000); data=p.read_bytes(); fid=hashlib.sha256(data).hexdigest()
        with socket.create_connection(('127.0.0.1',self.port)) as s:
            send(s,{'file_id':fid,'size':len(data)}); receive(s)
            send(s,{'offset':0,'sha256':hashlib.sha256(data[:65536]).hexdigest()},data[:65536]); self.assertEqual(receive(s)[0]['ack'],65536)
        r=backup(p,self.endpoint); self.assertTrue(r['success']); self.assertEqual(r['resumed_offset'],65536)
        self.assertEqual((self.root/'store'/(fid+'.bin')).read_bytes(),data)
    def test_bad_chunk_rejected(self):
        p=self.file(12); fid=hashlib.sha256(p.read_bytes()).hexdigest()
        with socket.create_connection(('127.0.0.1',self.port)) as s:
            send(s,{'file_id':fid,'size':12}); receive(s); send(s,{'offset':0,'sha256':'wrong'},p.read_bytes()); self.assertIn('error',receive(s)[0])
        self.assertFalse((self.root/'store'/(fid+'.bin')).exists())
    def test_empty_file(self): self.assertTrue(backup(self.file(0),self.endpoint)['success'])
    def test_whole_file_mismatch(self):
        data=b'wrong'; fid=hashlib.sha256(b'right').hexdigest()
        with socket.create_connection(('127.0.0.1',self.port)) as s:
            send(s,{'file_id':fid,'size':5}); receive(s); send(s,{'offset':0,'sha256':hashlib.sha256(data).hexdigest()},data); receive(s); self.assertIn('error',receive(s)[0])
        self.assertFalse((self.root/'store'/(fid+'.bin')).exists())
    def test_reconnect_preempts_dead_connection(self):
        # A path failure leaves a half-open connection that still owns the file on the server.
        p=self.file(300000); data=p.read_bytes(); fid=hashlib.sha256(data).hexdigest()
        stale=socket.create_connection(('127.0.0.1',self.port)); send(stale,{'file_id':fid,'size':len(data)}); receive(stale)
        send(stale,{'offset':0,'sha256':hashlib.sha256(data[:65536]).hexdigest()},data[:65536]); receive(stale)   # ...and now it goes silent, still open
        t0=time.monotonic(); r=backup(p,self.endpoint,attempts=3,timeout=3); stale.close()
        self.assertTrue(r['success'],r); self.assertLess(time.monotonic()-t0,5)
        self.assertEqual((self.root/'store'/(fid+'.bin')).read_bytes(),data)
    def test_unreachable_server_does_not_block_the_other(self):
        dead=socket.socket(); dead.bind(('127.0.0.1',0)); dead_port=dead.getsockname()[1]; dead.close()   # nothing listens here
        p=self.file(200000); t0=time.monotonic()
        res=backup_all(p,['127.0.0.1:%d'%dead_port,self.endpoint],attempts=3,timeout=.5)
        self.assertFalse(res[0]['success']); self.assertTrue(res[1]['success'],res[1])
        self.assertLess(time.monotonic()-t0,15)
    def test_progress_resets_failure_budget(self):
        # Several short outages in a row must not exhaust the retry budget while progress is being made.
        p=self.file(5*65536); fid=hashlib.sha256(p.read_bytes()).hexdigest(); data=p.read_bytes()
        for i in range(4):   # four interrupted attempts, each stores one more chunk
            with socket.create_connection(('127.0.0.1',self.port)) as s:
                send(s,{'file_id':fid,'size':len(data)}); off=receive(s)[0]['offset']
                send(s,{'offset':off,'sha256':hashlib.sha256(data[off:off+65536]).hexdigest()},data[off:off+65536]); receive(s)
        r=backup(p,self.endpoint,attempts=1); self.assertTrue(r['success']); self.assertEqual(r['resumed_offset'],4*65536)
if __name__=='__main__': unittest.main()
