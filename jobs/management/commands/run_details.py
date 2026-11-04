import threading
import time

from django import db
from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.scraper.details import claim_jobs, handle_job
from jobs.scraper.http import LinkedInClient, RateLimited


class Command(BaseCommand):
    help = "Часть 2: сбор полных данных вакансий и компаний (NEW/FAILED -> DONE)."

    def add_arguments(self, parser):
        parser.add_argument("--workers", type=int, default=1)
        parser.add_argument("--limit", type=int, default=0, help="Максимум вакансий за запуск (0 = все)")
        parser.add_argument("--batch-size", type=int, default=10)
        parser.add_argument("--query-id", type=int, help="Только вакансии этого поискового запроса")
        parser.add_argument("--retry-failed", action="store_true",
                            help="Сбросить счётчик попыток у FAILED-вакансий")

    def handle(self, *args, **opts):
        if opts["retry_failed"]:
            n = Job.objects.filter(status=Job.Status.FAILED).update(status=Job.Status.NEW, attempts=0)
            self.stdout.write(f"reset {n} failed jobs")

        stop, lock = threading.Event(), threading.Lock()
        stats = {"claimed": 0, "done": 0, "rate_limited_in_row": 0}

        def worker():
            client = LinkedInClient()
            try:
                while not stop.is_set():
                    with lock:
                        left = (opts["limit"] - stats["claimed"]) if opts["limit"] else opts["batch_size"]
                        take = min(opts["batch_size"], left)
                        if take <= 0:
                            return
                        jobs = claim_jobs(take, opts["query_id"])
                        stats["claimed"] += len(jobs)
                    if not jobs:
                        return
                    for i, job in enumerate(jobs):
                        if stop.is_set():
                            Job.objects.filter(pk__in=[j.pk for j in jobs[i:]]).update(status=Job.Status.NEW)
                            return
                        try:
                            handle_job(job, client)
                            with lock:
                                stats["done"] += 1
                                stats["rate_limited_in_row"] = 0
                        except RateLimited:
                            with lock:
                                stats["rate_limited_in_row"] += 1
                                too_many = stats["rate_limited_in_row"] >= 5
                            if too_many:
                                self.stderr.write("Слишком много блокировок подряд — остановка. Повторите позже/с прокси.")
                                stop.set()
                                break
                            time.sleep(settings.RATE_LIMIT_COOLDOWN)
                        if stats["done"] and stats["done"] % 50 == 0:
                            self.stdout.write(f"processed: {stats['done']}")
            finally:
                db.connections.close_all()

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, opts["workers"]))]
        for t in threads:
            t.start()
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            stop.set()
            for t in threads:
                t.join()
        left = Job.objects.filter(status__in=[Job.Status.NEW, Job.Status.PROCESSING]).count()
        self.stdout.write(f"finished: processed={stats['done']}, still pending={left}")
