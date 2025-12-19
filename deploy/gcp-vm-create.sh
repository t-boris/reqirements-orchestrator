#!/bin/bash
# =============================================================================
# MARO - GCP VM Creation Script
# Creates an e2-small VM with Docker pre-installed
# =============================================================================

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project)}"
ZONE="us-central1-a"
VM_NAME="maro-server"
MACHINE_TYPE="e2-small"

echo "Creating VM in project: $PROJECT_ID"

# Create firewall rules if they don't exist
echo "Setting up firewall rules..."
gcloud compute firewall-rules create allow-http \
    --project="$PROJECT_ID" \
    --allow=tcp:80 \
    --target-tags=http-server \
    --description="Allow HTTP traffic" \
    2>/dev/null || echo "Firewall rule 'allow-http' already exists"

gcloud compute firewall-rules create allow-https \
    --project="$PROJECT_ID" \
    --allow=tcp:443 \
    --target-tags=https-server \
    --description="Allow HTTPS traffic" \
    2>/dev/null || echo "Firewall rule 'allow-https' already exists"

# Create VM
echo "Creating VM: $VM_NAME ($MACHINE_TYPE)..."
gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=20GB \
    --boot-disk-type=pd-standard \
    --tags=http-server,https-server \
    --metadata=startup-script='#!/bin/bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
usermod -aG docker $USER

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p /opt/maro
chown -R $USER:$USER /opt/maro
'

echo ""
echo "VM created successfully!"
echo ""

# Get external IP
EXTERNAL_IP=$(gcloud compute instances describe "$VM_NAME" \
    --zone="$ZONE" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo "=============================================="
echo "VM Details:"
echo "  Name: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Type: $MACHINE_TYPE (2GB RAM)"
echo "  External IP: $EXTERNAL_IP"
echo "=============================================="
echo ""
echo "Next steps:"
echo "1. Wait 2-3 minutes for startup script to complete"
echo "2. SSH into VM:"
echo "   gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""
echo "3. Clone repo and deploy:"
echo "   cd /opt/maro"
echo "   git clone <your-repo> ."
echo "   cp .env.example .env"
echo "   # Edit .env with your secrets"
echo "   docker-compose -f docker-compose.prod.yml up -d"
echo ""
