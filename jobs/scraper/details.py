"""Часть 2 — Details: догружает полные данные вакансий и компаний.

Работает только с таблицами БД (берёт вакансии со статусом NEW/FAILED), поэтому полностью
независима от Search. Захват задач через SELECT ... FOR UPDATE SKIP LOCKED позволяет
запускать несколько воркеров параллельно без дублирования работы.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from jobs.models import Company, Job
from .http import AuthWall, FetchError, NotFound, RateLimited
from .parsers import parse_company, parse_job_detail

log = logging.getLogger(__name__)

JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
COMPANY_URL = "https://www.linkedin.com/company/{}"

JOB_FIELDS = ["title", "company_name", "location", "posted_text", "employment_type", "seniority_level",
              "job_function", "industries", "applicants_text", "applicants_count", "salary", "apply_url",
              "valid_through", "description_html", "description_text"]


def _stale_cutoff():
    return timezone.now() - timedelta(minutes=settings.STALE_LOCK_MINUTES)


def claim_jobs(n, query_id=None):
    """Атомарно забирает до n вакансий и помечает их PROCESSING."""
    claimable = (Q(status=Job.Status.NEW)
                 | Q(status=Job.Status.FAILED, attempts__lt=settings.MAX_ATTEMPTS)
                 | Q(status=Job.Status.PROCESSING, updated_at__lt=_stale_cutoff()))
    with transaction.atomic():
        qs = Job.objects.select_for_update(skip_locked=True).filter(claimable)
        if query_id:
            qs = qs.filter(queries__id=query_id)
        jobs = list(qs.order_by("id")[:n])
        Job.objects.filter(pk__in=[j.pk for j in jobs]).update(
            status=Job.Status.PROCESSING, updated_at=timezone.now())
    return jobs


def _claim_company(company):
    claimable = (Q(status__in=[Company.Status.NEW, Company.Status.FAILED], attempts__lt=settings.MAX_ATTEMPTS)
                 | Q(status=Company.Status.PROCESSING, updated_at__lt=_stale_cutoff()))
    return Company.objects.filter(claimable, pk=company.pk).update(
        status=Company.Status.PROCESSING, updated_at=timezone.now()) == 1


def process_company(company, client):
    if not _claim_company(company):
        return
    company.refresh_from_db()
    try:
        data = parse_company(client.get(COMPANY_URL.format(company.slug)))
        for k, v in data.items():
            setattr(company, k, v)
        if not data:
            raise FetchError("company page has no parsable data")
        company.status, company.last_error = Company.Status.DONE, ""
    except RateLimited:
        company.status = Company.Status.NEW   # не считаем попыткой
        company.save()
        raise
    except (AuthWall, NotFound, FetchError, Exception) as exc:  # компания — best effort
        company.attempts += 1
        company.status, company.last_error = Company.Status.FAILED, str(exc)[:1000]
        log.warning("company %s failed: %s", company.slug, exc)
    company.save()


def process_job(job, client):
    data = parse_job_detail(client.get(JOB_URL.format(job.job_id)))
    if not data.get("title") and not data.get("description_text"):
        raise FetchError("job page has no parsable data")
    for field in JOB_FIELDS:
        if data.get(field) not in (None, ""):
            setattr(job, field, data[field])
    if data.get("raw"):
        job.raw = data["raw"]
    if data.get("listed_at") and not job.listed_at:
        job.listed_at = data["listed_at"]

    slug = data.get("company_slug")
    if slug and (not job.company_id or job.company.slug != slug):
        company, _ = Company.objects.get_or_create(
            slug=slug, defaults={"name": data.get("company_name", ""), "url": data.get("company_url", "")})
        job.company = company
    job.status, job.last_error, job.processed_at = Job.Status.DONE, "", timezone.now()
    job.attempts += 1
    job.save()


def handle_job(job, client):
    """Обработка одной вакансии со всеми переходами статусов. RateLimited пробрасывается наверх."""
    try:
        process_job(job, client)
    except NotFound:
        job.status, job.last_error = Job.Status.NOT_FOUND, "HTTP 404"
        job.save()
        return
    except RateLimited:
        job.status = Job.Status.NEW
        job.save()
        raise
    except Exception as exc:
        job.attempts += 1
        job.status, job.last_error = Job.Status.FAILED, str(exc)[:1000]
        job.save()
        log.warning("job %s failed (attempt %s): %s", job.job_id, job.attempts, exc)
        return
    if job.company_id:
        process_company(job.company, client)
