import random
import unittest
from simple_rapidchiplet.hybrid.scheduler import Job,schedule_jobs
from simple_rapidchiplet.hybrid.calendar_index import IndexedCalendar

class CalendarTests(unittest.TestCase):
    def test_large_random_dag_matches_original_calendars(self):
        for seed in range(12):
            rng=random.Random(seed);jobs=[]
            for i in range(500):
                deps=tuple(str(d) for d in rng.sample(range(i),min(i,rng.randrange(4))))
                resources=tuple('r'+str(r) for r in rng.sample(range(9),rng.randrange(1,5)))
                duration=rng.choice((0.,1e-9,.0001,.01,.2))
                jobs.append(Job(str(i),deps,resources if duration else (),duration,priority=(rng.randrange(10),)))
            a=schedule_jobs(jobs,availability='coalesced')
            from simple_rapidchiplet.hybrid.native_schedule import available
            for backend in ('indexed','native') if available() else ('indexed',):
                b=schedule_jobs(jobs,availability=backend)
                self.assertEqual([e.job.id for e in a.events],[e.job.id for e in b.events])
                for old,new in zip(a.events,b.events):
                    self.assertEqual(old.start_s,new.start_s)
                    self.assertEqual(old.finish_s,new.finish_s)
                self.assertEqual(a.resource_busy_s,b.resource_busy_s)
                from simple_rapidchiplet.hybrid.diagnostics import _schedule_slack
                self.assertEqual(_schedule_slack(a),_schedule_slack(b))

    def test_gap_inside_tree_and_tail(self):
        cal=IndexedCalendar()
        for i in range(10000):cal.reserve(i*2.,i*2.+1.,str(i))
        self.assertEqual(cal.first_slot(0.,1.),1.)
        self.assertEqual(cal.first_slot(0.,1.5),19999.)
        self.assertEqual(cal.first_slot(2.5,.25),3.)

    def test_native_rejects_invalid_graphs_and_accepts_empty_graph(self):
        from simple_rapidchiplet.hybrid.native_schedule import available
        if not available():self.skipTest('optional native binary not built')
        self.assertEqual(schedule_jobs((),availability='native').makespan_s,0.)
        for jobs in ((Job('a',('missing',),(),1.),),
                     (Job('a',('b',),(),1.),Job('b',('a',),(),1.)),
                     (Job('a',(),(),1.),Job('a',(),(),2.))):
            with self.assertRaises(ValueError):schedule_jobs(jobs,availability='native')

if __name__=='__main__':unittest.main()
