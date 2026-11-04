# LinkedIn Jobs Parser (Python + Django + PostgreSQL)

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d db                 
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver              
```

1. В админке → **Поисковые запросы** создайте запросы (напр. `Python Developer` / `United States`, затем ещё одну страну).
2. Search: `python manage.py run_search` (или действие «Запустить Search» в админке).
3. Details: `python manage.py run_details --workers 3`
4. Выгрузка: `python manage.py export_jobs --output jobs.csv` (или `jobs.xlsx`)