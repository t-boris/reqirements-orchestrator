#!/bin/bash
# =============================================================================
# MARO Deployment Script
# Builds via Cloud Build and deploys to GCE VM
# =============================================================================

set -e

# -----------------------------------------------------------------------------
# Configuration (override via environment or .deploy.env)
# -----------------------------------------------------------------------------
if [ -f ".deploy.env" ]; then
    source .deploy.env
fi

GCP_PROJECT="${GCP_PROJECT:?Error: GCP_PROJECT not set}"
GCE_INSTANCE="${GCE_INSTANCE:?Error: GCE_INSTANCE not set}"
GCE_ZONE="${GCE_ZONE:-us-central1-a}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-maro}"

IMAGE="${REGION}-docker.pkg.dev/${GCP_PROJECT}/${REPO}/maro:latest"

echo "=========================================="
echo "MARO Deployment"
echo "=========================================="
echo "Project:  ${GCP_PROJECT}"
echo "Instance: ${GCE_INSTANCE}"
echo "Zone:     ${GCE_ZONE}"
echo "Image:    ${IMAGE}"
echo "=========================================="
echo ""

# -----------------------------------------------------------------------------
# Step 1: Build and push via Cloud Build
# -----------------------------------------------------------------------------
echo "Step 1: Building image via Cloud Build..."
gcloud builds submit \
    --project="${GCP_PROJECT}" \
    --config=cloudbuild.yaml \
    --substitutions="_REGION=${REGION},_REPO=${REPO}" \
    .

echo ""
echo "Image built and pushed to Artifact Registry"
echo ""

# -----------------------------------------------------------------------------
# Step 2: Deploy to VM via SSH
# -----------------------------------------------------------------------------
echo "Step 2: Deploying to VM..."

gcloud compute ssh "${GCE_INSTANCE}" \
    --project="${GCP_PROJECT}" \
    --zone="${GCE_ZONE}" \
    --command="cd /opt/maro && \
        docker-compose pull && \
        docker-compose up -d && \
        docker-compose ps"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Check status:"
echo "  gcloud compute ssh ${GCE_INSTANCE} --zone=${GCE_ZONE} --command='cd /opt/maro && docker-compose logs -f'"
echo ""
