import contextlib
import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dialer import Store,SafetyController,Worker,MockProvider,SlowProvider,Predictive

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.s=Store(self.root/'db')
        self.s.seed(5,100)
        self.g=SafetyController(self.s)
        self.p=MockProvider(self.root/'remote')
        self.w=Worker(self.s,{'A':self.p})
    def tearDown(self):
        self.tmp.cleanup()
    def test_concurrent_workers(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results=list(pool.map(lambda n: self.g.admit(str(n),50),range(12)))
        self.assertEqual(sum(map(len,results)),5)
        with self.s.tx() as c:
            self.assertEqual(c.execute('SELECT count(DISTINCT agent),count(DISTINCT borrower) FROM calls').fetchone(),(5,5))
    def test_duplicate_job(self):
        a=self.g.admit('job',2)
        self.assertEqual(a,self.g.admit('job',2))
        self.assertEqual(self.s.count('calls'),2)
    def test_crash_after_remote_accept_and_restart(self):
        self.g.admit('job',1)
        with self.assertRaises(RuntimeError): self.w.dispatch(True)
        restarted=Worker(Store(self.root/'db'),{'A':MockProvider(self.root/'remote')})
        restarted.recover()
        with contextlib.closing(sqlite3.connect(self.root/'remote')) as c, c:
            self.assertEqual(c.execute('SELECT count(*) FROM remote').fetchone()[0],1)
        self.assertEqual(self.s.count('calls',"state='RINGING'"),1)
    def test_duplicate_and_out_of_order(self):
        call=self.g.admit('job',1)[0]
        self.assertTrue(self.w.event('A','e',call,'ANSWERED'))
        self.assertFalse(self.w.event('A','e',call,'ANSWERED'))
        self.assertFalse(self.w.event('A','another',call,'ANSWERED'))
        self.w.event('A','end',call,'COMPLETED')
        self.assertFalse(self.w.event('A','late',call,'RINGING'))
        self.assertEqual(self.s.count('calls',"state='COMPLETED' AND connected=1"),1)
    def test_terminal_before_answer(self):
        call=self.g.admit('job',1)[0]
        self.w.event('A','end',call,'COMPLETED')
        self.assertFalse(self.w.event('A','answer',call,'ANSWERED'))
        self.assertEqual(self.s.count('calls','connected=1'),0)
    def test_crash_after_answer(self):
        call=self.g.admit('job',1)[0]
        self.w.event('A','answer',call,'ANSWERED')
        Worker(Store(self.root/'db'),{'A':self.p}).event('A','end',call,'COMPLETED')
        self.assertEqual(self.s.count('agents',"state='WRAP_UP'"),1)
    def test_outage_holds_reservations_and_blocks_new(self):
        self.g.admit('job',2)
        self.p.outage=True
        self.w.dispatch()
        self.assertEqual(self.g.admit('new',5),[])
        self.assertEqual(self.s.count('agents',"state='RESERVED'"),2)
        self.p.outage=False
        self.w.recover(now=__import__('time').time()+11)
        self.assertEqual(self.s.count('outbox','done=0'),0)
    def test_agent_loss_confirm_cancel_before_release(self):
        self.g.admit('job',1)
        self.w.dispatch()
        with self.s.tx() as c: c.execute("UPDATE agents SET state='OFFLINE' WHERE id=0")
        self.p.outage=True
        self.w.recover()
        self.assertEqual(self.s.count('calls',"state='CANCELLED'"),0)
        self.p.outage=False
        self.w.recover()
        self.assertEqual(self.s.count('calls',"state='CANCELLED'"),1)
        self.assertEqual(self.s.count('agents',"state='OFFLINE'"),1)
    def test_forty_agents_disappear(self):
        s=Store(self.root/'large'); s.seed(100,1000)
        with s.tx() as c: c.execute("UPDATE agents SET state='OFFLINE' WHERE id<40")
        self.assertEqual(len(SafetyController(s).admit('x',100)),60)
    def test_predictive_cannot_exceed_capacity(self):
        proposed=Predictive().propose(5,.2)
        self.assertEqual(proposed,25)
        self.assertEqual(len(self.g.admit('x',proposed)),5)
    def test_stale_agent_and_wrong_provider(self):
        with self.s.tx() as c: c.execute('UPDATE agents SET heartbeat=0')
        self.assertEqual(self.g.admit('x',5),[])
    def test_slow_provider_contract(self):
        p=SlowProvider(self.root/'b')
        p.start('id');p.start('id');self.assertEqual(p.status('id'),'RINGING')
        self.assertGreater(len(p.events('id',True)),3)
        p.cancel('id');self.assertEqual(p.status('id'),'CANCELLED')

    def test_cancellation_tombstone_survives_delayed_start(self):
        self.p.cancel('late')
        self.p.start('late')
        self.assertEqual(self.p.status('late'),'CANCELLED')
    def test_wrong_provider_rejected(self):
        call=self.g.admit('job',1)[0]
        self.assertFalse(self.w.event('B','fake',call,'COMPLETED'))
        self.assertEqual(self.s.count('events'),0)
    def test_two_workers_dispatch_same_outbox(self):
        self.g.admit('job',5)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: Worker(self.s,{'A':self.p}).dispatch(),range(2)))
        with contextlib.closing(sqlite3.connect(self.root/'remote')) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM remote').fetchone()[0],5)
        self.assertEqual(self.s.count('outbox','done=0'),0)
if __name__=='__main__': unittest.main(verbosity=2)


