"""Seeded discrete-event simulator. Virtual seconds, no real calls."""
import argparse
import heapq
import json
import random
import tempfile
from pathlib import Path
from dialer import *

class SimulationProvider:
    """In-memory remote ledger for virtual-time runs; durable adapters tested separately."""
    def __init__(self,model):
        self.model,self.name,self.outage,self.ledger=model,model.name,False,{}
    def start(self,key):
        if self.outage:
            raise TimeoutError('simulated provider outage')
        self.ledger.setdefault(key,'RINGING')
        return key
    def status(self,key):
        if self.outage:
            raise TimeoutError('simulated provider outage')
        return self.ledger.get(key)
    def cancel(self,key):
        if self.outage:
            raise TimeoutError('simulated provider outage')
        self.ledger[key]='CANCELLED'
    def sample(self,rng,p):
        return self.model.sample(rng,p)
    def events(self,call,answered):
        return self.model.events(call,answered)
class SimulationStore(Store):
    """Reuse one connection in this single-threaded simulator only."""
    def __init__(self,path):
        super().__init__(path)
        self.connection=sqlite3.connect(self.path,isolation_level=None)
        self.connection.execute('PRAGMA synchronous=NORMAL')
    @contextlib.contextmanager
    def tx(self):
        if not hasattr(self,'connection'):
            with super().tx() as c:
                yield c
            return
        c=self.connection
        c.execute('BEGIN IMMEDIATE')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
def simulate(mode,scenario,provider_name='A',duration=900,agents=50):
    rng=random.Random(42)
    with tempfile.TemporaryDirectory() as tmp:
        s=SimulationStore(Path(tmp)/'db');s.seed(agents,30000,now=0)
        p=SimulationProvider((MockProvider if provider_name=='A' else SlowProvider)(Path(tmp)/'remote'))
        w=Worker(s,{p.name:p});gate=SafetyController(s)
        engine=Progressive() if mode=='progressive' else Predictive()
        queue=[]; serial=0; initiated=connected=busy=proposed=approved=reduced=0
        answers=attempts=0;decisions=[]
        for tick in range(duration):
            while queue and queue[0][0]<=tick:
                _,_,call,event_id,state=heapq.heappop(queue)
                changed=w.event(p.name,event_id,call,state)
                if changed and state=='ANSWERED': connected+=1; answers+=1; attempts+=1
                if changed and state=='FAILED': attempts+=1
                if state in TERMINAL: w.wrap_up(now=tick)
            # Simulator heartbeats represent agents that remain logged in.
            with s.tx() as c:
                c.execute('UPDATE agents SET heartbeat=?',(tick,))
                available=c.execute("SELECT count(*) FROM agents WHERE state='AVAILABLE'").fetchone()[0]
                ringing=c.execute("SELECT count(*) FROM calls WHERE state IN ('INITIATED','RINGING')").fetchone()[0]
                busy+=c.execute("SELECT count(*) FROM agents WHERE state='CONNECTED'").fetchone()[0]
            rate,talk={'A':(.2,120),'B':(.5,90),'C':(.7,180),'D':((.7 if tick<duration//2 else .1),(90 if tick<duration//2 else 180))}[scenario]
            estimate=(answers+2)/(attempts+4)
            request=engine.propose(available,answer_rate=estimate,ringing=ringing)
            # Planned provider outage: admit rejects during breaker window; existing calls continue.
            p.outage=provider_name=='B' and 300<=tick<330
            if p.outage:
                with s.tx() as c: c.execute('INSERT OR REPLACE INTO health VALUES (?,1,?)',(p.name,tick+10))
            calls=gate.admit(f'tick:{tick}',request,p.name,now=tick)
            proposed+=request;approved+=len(calls);reduced+=int(len(calls)<request)
            if tick%60==0: decisions.append(dict(second=tick,estimate=round(estimate,3),available=available,ringing=ringing,requested=request,approved=len(calls)))
            w.dispatch(now=tick)
            for call in calls:
                latency,answer,failed=p.sample(rng,rate)
                initiated+=1
                for event_id,state in p.events(call,answer):
                    delay=latency+(talk if state=='COMPLETED' else 0)
                    if event_id.endswith(':late'): delay+=talk+1
                    serial+=1;heapq.heappush(queue,(tick+delay,serial,call,event_id,state))
        result = dict(mode=mode,scenario=scenario,provider=provider_name,seconds=duration,agents=agents,
          utilization=round(busy/(duration*agents),4),initiated=initiated,connected=connected,
          requested=proposed,approved=approved,reduced_ticks=reduced,decisions=decisions,
          note='Utilization is connected agent-seconds / staffed agent-seconds; unfinished calls remain active at horizon.')
        s.connection.close()
        return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='simulation_results.json');args=parser.parse_args()
    rows=[]
    for p in ['A','B']:
        for s in 'ABCD':
            for m in ['progressive','predictive']:
                rows.append(simulate(m,s,p))
                print('Finished',p,s,m,flush=True)
    Path(args.output).write_text(json.dumps(rows,indent=2))
    for r in rows: print(r['provider'],r['scenario'],r['mode'],r['utilization'],r['initiated'],r['connected'])



