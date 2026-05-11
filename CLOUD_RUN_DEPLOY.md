# HelloDoc Backend Cloud Run Deployment

This guide is for deploying the Django backend from the Google Cloud Console.
It matches the production image in [backend/Dockerfile](Dockerfile) and the startup script in [backend/start.sh](start.sh).

## What the image already does

- Listens on Cloud Run's `PORT` value
- Runs as a non-root user
- Collects static files on startup
- Serves Django with Gunicorn

## Prerequisites

- Google Cloud project created and billing enabled
- A production PostgreSQL database available
- A Redis instance available if you use Celery
- A frontend URL ready for CORS configuration
- Your container image built and pushed to Artifact Registry

## 1. Enable the required APIs

In Google Cloud Console, open **APIs & Services** and enable:

- Cloud Run
- Cloud Build
- Artifact Registry
- Secret Manager
- Cloud SQL Admin, if you use Cloud SQL

## 2. Create an Artifact Registry repository

In **Artifact Registry**, create a Docker repository for the backend image.

Suggested values:

- Repository name: `hellodoc`
- Format: `Docker`
- Location: choose the same region you will use for Cloud Run

Then build and push the backend image. You can do this locally or with Cloud Build.

Example local build:

```bash
cd backend
docker build -t REGION-docker.pkg.dev/PROJECT_ID/hellodoc/backend:latest .
docker push REGION-docker.pkg.dev/PROJECT_ID/hellodoc/backend:latest
```

Example Cloud Build submission:

```bash
gcloud builds submit backend --tag REGION-docker.pkg.dev/PROJECT_ID/hellodoc/backend:latest
```

## 3. Store secrets

In **Secret Manager**, create secrets for the values you do not want to expose directly.

Required secrets or environment variables from `config/settings.py`:

- `SECRET_KEY`
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `REDIS_URL` if Celery or transcription limits are enabled

Common optional secrets:

- `JWT_SECRET`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_STORAGE_BUCKET_NAME`
- `AWS_S3_ENDPOINT_URL`
- `AWS_S3_REGION_NAME`
- `ZOOM_OAUTH_CLIENT_ID`
- `ZOOM_OAUTH_CLIENT_SECRET`
- `ZOOM_OAUTH_ACCOUNT_ID`
- `RECALL_AI_API_KEY`
- `RECALL_AI_WEBHOOK_SECRET`
- `RECALL_SVIX_WEBHOOK_SECRET`
- `SENTRY_DSN`

## 4. Create the Cloud Run service

In **Cloud Run**, click **Create service**.

Use these values:

- Source: **Deploy one revision from an existing container image**
- Container image: select the backend image from Artifact Registry
- Service name: `hellodoc-backend`
- Region: same region as your image repository
- Authentication: choose what fits your setup; public access is common for APIs behind JWT

In the container settings:

- Container port: `8080`
- CPU: `1` or `2`
- Memory: `512 MiB` minimum, `1 GiB` recommended
- Request timeout: `120s` or higher if needed
- Concurrency: `10` to `80` depending on traffic

## 5. Set environment variables

In the service configuration, add these environment variables:

- `DEBUG=false`
- `ENVIRONMENT=production`
- `ALLOWED_HOSTS=<your-cloud-run-domain>`
- `FRONTEND_URL=https://<your-frontend-domain>`

Add secret-backed values for the rest:

- `SECRET_KEY`
- `JWT_SECRET` if used
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `REDIS_URL` if used

If you use S3-compatible storage, set:

- `USE_S3=true`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_STORAGE_BUCKET_NAME`
- `AWS_S3_ENDPOINT_URL`
- `AWS_S3_REGION_NAME`

## 6. Deploy the service

Click **Create** or **Deploy** in the Cloud Run console.

After the revision is ready, copy the service URL and confirm the app responds.

## 7. Run database migrations

Run migrations before sending traffic to production.

Recommended console-friendly options:

### Option A: Cloud Run Job

Create a Cloud Run Job using the same backend image.

Override the command to run:

```bash
python manage.py migrate
```

Provide the same environment variables and secrets as the web service, then execute the job once.

### Option B: Cloud Shell

Open Cloud Shell, clone the repo, and run:

```bash
cd backend
python manage.py migrate
```

Use the same production environment variables in Cloud Shell before running the command.

## 8. Verify the deployment

Open the Cloud Run URL and confirm:

- `/admin/` loads
- `/api/auth/login/` works
- `/api/auth/profile/` responds for an authenticated user
- static files are being served correctly

## 9. Celery workers

Cloud Run service deployments only run the web process.

If you need background jobs, deploy a second Cloud Run service or job with the same image and override the command to run Celery.

Example worker command:

```bash
celery -A config worker -Q default --concurrency=4 --loglevel=info
```

Example AI worker command:

```bash
celery -A config worker -Q ai --concurrency=2 --loglevel=info --max-tasks-per-child=5
```

## 10. Troubleshooting

- If Cloud Run returns a startup error, confirm the container is listening on `8080` and no code hard-codes another port.
- If static files are missing, confirm `collectstatic` completes successfully at startup.
- If uploads fail, verify your storage settings and bucket credentials.
- If auth fails, confirm `ALLOWED_HOSTS` and `FRONTEND_URL` match the deployed domains.
- If AI calls fail, verify `OPENAI_API_KEY` is present in the runtime environment.

## Recommended next step

After the service is deployed, point the frontend to the Cloud Run URL and confirm the onboarding/profile flow can save to `POST /api/auth/profile/`.
