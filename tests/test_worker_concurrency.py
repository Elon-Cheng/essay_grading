import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend import worker
from backend import saas
from backend import accounts
from tests.test_saas import SaaSTests as _SaaSFixture


class WorkerConcurrencyTests(unittest.TestCase):
    def test_two_tasks_overlap_without_starting_third_and_refill(self):
        release = threading.Event()
        both_started = threading.Event()
        started, jobs = [], [{'id':str(i),'start':None} for i in range(3)]
        lock = threading.Lock()
        def pick(excluded):
            with lock:
                return next((j for j in jobs if j['id'] not in excluded and j['id'] not in started), None)
        def grade(ident, start):
            with lock:
                started.append(ident)
                if len(started) == 2:
                    both_started.set()
            if not release.wait(5):
                raise RuntimeError('Tasks did not overlap')
        with patch.object(worker,'running',True), patch.object(worker,'next_job',side_effect=pick), \
                patch.object(worker.app,'run_job',side_effect=grade), ThreadPoolExecutor(max_workers=2) as pool:
            queue = worker.GradingQueue(pool,2)
            try:
                queue.dispatch()
                self.assertTrue(both_started.wait(3))
                queue.dispatch()
                self.assertEqual(len(started),2)
                self.assertEqual(len(queue.active),2)
            finally:
                release.set()
            for future in queue.active.values():
                future.result(timeout=3)
            queue.dispatch()
            for future in queue.active.values():
                future.result(timeout=3)
            self.assertCountEqual(started,['0','1','2'])

    def test_failure_does_not_block_remaining_jobs(self):
        jobs = iter([{'id':'bad','start':None},{'id':'next','start':None},None])
        def grade(ident,start):
            if ident == 'bad':
                raise RuntimeError('Expected failure')
        with patch.object(worker,'running',True), patch.object(worker,'next_job',side_effect=lambda _:next(jobs)), \
                patch.object(worker.app,'run_job',side_effect=grade), ThreadPoolExecutor(max_workers=1) as pool:
            queue = worker.GradingQueue(pool,1)
            queue.dispatch()
            with self.assertRaises(RuntimeError):
                queue.active['bad'].result(timeout=3)
            with self.assertLogs(level='ERROR'):
                queue.dispatch()
            queue.active['next'].result(timeout=3)

    def test_configuration_bounds(self):
        for value in ('0','9','invalid'):
            with patch.dict(worker.os.environ,{'WORKER_CONCURRENCY':value}):
                with self.assertRaises(ValueError):
                    worker.concurrency()


class WorkerClaimTests(unittest.TestCase):
    setUp = _SaaSFixture.setUp
    tearDown = _SaaSFixture.tearDown
    submit = _SaaSFixture.submit

    def test_only_one_runner_can_claim_same_job(self):
        ident=self.submit().json()['id']
        gate=threading.Barrier(4)
        def claim(index):
            gate.wait(timeout=5)
            return saas.claim(ident,str(index))
        with ThreadPoolExecutor(max_workers=4) as pool:
            result=list(pool.map(claim,range(4)))
        self.assertEqual(sum(result),1)

    def test_two_complete_grading_jobs_keep_quota_and_files_separate(self):
        identities=[self.submit().json()['id'] for _ in range(2)]
        gate=threading.Barrier(2)
        def grade(*args,**kwargs):
            gate.wait(timeout=5)
            return ''  # Existing demo fixture; no paid AI requests.
        with patch.dict(worker.os.environ,{'OPENAI_API_KEY':''}), \
                patch.object(worker.app,'call_openai',side_effect=grade), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda ident:worker.app.run_job(ident,None),identities))
        with accounts.database() as db:
            rows=db.execute('SELECT id,status,quota_state FROM jobs ORDER BY created').fetchall()
            self.assertEqual(len(rows),2)
            self.assertTrue(all(row['status']=='succeeded' and row['quota_state']=='committed' for row in rows))
        for ident in identities:
            self.assertTrue((self.root/ident/'grading.md').is_file())


if __name__ == '__main__':
    unittest.main()
