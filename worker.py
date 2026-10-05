"""Persistent queue worker and payment reconciliation. Run separately from uvicorn."""
import logging
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
import app
import accounts
import payments
import saas

running = True


def shutdown(*_):
    global running
    running = False


def tick():
    saas.recover()
    payments.reconcile()
    with accounts.database() as db:
        job = db.execute("SELECT id,start FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
    if job:
        app.run_job(job['id'], job['start'])
        return True
    return False


def concurrency():
    value = int(os.getenv('WORKER_CONCURRENCY', '1'))
    if not 1 <= value <= 8:
        raise ValueError('WORKER_CONCURRENCY must be between 1 and 8')
    return value


def next_job(excluded):
    with accounts.database() as db:
        placeholders = ','.join('?' for _ in excluded)
        exclude = f' AND id NOT IN ({placeholders})' if excluded else ''
        return db.execute("SELECT id,start FROM jobs WHERE status='queued'" + exclude +
                          ' ORDER BY created,id LIMIT 1', tuple(excluded)).fetchone()


class GradingQueue:
    """Bound outstanding futures as well as running calls; leave excess jobs in DB."""
    def __init__(self, executor, limit):
        self.executor, self.limit = executor, limit
        self.active = {}

    def dispatch(self):
        for ident, future in list(self.active.items()):
            if future.done():
                del self.active[ident]
                try:
                    future.result()
                except Exception:
                    logging.exception('Grading task failed: %s', ident)
        while running and len(self.active) < self.limit:
            job = next_job(self.active)
            if not job:
                break
            # run_job claims the job atomically and owns its heartbeat/settlement.
            self.active[job['id']] = self.executor.submit(app.run_job, job['id'], job['start'])


def maintain():
    saas.recover()
    payments.reconcile()


def main():
    global running
    running = True
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    limit = concurrency()
    logging.info('Grading worker started with concurrency=%s', limit)
    saas.recover()
    # Payment queries run independently so network delays cannot block dispatch.
    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix='grading') as executor, \
            ThreadPoolExecutor(max_workers=1, thread_name_prefix='maintenance') as maintenance:
        queue = GradingQueue(executor, limit)
        future, next_maintenance = None, 0
        while running:
            try:
                if future is not None and future.done():
                    try:
                        future.result()
                    except Exception:
                        logging.exception('Worker maintenance failed')
                    future = None
                if future is None and time.monotonic() >= next_maintenance:
                    future = maintenance.submit(maintain)
                    next_maintenance = time.monotonic() + 30
                queue.dispatch()
                time.sleep(0.2 if queue.active else 2)
            except Exception:
                logging.exception('Worker dispatch failed')
                time.sleep(5)
        logging.info('Worker stopping; waiting for active grading tasks to finish')


if __name__ == '__main__':
    main()
