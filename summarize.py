import csv,json
from pathlib import Path
rows=[]
for f in sorted(Path('results').glob('*/*.json')):
    if f.name not in ('client.json','client2.json'): continue
    for r in json.loads(f.read_text()): rows.append(dict(experiment=f.parent.name,**r))
keys=['experiment','endpoint','success','size','seconds','throughput_mbps','retries','resumed_offset','max_ack_gap_seconds','bytes_acknowledged','sha256']
with open('results/comparison.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(rows)
print('Wrote results/comparison.csv')
for r in rows: print(r['experiment'],r['endpoint'],'success=',r['success'],'seconds=',round(r['seconds'],2),'Mbps=',round(r.get('throughput_mbps',0),3))
