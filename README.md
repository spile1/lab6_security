# Лабораторна робота № 6. Тестування безпеки, стійкості до мережевих помилок, CI

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt

python shop_app/app.py             # термінал 1: навчальний API на http://localhost:8000
python -m pytest -v                # термінал 2: тести
```

Workflow GitHub Actions: `.github/workflows/tests.yml` (запускається після push і pull request).
