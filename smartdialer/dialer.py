import contextlib
import math
import random
import sqlite3
import time
import uuid

TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED'}
RANK = {'RESERVED': 1, 'INITIATED': 2, 'RINGING': 3, 'ANSWERED': 4, 'CONNECTED': 5}

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.tx() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS agents(id INTEGER PRIMARY KEY, state TEXT, heartbeat REAL);
            CREATE TABLE IF NOT EXISTS borrowers(id INTEGER PRIMARY KEY, priority INTEGER, state TEXT);
            CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, job TEXT, agent INTEGER, borrower INTEGER,
              state TEXT, created REAL, provider TEXT, connected INTEGER DEFAULT 0);
            CREATE UNIQUE INDEX IF NOT EXISTS active_agent ON calls(agent)
              WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED');
            CREATE UNIQUE INDEX IF NOT EXISTS active_borrower ON calls(borrower)
              WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED');
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS outbox(call_id TEXT PRIMARY KEY, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(provider TEXT, event_id TEXT, call_id TEXT, state TEXT,
              PRIMARY KEY(provider,event_id));
            CREATE TABLE IF NOT EXISTS health(provider TEXT PRIMARY KEY, failures INTEGER, blocked_until REAL);
            ''')
    @contextlib.contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
    def seed(self, agents=50, borrowers=30000, now=None):
        now = time.time() if now is None else now
        with self.tx() as c:
            c.executemany('INSERT OR IGNORE INTO agents VALUES (?, ?, ?)', ((i,'AVAILABLE',now) for i in range(agents)))
            c.executemany('INSERT OR IGNORE INTO borrowers VALUES (?, ?, ?)', ((i,i%100,'QUEUED') for i in range(borrowers)))
    def count(self, table, where='1=1'):
        if table not in {'calls','agents','borrowers','events','outbox'}:
            raise ValueError(table)
        with self.tx() as c:
            return c.execute(f'SELECT count(*) FROM {table} WHERE {where}').fetchone()[0]

class Progressive:
    def propose(self, available, **kwargs):
        return available

class Predictive:
    def propose(self, available, answer_rate=.5, ringing=0, **kwargs):
        # Beta smoothing belongs in the estimator; rate here is its bounded output.
        p = max(.05, min(.99, answer_rate))
        expected_need = max(0, available - ringing*p)
        return math.ceil(expected_need/p)

class SafetyController:
    """Only admission entry point. Rechecks capacity and allocates in ONE transaction."""
    def __init__(self, store, ttl=30, batch_limit=100):
        self.store, self.ttl, self.batch_limit = store, ttl, batch_limit
    def admit(self, job, requested, provider='A', now=None):
        now = time.time() if now is None else now
        with self.store.tx() as c:
            if c.execute('SELECT 1 FROM jobs WHERE id=?',(job,)).fetchone():
                return [r[0] for r in c.execute('SELECT id FROM calls WHERE job=?',(job,))]
            c.execute('INSERT INTO jobs VALUES (?)',(job,))
            health = c.execute('SELECT blocked_until FROM health WHERE provider=?',(provider,)).fetchone()
            if health and health[0] > now:
                return []
            limit = max(0, min(int(requested), self.batch_limit))
            agents = c.execute("SELECT id FROM agents WHERE state='AVAILABLE' AND heartbeat>=? ORDER BY id LIMIT ?",(now-self.ttl,limit)).fetchall()
            borrowers = c.execute("SELECT id FROM borrowers WHERE state='QUEUED' ORDER BY priority DESC,id LIMIT ?",(len(agents),)).fetchall()
            result=[]
            for (agent,), (borrower,) in zip(agents,borrowers):
                call = uuid.uuid4().hex
                c.execute("UPDATE agents SET state='RESERVED' WHERE id=?",(agent,))
                c.execute("UPDATE borrowers SET state='RESERVED' WHERE id=?",(borrower,))
                c.execute("INSERT INTO calls(id,job,agent,borrower,state,created,provider) VALUES (?,?,?,?,'RESERVED',?,?)",(call,job,agent,borrower,now,provider))
                c.execute('INSERT INTO outbox(call_id) VALUES (?)',(call,))
                result.append(call)
            return result

class MockProvider:
    """Durable provider ledger models provider-side idempotency and status queries."""
    def __init__(self, path, name='A', outage=False):
        self.name,self.outage,self.path=name,outage,str(path)
        with contextlib.closing(sqlite3.connect(self.path)) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS remote(id TEXT PRIMARY KEY,state TEXT)')
    def start(self, key):
        if self.outage:
            raise TimeoutError('provider unavailable; outcome must be reconciled')
        with contextlib.closing(sqlite3.connect(self.path)) as c, c:
            c.execute("INSERT OR IGNORE INTO remote VALUES (?,'RINGING')",(key,))
        return key
    def status(self,key):
        if self.outage:
            raise TimeoutError('status unavailable')
        with contextlib.closing(sqlite3.connect(self.path)) as c, c:
            row=c.execute('SELECT state FROM remote WHERE id=?',(key,)).fetchone()
        return row[0] if row else None
    def cancel(self,key):
        if self.outage:
            raise TimeoutError('cancel unconfirmed')
        with contextlib.closing(sqlite3.connect(self.path)) as c, c:
            c.execute("INSERT OR IGNORE INTO remote VALUES (?,'CANCELLED')",(key,))
            c.execute("UPDATE remote SET state='CANCELLED' WHERE id=? AND state NOT IN ('COMPLETED','FAILED','CANCELLED')",(key,))
    def sample(self,rng,p):
        return (1, rng.random()<p, False)
    def events(self,call,answered):
        return [(call+':ring','RINGING'),(call+':answer','ANSWERED'),(call+':end','COMPLETED')] if answered else [(call+':fail','FAILED')]

class SlowProvider(MockProvider):
    def __init__(self,path,outage=False):
        super().__init__(path,'B',outage)
    def sample(self,rng,p):
        failed=rng.random()<.12
        return (5+rng.randrange(6), not failed and rng.random()<p, failed)
    def events(self,call,answered):
        e=super().events(call,answered)
        return e+[e[0]]+[ (call+':late','RINGING') ]

class Worker:
    def __init__(self,store,providers):
        self.store,self.providers=store,providers
    def event(self,provider,event_id,call,state):
        if state not in set(RANK)|TERMINAL:
            raise ValueError(state)
        with self.store.tx() as c:
            row=c.execute('SELECT agent,borrower,state,provider FROM calls WHERE id=?',(call,)).fetchone()
            if not row or row[3]!=provider:
                return False
            if not c.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?)',(provider,event_id,call,state)).rowcount:
                return False
            agent,borrower,old,_=row
            if old in TERMINAL or (state not in TERMINAL and RANK[state]<=RANK[old]):
                return False
            if state=='ANSWERED':
                # Mock bridge is atomic locally. Real bridge needs another durable outbox.
                state='CONNECTED'
            c.execute('UPDATE calls SET state=?,connected=max(connected,?) WHERE id=?',(state,int(state=='CONNECTED'),call))
            if state in TERMINAL:
                c.execute("UPDATE agents SET state=CASE WHEN state='OFFLINE' THEN 'OFFLINE' ELSE 'WRAP_UP' END WHERE id=?",(agent,))
                c.execute("UPDATE borrowers SET state='DONE' WHERE id=?",(borrower,))
                c.execute('UPDATE outbox SET done=1 WHERE call_id=?',(call,))
            else:
                c.execute("UPDATE agents SET state=? WHERE id=? AND state!='OFFLINE'",('CONNECTED' if state=='CONNECTED' else 'DIALING',agent))
            return True
    def dispatch(self,crash_after_send=False,now=None):
        now=time.time() if now is None else now
        with self.store.tx() as c:
            pending=c.execute('SELECT o.call_id,k.provider,k.agent FROM outbox o JOIN calls k ON k.id=o.call_id WHERE o.done=0').fetchall()
        for call,name,agent in pending:
            p=self.providers[name]
            with self.store.tx() as c:
                row=c.execute('SELECT state FROM calls WHERE id=?',(call,)).fetchone()
                a=c.execute('SELECT state,heartbeat FROM agents WHERE id=?',(agent,)).fetchone()
                if row[0] in TERMINAL:
                    continue
                stale=a[0]=='OFFLINE' or a[1]<now-30
                h=c.execute('SELECT blocked_until FROM health WHERE provider=?',(name,)).fetchone()
            try:
                if stale:
                    p.cancel(call)
                    self.event(name,call+':cancel',call,'CANCELLED')
                    continue
                if h and h[0]>now:
                    continue
                p.start(call)
                if crash_after_send:
                    raise RuntimeError('simulated worker crash after provider accepted')
                self.event(name,call+':init',call,'INITIATED')
                with self.store.tx() as c:
                    c.execute('UPDATE outbox SET done=1 WHERE call_id=?',(call,))
                    c.execute('INSERT OR REPLACE INTO health VALUES (?,0,0)',(name,))
            except TimeoutError:
                with self.store.tx() as c:
                    c.execute('INSERT OR IGNORE INTO health VALUES (?,0,0)',(name,))
                    c.execute('UPDATE health SET failures=failures+1,blocked_until=? WHERE provider=?',(now+10,name))
    def recover(self,now=None):
        self.dispatch(now=now)
        with self.store.tx() as c:
            active=c.execute("SELECT id,provider,agent FROM calls WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED')").fetchall()
        for call,name,agent in active:
            p=self.providers[name]
            with self.store.tx() as c:
                a=c.execute('SELECT state,heartbeat FROM agents WHERE id=?',(agent,)).fetchone()
            try:
                if a[0]=='OFFLINE' or a[1]<(time.time() if now is None else now)-30:
                    p.cancel(call)
                status=p.status(call)
                if status:
                    self.event(name,call+':reconcile:'+status,call,status)
            except TimeoutError:
                pass # Never release capacity while the remote outcome is unknown.
    def wrap_up(self,now=None):
        with self.store.tx() as c:
            c.execute("UPDATE agents SET state='AVAILABLE',heartbeat=? WHERE state='WRAP_UP'",(time.time() if now is None else now,))


