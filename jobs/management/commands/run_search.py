from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from jobs.models import SearchQuery
from jobs.scraper.search import run_search


class Command(BaseCommand):
    help = "Часть 1: поиск вакансий по активным поисковым запросам (возобновляемый)."

    def add_arguments(self, parser):
        parser.add_argument("--query-id", type=int, help="Только этот запрос")
        parser.add_argument("--rescan", action="store_true",
                            help="Сбросить прогресс и пройти запрос заново (найти новые вакансии)")

    def handle(self, *args, **opts):
        qs = SearchQuery.objects.filter(is_active=True)
        if opts["query_id"]:
            qs = qs.filter(pk=opts["query_id"])
        for query in qs.order_by("id"):
            if opts["rescan"]:
                query.progress, query.status = {}, SearchQuery.Status.IDLE
                query.save()
            if query.status == SearchQuery.Status.DONE:
                self.stdout.write(f"skip (done): {query}")
                continue
            if query.status == SearchQuery.Status.RUNNING and query.updated_at > timezone.now() - timedelta(minutes=5):
                self.stdout.write(f"skip (already running): {query}")
                continue
            ok = run_search(query)
            self.stdout.write(f"{'OK' if ok else 'INTERRUPTED'}: {query} -> {query.jobs_found} jobs")
