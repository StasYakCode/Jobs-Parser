from django.db import models


class SearchQuery(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Ожидает"
        RUNNING = "running", "Выполняется"
        DONE = "done", "Завершён"
        FAILED = "failed", "Ошибка (можно продолжить)"

    keywords = models.CharField("Поисковый запрос", max_length=255)
    country = models.CharField("Страна / локация", max_length=128)
    geo_id = models.CharField("LinkedIn geoId (необязательно)", max_length=32, blank=True)
    max_jobs = models.PositiveIntegerField("Лимит вакансий (0 = без лимита)", default=0)
    is_active = models.BooleanField("Активен", default=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDLE, db_index=True)
    progress = models.JSONField("Прогресс (для возобновления)", default=dict, blank=True)
    jobs_found = models.PositiveIntegerField("Найдено вакансий", default=0)
    last_error = models.TextField(blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Поисковый запрос"
        verbose_name_plural = "Поисковые запросы"
        constraints = [models.UniqueConstraint(fields=["keywords", "country"], name="uniq_query_country")]

    def __str__(self):
        return f"{self.keywords} — {self.country}"


class Company(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новая"
        PROCESSING = "processing", "В обработке"
        DONE = "done", "Готово"
        FAILED = "failed", "Ошибка"

    slug = models.CharField("LinkedIn slug", max_length=255, unique=True)
    name = models.CharField(max_length=500, blank=True)
    url = models.URLField(max_length=500, blank=True)
    website = models.CharField(max_length=500, blank=True)
    industry = models.CharField(max_length=255, blank=True)
    company_size = models.CharField(max_length=100, blank=True)
    employees_count = models.PositiveIntegerField(null=True, blank=True)
    followers = models.PositiveIntegerField(null=True, blank=True)
    headquarters = models.CharField(max_length=500, blank=True)
    address = models.CharField(max_length=500, blank=True)
    founded = models.CharField(max_length=32, blank=True)
    specialties = models.TextField(blank=True)
    description = models.TextField(blank=True)
    logo_url = models.TextField(blank=True)
    raw = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Компания"
        verbose_name_plural = "Компании"

    def __str__(self):
        return self.name or self.slug


class Job(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новая (ждёт Details)"
        PROCESSING = "processing", "В обработке"
        DONE = "done", "Обработана"
        FAILED = "failed", "Ошибка"
        NOT_FOUND = "not_found", "Удалена (404)"

    job_id = models.CharField("LinkedIn job ID", max_length=32, unique=True)
    queries = models.ManyToManyField(SearchQuery, related_name="jobs", verbose_name="Поисковые запросы")
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs")

    # Search data
    title = models.CharField(max_length=500, blank=True)
    company_name = models.CharField(max_length=500, blank=True)
    location = models.CharField(max_length=500, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    listed_at = models.DateField(null=True, blank=True)

    # Details data
    posted_text = models.CharField(max_length=100, blank=True)
    employment_type = models.CharField(max_length=100, blank=True)
    seniority_level = models.CharField(max_length=100, blank=True)
    job_function = models.CharField(max_length=500, blank=True)
    industries = models.CharField(max_length=500, blank=True)
    applicants_text = models.CharField(max_length=100, blank=True)
    applicants_count = models.PositiveIntegerField(null=True, blank=True)
    salary = models.CharField(max_length=255, blank=True)
    apply_url = models.TextField(blank=True)
    valid_through = models.DateField(null=True, blank=True)
    description_html = models.TextField(blank=True)
    description_text = models.TextField(blank=True)
    raw = models.JSONField(default=dict, blank=True)

    
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Вакансия"
        verbose_name_plural = "Вакансии"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.title} ({self.job_id})"
