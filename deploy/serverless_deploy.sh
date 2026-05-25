#!/usr/bin/env bash
# Serverless deploy: build the image, create two Cloud Run Jobs (capture +
# lab-cycle), and schedule them. Secrets live in Secret Manager. No VMs.
#
#   KALSHI_KEY_ID / KALSHI_PEM  → read by kalshi_creds.py
#   GITHUB_TOKEN                → lets the jobs push results (board + data)
#
# Prereqs: gcloud authed; secrets already created (see comments). Run from repo root.
set -euo pipefail
PROJECT="${PROJECT:-project-zion-454116}"
REGION="${REGION:-us-central1}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/lab/kalshi-lab:latest"
SA="kalshi-lab@$PROJECT.iam.gserviceaccount.com"

echo "== enable APIs =="
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  --project="$PROJECT"

echo "== Artifact Registry repo =="
gcloud artifacts repositories create lab --repository-format=docker \
  --location="$REGION" --project="$PROJECT" 2>/dev/null || echo "(repo exists)"

echo "== build image (Cloud Build) =="
gcloud builds submit --tag "$IMAGE" --project="$PROJECT" .

echo "== service account for the jobs + scheduler =="
gcloud iam service-accounts create kalshi-lab --project="$PROJECT" 2>/dev/null || echo "(sa exists)"
for s in KALSHI_KEY_ID KALSHI_PEM GITHUB_TOKEN; do
  gcloud secrets add-iam-policy-binding "$s" --project="$PROJECT" \
    --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" >/dev/null 2>&1 || true
done

echo "== create/update Cloud Run Jobs =="
COMMON=(--image="$IMAGE" --region="$REGION" --project="$PROJECT" \
  --service-account="$SA" --max-retries=0 --memory=1Gi --cpu=1 \
  --set-secrets=KALSHI_KEY_ID=KALSHI_KEY_ID:latest,KALSHI_PEM=KALSHI_PEM:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest)
gcloud run jobs deploy kalshi-capture  "${COMMON[@]}" --task-timeout=8h  --args=capture
gcloud run jobs deploy kalshi-labcycle "${COMMON[@]}" --task-timeout=30m --args=lab-cycle

echo "== allow scheduler to run the jobs =="
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA" --role="roles/run.developer" >/dev/null 2>&1 || true

RUNJOB="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs"
echo "== schedule (cron, UTC) =="
# capture: a couple of windows covering NBA/WNBA tip-offs (adjust freely)
gcloud scheduler jobs create http capture-evening --project="$PROJECT" --location="$REGION" \
  --schedule="0 23 * * *" --uri="$RUNJOB/kalshi-capture:run" --http-method=POST \
  --oauth-service-account-email="$SA" 2>/dev/null || echo "(capture-evening exists)"
gcloud scheduler jobs create http labcycle-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 9 * * *" --uri="$RUNJOB/kalshi-labcycle:run" --http-method=POST \
  --oauth-service-account-email="$SA" 2>/dev/null || echo "(labcycle-daily exists)"

echo "== done. Trigger a test run with: =="
echo "   gcloud run jobs execute kalshi-capture --region=$REGION --project=$PROJECT"
