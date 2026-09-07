# DietSync Deployment Guide

This guide covers everything required to push DietSync to GitHub and deploy it across modern cloud environments:
1. [Pushing to GitHub](#1-pushing-to-github)
2. [Architecture & Service Topology](#2-architecture--service-topology)
3. [Option A: One-Command Cloud VPS Deployment (Docker Compose)](#3-option-a-cloud-vps-deployment-docker-compose-recommended)
4. [Option B: Platform-as-a-Service (Railway / Render)](#4-option-b-paas-deployment-railway--render)
5. [Option C: Hybrid (Vercel Frontend + Cloud Backend)](#5-option-c-hybrid-deployment-vercel--cloud-backend)
6. [Production Environment Variables Checklist](#6-production-environment-variables-checklist)
7. [Post-Deployment Verification](#7-post-deployment-verification)

---

## 1. Pushing to GitHub

### Step 1.1: Verify `.gitignore`
Make sure sensitive files (`.env`, virtual environments, build artifacts) are not tracked:
```bash
# Check your git status
git status
```
Confirm that `.env` and `venv/` are listed in `.gitignore` and are **not** staged.

### Step 1.2: Commit and Push
If you haven't created a GitHub repository yet, go to [github.com/new](https://github.com/new) and create a new repository named `dietsync`.

Then, from your project root:
```bash
# Initialize git (if not already done)
git init

# Add all project files
git add .

# Create initial commit
git commit -m "feat: complete clinical decision support engine with doctor mode, async worker, and deployment manifests"

# Rename branch to main
git branch -M main

# Add your GitHub remote (replace with your actual GitHub username)
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/dietsync.git

# Push to GitHub
git push -u origin main
```

Upon pushing, the GitHub Actions CI workflow in [`.github/workflows/ci.yml`](file:///.github/workflows/ci.yml) will automatically run tests and verify the frontend build.

---

## 2. Architecture & Service Topology

DietSync consists of 5 services:

```
[Internet Users / Physicians]
             │
             ▼
    ┌─────────────────┐
    │  Nginx / Caddy  │ (Port 80 / 443 with SSL)
    └────────┬────────┘
             │
    ┌────────┴──────────────────────────┐
    ▼                                   ▼
┌──────────────────┐           ┌──────────────────┐
│  React Frontend  │           │   FastAPI API    │ (:8000)
│  (Vite SPA Dist) │           │  (REST & WebSoc) │
└──────────────────┘           └────────┬─────────┘
                                        │
                         ┌──────────────┴──────────────┐
                         ▼                             ▼
                 ┌───────────────┐             ┌───────────────┐
                 │ PostgreSQL 16 │             │   RabbitMQ    │
                 │  (Data Store) │             │ (Task Queue)  │
                 └───────▲───────┘             └───────┬───────┘
                         │                             │
                         └──────────────┬──────────────┘
                                        │
                               ┌────────┴────────┐
                               │ Async Worker    │
                               │ (worker.consumer)
                               └─────────────────┘
```

---

## 3. Option A: Cloud VPS Deployment (Docker Compose) — *Recommended*

This is the cleanest, most cost-effective approach for production. It runs all 5 services with a single command on any VPS (DigitalOcean Droplet, Hetzner, AWS EC2, or Linode) running Ubuntu 22.04 or 24.04 LTS.

### Step 3.1: Provision VPS & Install Docker
SSH into your server:
```bash
ssh root@YOUR_SERVER_IP
```

Install Docker & Docker Compose:
```bash
# Update packages
apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Verify installation
docker --version
docker compose version
```

### Step 3.2: Clone Repository on the Server
```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/dietsync.git
cd dietsync
```

### Step 3.3: Configure Production `.env`
Create your production `.env` file:
```bash
cat << 'EOF' > .env
POSTGRES_DB=dietsync
POSTGRES_USER=dietsync_admin
POSTGRES_PASSWORD=generate_a_strong_password_here_123!
RABBITMQ_USER=dietsync_rabbit
RABBITMQ_PASSWORD=generate_another_strong_password_here_456!

OPENAI_API_KEY=sk-your-actual-openai-api-key

LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=dietsync
EOF
```

### Step 3.4: Launch with Production Docker Compose
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

This single command:
1. Starts PostgreSQL 16 and RabbitMQ with persistent disk volumes.
2. Builds the Python container for the API and executes database migrations (`alembic upgrade head`).
3. Seeds the curated demo set (`python scripts/demo_seed.py`).
4. Starts the background LangGraph worker (`worker.consumer`).
5. Builds the React frontend and starts Nginx on port 80.

Check running containers:
```bash
docker compose -f docker-compose.prod.yml ps
```

### Step 3.5: Set Up Free HTTPS (Let's Encrypt with Caddy)
For a custom domain (e.g. `dietsync.yourdomain.com`), install Caddy to handle automatic HTTPS renewal:

```bash
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install caddy -y
```

Edit `/etc/caddy/Caddyfile`:
```caddy
dietsync.yourdomain.com {
    reverse_proxy localhost:80
}
```

Reload Caddy:
```bash
systemctl reload caddy
```
Your application is now live at `https://dietsync.yourdomain.com` with free automated SSL certificates!

---

## 4. Option B: PaaS Deployment (Railway / Render)

If you prefer managed cloud platforms that build directly from GitHub:

### Deploying on Railway (Fastest Managed Setup)
1. Go to [railway.app](https://railway.app) and click **New Project** $\rightarrow$ **Deploy from GitHub repo**.
2. Select your `dietsync` repository.
3. **Add PostgreSQL**: Click `+ New` $\rightarrow$ `Database` $\rightarrow$ `Add PostgreSQL`.
4. **Add RabbitMQ**:
   - Option 1: Click `+ New` $\rightarrow$ `Database` $\rightarrow$ search `RabbitMQ` template.
   - Option 2: Use free hosted RabbitMQ from [CloudAMQP.com](https://www.cloudamqp.com) and copy the `CLOUDAMQP_URL`.
5. **Configure API Service**:
   - In your Web Service settings, set the Start Command:
     ```bash
     sh -c "alembic upgrade head && python scripts/demo_seed.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT"
     ```
   - Add environment variables (`DATABASE_URL`, `RABBITMQ_URL`, `OPENAI_API_KEY`).
6. **Configure Worker Service**:
   - Click `+ New` $\rightarrow$ `GitHub Repo` $\rightarrow$ select `dietsync` again.
   - Set the Start Command:
     ```bash
     python -m worker.consumer
     ```
   - Connect the same `DATABASE_URL`, `RABBITMQ_URL`, and `OPENAI_API_KEY`.
7. **Frontend Service**:
   - Deploy `frontend/` as a static site or see Option C below.

---

## 5. Option C: Hybrid Deployment (Vercel + Cloud Backend)

Deploy the frontend on **Vercel** (global edge CDN) and the backend on your server or Railway:

1. Push code to GitHub.
2. Open [vercel.com](https://vercel.com) and click **Add New** $\rightarrow$ **Project**.
3. Import your `dietsync` repository.
4. Set the **Root Directory** to `frontend`.
5. Set the **Framework Preset** to `Vite`.
6. Add Environment Variables:
   - `VITE_API_BASE`: `https://api.yourdomain.com` (or your Railway/Render URL)
   - `VITE_WS_BASE`: `wss://api.yourdomain.com` (or your Railway/Render WebSocket URL)
7. Click **Deploy**. Vercel will automatically build and deploy the React frontend globally with instant previews on every git push.

---

## 6. Production Environment Variables Checklist

| Variable | Description | Example / Required |
| :--- | :--- | :--- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/dietsync` |
| `RABBITMQ_URL` | RabbitMQ connection string | `amqp://user:pass@host:5672/` |
| `OPENAI_API_KEY` | OpenAI API key for LangGraph reasoning & auditor | `sk-proj-...` |
| `LANGCHAIN_TRACING_V2` | Enable LangSmith tracing (optional) | `false` or `true` |
| `LANGCHAIN_API_KEY` | LangSmith API Key (optional) | `lsv2_pt_...` |
| `LANGCHAIN_PROJECT` | LangSmith project name | `dietsync` |
| `VITE_API_BASE` | HTTP API base URL (Frontend) | `https://api.yourdomain.com` |
| `VITE_WS_BASE` | WebSocket base URL (Frontend) | `wss://api.yourdomain.com` |

---

## 7. Post-Deployment Verification

Once deployed, run these quick sanity checks:

### 1. API Health Check
```bash
curl -i https://YOUR_DOMAIN/health
# Expected: HTTP/1.1 200 OK
# {"status":"healthy","database":"connected","drap_resolver":"operational"}
```

### 2. Verify Drug Resolution
```bash
curl -X POST https://YOUR_DOMAIN/resolve \
  -H "Content-Type: application/json" \
  -d '{"query":"Disprin"}'
# Expected: {"status":"resolved","drug":{"drug_id":...,"display_name":"Disprin Tablet",...}}
```

### 3. Verify Doctor Mode in Browser
1. Open your web app URL in a browser.
2. Toggle to **Physician Prescriber** mode.
3. Click the preset **Aspirin + Warfarin (Severe Bleeding)**.
4. Click **Execute Grounded Clinical Safety Check**.
5. Verify that the WebSocket streams real-time updates and renders the critical hazard alert, verbatim manufacturer quote, and prescriber directives.
6. Click **Generate EMR Consultation Note** to confirm formatted EMR note generation and copy-to-clipboard functionality.
