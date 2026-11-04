import csv
import re

from django.core.management.base import BaseCommand

from jobs.models import Job

JOB_FIELDS = ["job_id", "url", "title", "company_name", "location", "listed_at", "posted_text", "employment_type",
              "seniority_level", "job_function", "industries", "applicants_text", "applicants_count", "salary",
              "apply_url", "valid_through", "description_text", "status", "attempts", "last_error"]
COMPANY_FIELDS = ["slug", "name", "url", "website", "industry", "company_size", "employees_count", "followers",
                  "headquarters", "address", "founded", "specialties", "description", "logo_url", "status"]
ILLEGAL = re.compile(r"[\000-\010\013\014\016-\037]")


class Command(BaseCommand):
    help = "Выгрузка вакансий вместе с данными компаний в CSV или XLSX."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="jobs_export.csv")
        parser.add_argument("--format", choices=["csv", "xlsx"], help="По умолчанию — по расширению файла")
        parser.add_argument("--query-id", type=int)

    def rows(self, query_id):
        qs = Job.objects.select_related("company").prefetch_related("queries").order_by("id")
        if query_id:
            qs = qs.filter(queries__id=query_id)
        yield (["search_queries"] + JOB_FIELDS + [f"company_{f}" for f in COMPANY_FIELDS])
        for job in qs.iterator(chunk_size=500):
            c = job.company
            yield ([" | ".join(str(q) for q in job.queries.all())]
                   + [getattr(job, f) for f in JOB_FIELDS]
                   + [getattr(c, f) if c else "" for f in COMPANY_FIELDS])

    def handle(self, *args, **opts):
        path = opts["output"]
        fmt = opts["format"] or ("xlsx" if path.lower().endswith(".xlsx") else "csv")
        count = 0
        if fmt == "csv":
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                for row in self.rows(opts["query_id"]):
                    writer.writerow(["" if v is None else v for v in row])
                    count += 1
        else:
            from openpyxl import Workbook
            wb = Workbook(write_only=True)
            ws = wb.create_sheet("jobs")
            for row in self.rows(opts["query_id"]):
                ws.append([ILLEGAL.sub("", str(v))[:32000] if v is not None else "" for v in row])
                count += 1
            wb.save(path)
        self.stdout.write(f"exported {count - 1} jobs -> {path}")
