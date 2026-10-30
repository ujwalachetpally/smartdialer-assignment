import concurrent.futures
import json
import tempfile
import time
from pathlib import Path
from dialer import Store,SafetyController

def run(agents):
    with tempfile.TemporaryDirectory() as tmp:
        store=Store(Path(tmp)/'db');store.seed(agents,30000)
        gate=SafetyController(store)
        start=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results=list(pool.map(lambda i: len(gate.admit(str(i),100)),range((agents+99)//100+8)))
        elapsed=time.perf_counter()-start
        allocated=sum(results)
        assert allocated==agents
        with store.tx() as c:
            assert c.execute('SELECT count(DISTINCT agent),count(DISTINCT borrower) FROM calls').fetchone()==(agents,agents)
        return dict(agents=agents,workers=8,allocated=allocated,seconds=round(elapsed,4),allocations_per_second=round(allocated/elapsed,1))
if __name__=='__main__':
    rows=[run(n) for n in [100,1000,10000]]
    Path('load_results.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2))
