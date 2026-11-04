"""Часть 1 — Search: поиск вакансий с пагинацией и сохранение в PostgreSQL.

LinkedIn отдаёт максимум ~1000 результатов на один набор фильтров, поэтому, если базовый
запрос упёрся в лимит, поиск автоматически дробится на срезы (дата публикации × уровень
опыта). Дубли отсекаются по unique job_id. Прогресс хранится в SearchQuery.progress, так что
после сбоя запуск продолжается с того же места.
"""
import logging

from django.db import transaction
from django.utils import timezone

from jobs.models import Company, Job, SearchQuery
from .http import FetchError, LinkedInClient
from .parsers import parse_search_page

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
PAGE_CAP = 1000          
SATURATION = 900         
TIME_FILTERS = ["r86400", "r604800", "r2592000", ""]   
EXPERIENCE_FILTERS = ["1", "2", "3", "4", "5", "6"]    


def slice_plan(progress):
    """Ленивый генератор срезов; решение о дроблении принимается после base-среза."""
    yield "base", {}
    if progress["done"].get("base", 0) < SATURATION:
        return
    for tpr in TIME_FILTERS:
        for exp in EXPERIENCE_FILTERS:
            params = {"f_E": exp}
            if tpr:
                params["f_TPR"] = tpr
            yield f"tpr={tpr or 'any'}|exp={exp}", params


def save_cards(query, cards):
    """Идемпотентное сохранение страницы результатов. Возвращает число новых вакансий."""
    if not cards:
        return 0
    ids = [c["job_id"] for c in cards]
    with transaction.atomic():
        slugs = {c["company_slug"]: c for c in cards if c["company_slug"]}
        have = set(Company.objects.filter(slug__in=slugs).values_list("slug", flat=True))
        Company.objects.bulk_create(
            [Company(slug=s, name=c["company_name"], url=c["company_url"])
             for s, c in slugs.items() if s not in have],
            ignore_conflicts=True)
        company_pk = dict(Company.objects.filter(slug__in=slugs).values_list("slug", "pk"))

        existing = set(Job.objects.filter(job_id__in=ids).values_list("job_id", flat=True))
        new_jobs = [Job(job_id=c["job_id"], title=c["title"], company_name=c["company_name"],
                        location=c["location"], url=c["url"], listed_at=c["listed_at"],
                        company_id=company_pk.get(c["company_slug"]))
                    for c in cards if c["job_id"] not in existing]
        Job.objects.bulk_create(new_jobs, ignore_conflicts=True)

        through = Job.queries.through
        pks = Job.objects.filter(job_id__in=ids).values_list("pk", flat=True)
        through.objects.bulk_create(
            [through(job_id=pk, searchquery_id=query.pk) for pk in pks], ignore_conflicts=True)
    return len(new_jobs)


def _save_state(query, **fields):
    for k, v in fields.items():
        setattr(query, k, v)
    query.save()


def run_search(query: SearchQuery, client=None):
    client = client or LinkedInClient()
    progress = query.progress or {}
    progress.setdefault("done", {})
    _save_state(query, status=SearchQuery.Status.RUNNING, last_error="", last_run_at=timezone.now(),
                progress=progress)
    log.info("search start: %s", query)

    def limit_reached():
        return query.max_jobs and query.jobs.count() >= query.max_jobs

    try:
        for key, extra in slice_plan(progress):
            if key in progress["done"]:
                continue
            cur = progress.get("current") or {}
            resumed = cur.get("key") == key
            start = cur.get("start", 0) if resumed else 0
            count = cur.get("count", 0) if resumed else 0

            while start < PAGE_CAP and not limit_reached():
                params = {"keywords": query.keywords, "location": query.country, "start": start, **extra}
                if query.geo_id:
                    params["geoId"] = query.geo_id
                cards = parse_search_page(client.get(SEARCH_URL, params=params))
                if not cards:
                    break
                new = save_cards(query, cards)
                start += len(cards)
                count += len(cards)
                progress["current"] = {"key": key, "start": start, "count": count}
                _save_state(query, progress=progress, jobs_found=query.jobs.count())
                log.info("[%s] slice=%s start=%s page=%s new=%s", query, key, start, len(cards), new)

            progress["done"][key] = count
            progress["current"] = {}
            _save_state(query, progress=progress, jobs_found=query.jobs.count())
            if limit_reached():
                break
    except FetchError as exc:
        log.error("search interrupted: %s", exc)
        _save_state(query, status=SearchQuery.Status.FAILED, last_error=str(exc)[:2000])
        return False

    _save_state(query, status=SearchQuery.Status.DONE, jobs_found=query.jobs.count())
    log.info("search done: %s, jobs=%s", query, query.jobs_found)
    return True
