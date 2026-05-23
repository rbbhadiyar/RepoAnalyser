# GitHub Repo Analyser

Lightweight tool to fetch a GitHub repository, analyze source files, and produce a developer-facing report.

## Quick overview
- Fetches repo via `git clone` (falls back to GitHub API if `git` is unavailable)
- Uses a configurable LLM backend to analyze code and generate architecture + README drafts
- Provides a local fallback summary when remote LLMs are unavailable

## Setup
1. Create a Python 3.10+ virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\\Scripts\\activate on Windows
pip install -r requirements.txt
```

2. Copy and edit `.env` with your keys (examples):

```
GROQ_API_KEY=your_groq_key_here
# Optional: GITHUB_TOKEN for private repos or higher rate limits
# GITHUB_TOKEN=ghp_...
GROQ_MODEL=groq/llama-3.1-8b-instant
GROQ_FALLBACK_MODELS=groq/llama-3.1-8b-instant,groq/llama-2-13b
# Use local fallback if you don't want remote LLMs
# FORCE_LOCAL_FALLBACK=true
```

## Run the app

```bash
python main.py
# Open http://localhost:5000 and submit a repo URL
```

## Troubleshooting
- If you see `This is a local fallback summary generated because remote LLMs were unavailable`:
  - Check `GROQ_API_KEY` validity and model access
  - Try a smaller model in `.env` (e.g. `groq/llama-3.1-8b-instant`)
  - Or set `FORCE_LOCAL_FALLBACK=true` to skip remote calls
- To view model attempt messages, check the server logs or watch the SSE stream at `/stream/<job_id>`

## Cleaning up before committing
- The app generates `jobs/` job folders and a `crew_output.log.txt` file during runs. These are ignored by default in `.gitignore`.

## To push cleaned repo

```bash
git add .
git commit -m "chore: clean up repo and add README"
git push origin main
```

If you want me to create a branch, compress job artifacts, or remove other files, tell me which files/folders to target.
