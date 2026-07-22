# Waste Management Online Form

Flask + SQLite app for tracking waste quantities by stock item.

## Run locally

1. Create a virtual environment.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3. Start the app:

```bash
flask --app app run
```

## What it does

- Loads stock items from `Stock Items.csv` the first time the database is created.
- Lets you add or delete active stock items.
- Lets you enter waste quantities and save them as a reusable form.
- Provides a saved forms page with view, edit, delete, CSV export, and PDF export.
