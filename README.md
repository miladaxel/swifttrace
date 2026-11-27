# OhMyFin

OhMyFin is a Django web application. This package is configured for local development with SQLite.

## Requirements

- Python 3.11
- pip
- Node.js is optional; it is only needed to rebuild the Tailwind CSS file.

## Run locally

1. Extract this archive and open a terminal in the `ohmyfin` folder.
2. Create and activate a virtual environment:

   **Windows (PowerShell)**
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   **macOS / Linux**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

3. Install Python packages and initialize the local database:

   ```bash
   python -m pip install -r requirements-dev.txt
   python manage.py migrate
   ```

4. Start the development server:

   ```bash
   python manage.py runserver
   ```

5. Open <http://127.0.0.1:8000/> in your browser.

Django Debug Toolbar is enabled locally when `DJANGO_DEBUG` is true (the default).
Production installs use `requirements.txt` and must set `DJANGO_DEBUG=false`.

To create an admin account, run `python manage.py createsuperuser`. The generated local SQLite database is created in the project folder.

## Optional: rebuild CSS

The compiled CSS is included. If you change Tailwind classes or templates, install Node.js and run:

```bash
npm ci
npm run build:css
```
