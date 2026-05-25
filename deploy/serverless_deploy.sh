#!/usr/bin/env bash
# Serverless deploy: build the image, create two Cloud Run Jobs (capture +
# lab-cycle), schedule them. Secrets in Secret Manager. No VMs.
# Resource names are intentionally neutral (data-*, mkt-*) to blend into the host
# account; env vars inside the job stay KALSHI_*/GITHUB_TOKEN for the code.
set -euo pipefail
PROJECT="${PROJECT:-project-zion-454116}"
REGION="${REGION:-us-central1}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/apps/market-lab:latest"
SA="data-jobs@$PROJECT.iam.gserviceaccount.com"

echo "== enable APIs =="
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  --project="$PROJECT"

echo "== Artifact Registry repo =="
gcloud artifacts repositories create apps --repository-format=docker \
  --location="$REGION" --project="$PROJECT" 2>/dev/null || echo "(repo exists)"

echo "== service account =="
gcloud iam service-accounts create data-jobs --project="$PROJECT" 2>/dev/null || echo "(sa exists)"
for s in mkt-key-id mkt-pem gh-token; do
  gcloud secrets add-iam-policy-binding "$s" --project="$PROJECT" \
    --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" >/dev/null 2>&1 || true
done

echo "== build image (Cloud Build) =="
gcloud builds submit --tag "$IMAGE" --project="$PROJECT" .

SECRETS="KALSHI_KEY_ID=mkt-key-id:latest,KALSHI_PEM=mkt-pem:latest,GITHUB_TOKEN=gh-token:latest"
COMMON=(--image="$IMAGE" --region="$REGION" --project="$PROJECT" \
  --service-account="$SA" --max-retries=0 --memory=1Gi --cpu=1 --set-secrets="$SECRETS")
echo "== create/update Cloud Run Jobs =="
gcloud run jobs deploy data-capture "${COMMON[@]}" --task-timeout=8h  --args=capture
gcloud run jobs deploy data-cycle   "${COMMON[@]}" --task-timeout=30m --args=lab-cycle

echo "== allow scheduler to run the jobs =="
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA" --role="roles/run.developer" >/dev/null 2>&1 || true

RUNJOB="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs"
echo "== schedule (cron, UTC; adjust to tip-off windows) =="
gcloud scheduler jobs create http data-evening --project="$PROJECT" --location="$REGION" \
  --schedule="0 23 * * *" --uri="$RUNJOB/data-capture:run" --http-method=POST \
  --oauth-service-account-email="$SA" 2>/dev/null || echo "(data-evening exists)"
gcloud scheduler jobs create http data-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 9 * * *" --uri="$RUNJOB/data-cycle:run" --http-method=POST \
  --oauth-service-account-email="$SA" 2>/dev/null || echo "(data-daily exists)"

echo "== done. Test: gcloud run jobs execute data-capture --region=$REGION --project=$PROJECT =="
