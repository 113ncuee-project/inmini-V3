"""Calendar optimization must preserve every legacy scheduling decision."""
import random
import unittest

from simple_rapidchiplet.hybrid.scheduler import Job, schedule_jobs


class CoalescedCalendarTests(unittest.TestCase):
    def test_random_shared_resource_DAGs_match_all_legacy_event_times(self):
        for seed in range(20):
            rng = random.Random(seed)
            jobs = []
            for i in range(80):
                deps = tuple(f'j{j}' for j in rng.sample(range(i), min(i, rng.randrange(4))))
                resources = tuple(f'r{j}' for j in rng.sample(range(6), rng.randrange(1, 5)))
                duration = rng.choice((0., .125, 1., 3., 10.))
                jobs.append(Job(f'j{i}', deps, resources if duration else (), duration, priority=(rng.randrange(3), i)))
            for policy in ('priority', 'earliest'):
                old = schedule_jobs(jobs, policy=policy)
                new = schedule_jobs(jobs, policy=policy, availability='coalesced')
                self.assertEqual([(e.job.id, e.start_s, e.finish_s) for e in old.events],
                                 [(e.job.id, e.start_s, e.finish_s) for e in new.events])
                self.assertEqual(old.resource_busy_s, new.resource_busy_s)
                self.assertTrue(new.validate())

    def test_subnanosecond_tolerance_and_zero_duration_match(self):
        jobs = [Job('a', (), ('x',), 2e-9), Job('b', (), ('x', 'y'), 1e-9),
                Job('c', ('a',), (), 0.), Job('d', ('c',), ('y',), 1e-12)]
        old, new = schedule_jobs(jobs), schedule_jobs(jobs, availability='coalesced')
        self.assertEqual(old, new)


if __name__ == '__main__':
    unittest.main()
