# SYCRO Financial — Free Hosting Deployment

## Recommended: Render Free Web Service

This build is optimized for Render's Free Web Service.

### Render
Service type: Web Service
Plan: Free

Build command:
`pip install --no-cache-dir -r requirements.txt`

Start command:
`gunicorn --workers 1 --threads 2 --timeout 90 --max-requests 500 --max-requests-jitter 50 app:app`

Health check:
`/health`

Environment variables:
- `SECRET_KEY` — Render can generate this automatically from `render.yaml`
- `DB_DIR` — `/tmp/sycro`
- `PYTHONUNBUFFERED` — `1`
- `PYTHONDONTWRITEBYTECODE` — `1`

Do not configure a persistent disk on the Free plan.

### GitHub → Render workflow

1. Create a GitHub repository.
2. Upload the contents of this ZIP to the repository (do not upload the ZIP as a nested archive).
3. In Render, choose **New → Web Service**.
4. Select the GitHub repository.
5. Choose **Free**.
6. Use the build/start commands above.
7. Add or import the environment variables.
8. Deploy.
9. Test `https://YOUR-SERVICE.onrender.com/health`.
10. Open the application URL.

### Important database note

The current educational build uses SQLite. Render Free has no persistent disk, so SQLite data can reset after a restart, spin-down, or redeploy.

If durable data is required, the next architecture should move the database to PostgreSQL.

## Alternative: PythonAnywhere

PythonAnywhere offers a free Python web-app option with private file storage, which can be a better fit for a small SQLite-based Flask teaching project when persistent local files matter. Its free plan has restrictions, including limited outbound internet access. Check the current plan before relying on external email/payment integrations.

## Alternative: Koyeb

Koyeb supports Flask deployments and offers a free instance with 512 MB RAM, 0.1 vCPU and 2 GB SSD. It is another option for lightweight Flask deployments, but verify current free-tier storage/lifecycle limits before using it for persistent application data.

## Production upgrade path

For a real persistent deployment:
Flask app → Gunicorn → PostgreSQL → external object storage for uploads → managed secrets.

This project is an educational Flask application and should not be used as a real banking/financial service.
