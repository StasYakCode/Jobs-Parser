import subprocess
import sys

from django.conf import settings
from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Company, Job, SearchQuery


def _spawn(*args):
    log = open(settings.BASE_DIR / "logs" / "admin_runs.log", "a")
    subprocess.Popen([sys.executable, str(settings.BASE_DIR / "manage.py"), *args], stdout=log,
                     stderr=subprocess.STDOUT, cwd=settings.BASE_DIR, start_new_session=True)


@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    list_display = ("keywords", "country", "is_active", "status", "jobs_found", "max_jobs", "last_run_at")
    list_editable = ("is_active",)
    list_filter = ("status", "country", "is_active")
    search_fields = ("keywords", "country")
    readonly_fields = ("status", "progress", "jobs_found", "last_error", "last_run_at", "created_at", "updated_at")
    actions = ["start_search", "start_details", "reset_progress"]

    @admin.action(description="▶ Запустить / продолжить Search (в фоне)")
    def start_search(self, request, queryset):
        for q in queryset:
            _spawn("run_search", "--query-id", str(q.pk))
        self.message_user(request, f"Запущено запросов: {queryset.count()} (лог: logs/admin_runs.log)")

    @admin.action(description="▶ Запустить Details для вакансий этих запросов (в фоне)")
    def start_details(self, request, queryset):
        for q in queryset:
            _spawn("run_details", "--query-id", str(q.pk))
        self.message_user(request, "Details запущен в фоне")

    @admin.action(description="↺ Сбросить прогресс (пересканировать с нуля)")
    def reset_progress(self, request, queryset):
        queryset.update(progress={}, status=SearchQuery.Status.IDLE, last_error="")
        self.message_user(request, "Прогресс сброшен", level=messages.WARNING)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "title", "company_name", "location", "employment_type", "seniority_level",
                    "listed_at", "status", "attempts")
    list_filter = ("status", "queries", "queries__country", "employment_type", "seniority_level", "listed_at")
    search_fields = ("job_id", "title", "company_name", "location", "description_text")
    list_select_related = ("company",)
    raw_id_fields = ("company",)
    readonly_fields = ("job_id", "linkedin_link", "created_at", "updated_at", "processed_at", "raw")
    exclude = ("description_html",)
    actions = ["reset_to_new"]
    list_per_page = 50
    show_full_result_count = False  # быстрее на больших таблицах

    @admin.display(description="Ссылка")
    def linkedin_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.url, obj.url) if obj.url else "-"

    @admin.action(description="↺ Вернуть в очередь Details (NEW)")
    def reset_to_new(self, request, queryset):
        n = queryset.update(status=Job.Status.NEW, attempts=0, last_error="")
        self.message_user(request, f"Возвращено в очередь: {n}")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "industry", "company_size", "headquarters", "website", "status")
    list_filter = ("status", "industry", "company_size")
    search_fields = ("name", "slug", "website")
    readonly_fields = ("raw", "created_at", "updated_at")
    actions = ["reset_to_new"]

    @admin.action(description="↺ Повторить сбор данных компании")
    def reset_to_new(self, request, queryset):
        queryset.update(status=Company.Status.NEW, attempts=0, last_error="")
