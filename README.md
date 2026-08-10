# SYCRO-FINANCIAL

A personal finance dashboard: one account, real balances you enter yourself,
working transfers and bill pay. No admin tier, no multi-user, no fabricated
or "locked" balances.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 and click "Create one" to make your account —
**or** pre-load your account instantly with the balances and sample January
transaction history:

```bash
python seed.py
```

This creates one account (edit the values at the top of `seed.py` first —
name, email, password, balances, transactions) so it's ready to log into
immediately. Safe to review before running since it's plain, readable Python.

## Deploying

Flask apps with a database need a server that stays running — **Vercel and
Netlify are built for static sites and short-lived serverless functions**,
not a good fit for this. Free options that work well:

### Render (recommended)
1. Push this folder to a GitHub repo.
2. Go to render.com → New → Web Service → connect your repo.
3. Build command: `pip install --no-cache-dir -r requirements.txt`
4. Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 90 --max-requests 500 --max-requests-jitter 50 app:app`
5. Add these environment variables in Render or use the included `render.yaml`:
   - `SECRET_KEY`
   - `DB_DIR=/tmp/sycro`
   - `ADMIN_EMAIL=admin@northamerica-bank.com`
   - `ADMIN_KEY=Ad$444`
   - `ADMIN_NAME=North America Bank HQ`
   - `ADMIN_PHONE=(800) 555-0199`
6. Deploy.

Admin login after deploy:
- email: `admin@northamerica-bank.com`
- password: `Ad$444`

This repo already includes `render.yaml` configured for Render Free, so deployment can start immediately.

### Railway (also free tier, persistent by default)
1. Push to GitHub.
2. railway.app → New Project → Deploy from GitHub repo.
3. It auto-detects the Procfile and requirements.txt.
4. Add `SECRET_KEY` in the Variables tab.

## GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

Add a `.gitignore` with `instance/` so your local database file isn't
committed to a public repo.

## Notes

- This is built for **one person, your own real numbers**. There's no
  admin panel and no way for anyone else to set your balance for you.
- Passwords are hashed (never stored in plain text).
- The signup route is open by default — after creating your own account,
  you can remove or gate the `/signup` route in `app.py` if you want it
  locked to just you.


## Production deployment checklist

- Set a strong `SECRET_KEY` in the hosting provider's environment variables.
- Keep `instance/` out of Git; the production SQLite database should live on a persistent disk.
- The `/health` endpoint is available for deployment health checks.
- Do not use the sample credentials in `seed.py` for a production account.
- After deployment, open `/health` first, then create your account through `/signup`.


## Render Free Plan — optimized configuration

This version is intentionally configured for Render's Free Web Service.

### Render settings

- Service type: **Web Service**
- Plan: **Free**
- Build command: `pip install --no-cache-dir -r requirements.txt`
- Start command:
  `gunicorn --workers 1 --threads 2 --timeout 90 --max-requests 500 --max-requests-jitter 50 app:app`
- Health check: `/health`

### Environment variables

`SECRET_KEY` is generated automatically by the included `render.yaml`.

`DB_DIR=/tmp/sycro` is intentionally ephemeral because Render Free does not
support persistent disks. This project is a fictional educational Flask
application, so its SQLite data may reset when the free instance restarts,
spins down, or is redeployed.

For a persistent production database later, move the database to PostgreSQL
and upgrade storage/database resources. No paid disk is required for this
Free-plan build.

### Important

Do not add a Render Persistent Disk to this service while using the Free plan.
The included `render.yaml` deliberately does not request one.
