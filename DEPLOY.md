# DocuMind AI - GitHub & Cloud Deployment Guide

This directory contains the clean production-ready application package for **DocuMind AI**, free from local virtual environments, test caches, bytecode, and sensitive credentials.

---

## 1. Quick Push to a New GitHub Repository

To deploy this folder to a fresh GitHub repository:

```bash
# 1. Navigate into the deploy folder
cd deploy

# 2. Initialize a clean git repository
git init -b main

# 3. Stage all deployable files
git add .

# 4. Create your initial commit
git commit -m "feat: initial production deployment for DocuMind AI"

# 5. Link to your GitHub remote repository (replace with your repo URL)
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git

# 6. Push to GitHub
git push -u origin main
```

---

## 2. Cloud Deployment Options

### Option A: Render / Railway / Heroku
This folder includes both `Procfile` and `runtime.txt`.
1. Link your GitHub repository in the cloud provider's dashboard.
2. Select **Python** runtime or Docker.
3. Configure your Environment Variables in the provider's dashboard:
   - `SECRET_KEY`: A strong random string (e.g., generate with `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `DATABASE_URL`: Your production MySQL or PostgreSQL connection string
   - `GEMINI_API_KEY`: Your Google Gemini API key
   - `PORT`: Set automatically by the hosting provider (defaults to 5000)

### Option B: Docker Container Deployment
Run DocuMind AI anywhere with Docker:

```bash
# Build the production image
docker build -t documind-ai:latest .

# Run the container
docker run -d -p 5000:5000 --env-file .env documind-ai:latest
```

Or using Docker Compose:
```bash
docker-compose up -d --build
```

### Option C: Vercel Deployment
DocuMind AI includes `vercel.json` and `.python-version` (pinned to `3.12` as required by Vercel's build runner).

> **Important Architecture Note for Vercel:**
> Vercel is a **serverless** platform with a **250 MB uncompressed function size limit** and **ephemeral read-only disk storage** (meaning any files uploaded to `uploads/` or FAISS indexes saved to `vector_indexes/` are wiped between function invocations).
> 
> For full production document processing with local files and heavy ML dependencies (`torch`, `faiss-cpu`), **Render**, **Railway**, **Koyeb**, or **Docker** (Option A & B) are strongly recommended over Vercel because they provide long-running processes, persistent storage, and full resource allocations.

---

## 3. Directory Structure

```
deploy/
├── app.py                  # Core application factory
├── wsgi.py                 # Production WSGI server (Waitress)
├── config.py               # Application configuration
├── extensions.py           # SQLAlchemy database instance
├── requirements.txt        # Production dependencies
├── Dockerfile              # Container specification
├── docker-compose.yml      # Multi-container orchestration
├── Procfile                # Cloud process configuration
├── runtime.txt             # Python runtime version
├── .env.example            # Environment template (NO sensitive keys)
├── .gitignore              # Production ignore rules
├── README.md               # Overview & quickstart documentation
├── DEPLOY.md               # Deployment instructions
├── models/                 # SQLAlchemy database schema models
├── routes/                 # Flask Blueprints (auth, chat, docs, profile)
├── services/               # Vector store, retrieval, extraction, LLM logic
├── static/                 # CSS styling, JavaScript, media assets
├── templates/              # Jinja2 HTML templates
├── tests/                  # Automated test suite (pytest)
├── uploads/                # Runtime document upload storage (.gitkeep)
└── vector_indexes/         # Runtime FAISS vector storage (.gitkeep)
```
