#!/usr/bin/env bash
# deploy.sh — Configura el proyecto en GCP y hace el primer deploy a Cloud Run.
# Uso: bash deploy.sh <PROJECT_ID> [REGION] [BUCKET_NAME]
# Ejemplo: bash deploy.sh ml-nube us-central1 ecobici-raw-data

set -euo pipefail

PROJECT_ID="${1:?Debes pasar el PROJECT_ID como primer argumento}"
REGION="${2:-us-central1}"
BUCKET="${3:-ecobici-raw-data}"

SERVICE="ecobici-uploader"
REPO="ecobici-repo"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}"

echo "==> Proyecto: $PROJECT_ID | Región: $REGION | Bucket: $BUCKET"

# Habilitar APIs necesarias
echo "==> Habilitando APIs..."
gcloud services enable \
  run.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project="$PROJECT_ID"

# Crear repositorio en Artifact Registry
echo "==> Creando repositorio en Artifact Registry..."
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID" 2>/dev/null || echo "(ya existe, continuando)"

# Crear bucket de GCS
echo "==> Creando bucket gs://$BUCKET ..."
gcloud storage buckets create "gs://$BUCKET" \
  --project="$PROJECT_ID" \
  --location="$REGION" 2>/dev/null || echo "(ya existe, continuando)"

# Dar al Cloud Build SA permisos para Cloud Run y GCS
CB_SA="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')@cloudbuild.gserviceaccount.com"
echo "==> Asignando roles a Cloud Build SA: $CB_SA"
for ROLE in roles/run.admin roles/iam.serviceAccountUser roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$CB_SA" \
    --role="$ROLE" --quiet
done

# Build y push con Cloud Build
echo "==> Build + push de imagen..."
gcloud builds submit \
  --tag "${IMAGE}:latest" \
  --project="$PROJECT_ID" .

# Primer deploy a Cloud Run
echo "==> Desplegando en Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image "${IMAGE}:latest" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --max-instances 3 \
  --set-env-vars "GCS_BUCKET_NAME=${BUCKET}" \
  --project="$PROJECT_ID"

URL=$(gcloud run services describe "$SERVICE" \
  --region="$REGION" --project="$PROJECT_ID" \
  --format='value(status.url)')

echo ""
echo "✅ Deploy completado."
echo "   URL: $URL"
echo "   Bucket: gs://$BUCKET/raw/"
