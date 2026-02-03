# OLT Dashboard

Scraper OLT HIOSO & VSOL → PostgreSQL → Dashboard Flask

## Run
```bash
source venv/bin/activate
python scraper/scraper_hioso.py
python db/json_to_db.py
python dashboard/app.py
