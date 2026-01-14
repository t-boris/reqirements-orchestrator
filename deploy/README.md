# MARO Deployment

## Prerequisites

### 1. GCE VM Setup

```bash
# Create VM (if not exists)
gcloud compute instances create maro-vm \
    --project=YOUR_PROJECT \
    --zone=us-central1-a \
    --machine-type=e2-small \
    --image-family=debian-12 \
    --image-project=debian-cloud

# SSH into VM and run setup
gcloud compute ssh maro-vm --zone=us-central1-a
# Then run: curl -fsSL https://get.docker.com | sh
# Add user to docker group: sudo usermod -aG docker $USER
# Log out and back in
```

### 2. Artifact Registry Setup

```bash
# Create repository
gcloud artifacts repositories create maro \
    --project=YOUR_PROJECT \
    --repository-format=docker \
    --location=us-central1

# Configure Docker auth
gcloud auth configure-docker us-central1-docker.pkg.dev
```

### 3. VM Configuration

```bash
# On the VM
sudo mkdir -p /opt/maro
sudo chown $USER:$USER /opt/maro
cd /opt/maro

# Copy .env file (with your secrets)
# Copy docker-compose.yml
```

## Deployment

```bash
# From local machine
./deploy.sh
```

## Monitoring

```bash
# View logs
gcloud compute ssh maro-vm --command='cd /opt/maro && docker-compose logs -f bot'

# Check health
gcloud compute ssh maro-vm --command='curl -s localhost:8000/health'

# Restart services
gcloud compute ssh maro-vm --command='cd /opt/maro && docker-compose restart'
```
