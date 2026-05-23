import os
import json
import queue
import threading
import re
import time
import random
import shutil
import html
from urllib.parse import urlparse
from dotenv import load_dotenv
from datetime import datetime

load_dotenv(override=True)

# ── Patch LiteLLM to strip unsupported 'cache_breakpoint' from messages ──────
try:
    import litellm
    _original_completion = litellm.completion

    def _patched_completion(*args, **kwargs):
        messages = kwargs.get("messages", [])
        for msg in messages:
            msg.pop("cache_breakpoint", None)
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict):
                        block.pop("cache_breakpoint", None)
        kwargs["messages"] = messages
        return _original_completion(*args, **kwargs)

    litellm.completion = _patched_completion
except Exception:
    pass
# ─────────────────────────────────────────────────────────────────────────────

from flask import Flask, request, jsonify, Response, render_template, stream_with_context
from flask_cors import CORS

from repo_utils import clone_repo, get_files, format_files_for_prompt, get_repo_structure
from agents import build_crew

app = Flask(__name__)
CORS(app)

REPO_CLONE_PATH = "repo"
progress_queues: dict[str, queue.Queue] = {}


try:
    from litellm import RateLimitError as LitellmRateLimitError
except Exception:
    LitellmRateLimitError = None


def _send(q: queue.Queue, event: str, data: dict):
    q.put({"event": event, "data": data})


def _is_rate_limit_error(exc: BaseException) -> bool:
    if LitellmRateLimitError and isinstance(exc, LitellmRateLimitError):
        return True
    text = str(exc).lower()
    return any(token in text for token in ["rate limit", "rate_limit_exceeded", "tokens per minute", "rate limit exceeded"])


def _is_model_not_found_error(exc: BaseException) -> bool:
    """Detect errors indicating the specified model is not available or accessible."""
    text = str(exc).lower()
    tokens = [
        "does not exist", "model_not_found", "model not found", "not found",
        "access", "unauthorized", "forbidden", "model is not available",
        "invalid", "invalid_api_key", "invalid api key", "invalid key",
    ]
    return any(tok in text for tok in tokens)


def _format_date(dt: datetime) -> str:
    return dt.strftime("%d %B %Y")


def _parse_repo_url(repo_url: str) -> tuple[str, str, str, str]:
    if not repo_url:
        return "", "", "Unknown project", "Repository"
    parsed = urlparse(repo_url.strip())
    host = (parsed.netloc or "").lower()
    if "github.com" in host:
        source = "GitHub"
    elif "gitlab.com" in host:
        source = "GitLab"
    elif host:
        source = host
    else:
        source = "Repository"
    path = (parsed.path or "").rstrip("/").replace(".git", "")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        owner, name = parts[-2], parts[-1]
        display = f"{owner}/{name}"
    elif parts:
        owner, name = "", parts[-1]
        display = name
    else:
        owner, name, display = "", "Unknown project", "Unknown project"
    return owner, name, display, source


def _infer_primary_stack(files: list[dict], repo_path: str) -> str:
    extensions = {os.path.splitext(f["file"])[1].lower() for f in files}
    content = ""
    for candidate in ["requirements.txt", "pyproject.toml", "Pipfile"]:
        candidate_path = os.path.join(repo_path, candidate)
        if os.path.exists(candidate_path):
            try:
                with open(candidate_path, "r", encoding="utf-8", errors="ignore") as f:
                    content += f.read().lower()
            except Exception:
                pass
    if ".py" in extensions:
        if "flask" in content:
            return "Python · Flask"
        if "fastapi" in content:
            return "Python · FastAPI"
        if "django" in content:
            return "Python · Django"
        return "Python"
    if ".ts" in extensions:
        return "TypeScript"
    if ".js" in extensions:
        return "JavaScript"
    if ".go" in extensions:
        return "Go"
    if ".rb" in extensions:
        return "Ruby"
    if ".java" in extensions:
        return "Java"
    return "Multi-language"


def _markdown_to_html(text: str) -> str:
    if not text:
        return ""

    escaped = html.escape(text)
    escaped = re.sub(r"```(\w*)\n([\s\S]*?)```", lambda m: f"<pre><code class=\"language-{m.group(1)}\">{m.group(2).strip()}</code></pre>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"_(.+?)_", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?m)^###\s+(.+)$", r"<h3>\1</h3>", escaped)
    escaped = re.sub(r"(?m)^##\s+(.+)$", r"<h2>\1</h2>", escaped)
    escaped = re.sub(r"(?m)^#\s+(.+)$", r"<h1>\1</h1>", escaped)
    escaped = re.sub(r"(?m)^>\s+(.+)$", r"<blockquote>\1</blockquote>", escaped)
    escaped = re.sub(r"(?m)^\s*[-*+]\s+(.+)$", r"<li>\1</li>", escaped)
    escaped = re.sub(r"(?s)(?:<li>.*?</li>\s*)+", lambda m: f"<ul>{m.group(0).strip()}</ul>", escaped)

    parts = [p.strip() for p in re.split(r"\n\s*\n+", escaped) if p.strip()]
    html_parts = []
    for part in parts:
        if part.startswith("<h1>") or part.startswith("<h2>") or part.startswith("<h3>") or part.startswith("<ul>") or part.startswith("<pre>") or part.startswith("<blockquote>"):
            html_parts.append(part)
        else:
            paragraph = part.replace("\n", "<br/>")
            html_parts.append("<p>" + paragraph + "</p>")

    return "\n".join(html_parts)


def _kickoff_with_retry(crew_factory, q, retries: int = 3) -> object:
    """Attempt to kickoff a crew (built via crew_factory) with retries and model fallbacks.

    crew_factory: callable(model: str|None, temperature: float|None) -> Crew
    """
    # Build list of candidate models to try (initial + fallbacks)
    initial = os.environ.get("GROQ_MODEL", "groq/llama-3.3-70b-versatile")
    fallback_env = os.environ.get("GROQ_FALLBACK_MODELS", "groq/llama-3.3-32b,groq/llama-2-13b")
    candidates = [m.strip() for m in ([initial] + fallback_env.split(",")) if m.strip()]
    # Use environment-configurable retry/backoff settings if provided
    env_max_attempts = int(os.environ.get("GROQ_RETRY_MAX_ATTEMPTS", str(retries)))
    base_delay = float(os.environ.get("GROQ_RETRY_BASE_DELAY", "2"))
    max_delay = float(os.environ.get("GROQ_RETRY_MAX_DELAY", "120"))

    temp_override = float(os.environ.get("GROQ_TEMPERATURE", "0.3"))
    for model in candidates:
        crew = crew_factory(model, temp_override)
        for attempt in range(1, env_max_attempts + 1):
            try:
                _send(q, "progress", {"step": 6, "message": f"Using model {model} (attempt {attempt}/{env_max_attempts})"})
                return crew.kickoff(), crew
            except Exception as exc:
                # If the model is not available on the account, skip immediately to next candidate
                if _is_model_not_found_error(exc):
                    _send(q, "progress", {"step": 6, "message": f"⚠️ Model {model} not available or inaccessible. Switching to next fallback."})
                    break

                # If we detected a server-suggested retry time, prefer it (plus small buffer)
                match = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
                if _is_rate_limit_error(exc) and attempt < env_max_attempts:
                    if match:
                        suggested = min(max_delay, float(match.group(1)) + 2)
                        wait = suggested
                    else:
                        # Exponential backoff with full jitter: cap = min(max_delay, base_delay * 2^(attempt-1))
                        cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
                        wait = random.uniform(0, cap)

                    wait = max(0.5, min(wait, max_delay))
                    _send(q, "progress", {
                        "step": 6,
                        "message": f"⏳ Rate limit on model {model}, retrying in {int(wait)}s (attempt {attempt}/{env_max_attempts})...",
                    })
                    time.sleep(wait)
                    continue

                # If it's a rate limit and we've exhausted attempts for this model, break to try next model
                if _is_rate_limit_error(exc):
                    _send(q, "progress", {"step": 6, "message": f"⚠️ Switching to fallback model after rate limits on {model}."})
                    break
                raise
    # If all candidates exhausted, raise final error
    raise RuntimeError("All model candidates exhausted due to rate limits or errors.")


def _local_fallback_summary(formatted_files: str, structure: dict) -> str:
    """Produce a minimal text summary from the collected files when LLMs are unavailable.

    This returns a markdown-like string suitable for saving as report.md and basic parsing.
    """
    lines = []
    total_files = 0
    for block in re.split(r"\n\n#+ File:", formatted_files):
        if not block.strip():
            continue
        total_files += 1
        # try to extract filename
        m = re.search(r"^\s*([^\n]+)\n```\n([\s\S]{0,600})```", block, re.MULTILINE)
        if m:
            fname = m.group(1).strip()
            snippet = m.group(2).strip().split('\n')[:6]
            snippet = ' '.join([s.strip() for s in snippet])[:300]
        else:
            # fallback: first line as name
            parts = block.strip().split('\n')
            fname = parts[0][:160]
            snippet = ' '.join(parts[1:4])[:300]
        lines.append(f"### File: {fname}\n\n{snippet}\n")

    header = (
        "## 📌 What the Project Does\n\n"
        "This is a local fallback summary generated because remote LLMs were unavailable. "
        f"The analysis read approximately {total_files} file(s) and produced concise snippets.\n\n"
    )
    modules = "## ⚙️ Key Modules Breakdown\n\n" + "\n".join(lines[:50])
    recommendations = (
        "## 🚀 Recommendations\n\n"
        "- Add an API key for an LLM provider or increase quota to enable full analysis.\n"
        "- Add unit tests for critical modules.\n"
        "- Add basic README and runbook if missing.\n"
    )
    return header + modules + "\n" + recommendations


def run_analysis(job_id: str, repo_url: str):
    q = progress_queues[job_id]

    try:
        _send(q, "progress", {"step": 1, "message": "📥 Cloning repository..."})
        clone_path = os.path.join("jobs", job_id, "repo")
        repo_path, method = clone_repo(repo_url, clone_path)
        _send(q, "progress", {"step": 1, "message": f"✅ Repository fetched via {method}"})

        _send(q, "progress", {"step": 2, "message": "📂 Reading and parsing code files..."})
        files = get_files(repo_path)
        if not files:
            _send(q, "error", {"message": "No supported code files found in the repository."})
            return
        structure = get_repo_structure(files)
        _send(q, "progress", {
            "step": 2,
            "message": f"✅ Found {len(files)} file(s) across {len(structure)} folder(s)",
            "file_count": len(files),
            "structure": structure,
        })

        owner, repo_name, repo_display, repo_source = _parse_repo_url(repo_url)
        meta = {
            "repo_name": repo_name or repo_display,
            "repo_display": repo_display,
            "repo_source": repo_source,
            "repo_url": repo_url,
            "primary_stack": _infer_primary_stack(files, repo_path),
            "file_count": len(files),
            "structure": structure,
            "folder_count": len(structure),
            "generated_date": _format_date(datetime.utcnow()),
            "source_tooling": "CrewAI · Groq LLaMA 3.3",
            "badges": ["Repository analysis", "Architecture", "Metrics"],
        }

        formatted = format_files_for_prompt(files)

        _send(q, "progress", {"step": 3, "message": "🎯 Repo Manager: triaging files..."})
        _send(q, "progress", {"step": 4, "message": "📖 Code Analyst: reading codebase..."})
        _send(q, "progress", {"step": 5, "message": "🏗️ Architecture Agent: mapping system design..."})
        _send(q, "progress", {"step": 6, "message": "🧾 Documentation Agent: writing docs..."})

        # Debug: report detection of env flag and file flag
        try:
            env_flag = str(os.environ.get("FORCE_LOCAL_FALLBACK", "")).lower()
            file_flag = os.path.exists(os.path.join(os.path.dirname(__file__), "FORCE_LOCAL_FALLBACK"))
            _send(q, "progress", {"step": 6, "message": f"DEBUG: FORCE_LOCAL_FALLBACK env={env_flag} file={file_flag}"})
        except Exception:
            pass

        # If FORCE_LOCAL_FALLBACK is set, skip remote LLMs and produce a local summary
        if str(os.environ.get("FORCE_LOCAL_FALLBACK", "")).lower() in ("1", "true", "yes") or os.path.exists(os.path.join(os.path.dirname(__file__), "FORCE_LOCAL_FALLBACK")):
            _send(q, "progress", {"step": 6, "message": "⚠️ FORCE_LOCAL_FALLBACK enabled — generating local fallback summary."})
            raw = _local_fallback_summary(formatted, structure)
            debug_path = os.path.join("jobs", job_id, "debug_raw.txt")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(raw)
            sections = parse_sections(raw, [])
            meta["note"] = "Fallback summary generated locally (FORCE_LOCAL_FALLBACK)"
            report_path = os.path.join("jobs", job_id, "report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(raw)
            meta_path = os.path.join("jobs", job_id, "meta.json")
            try:
                with open(meta_path, "w", encoding="utf-8") as mf:
                    json.dump(meta, mf)
            except Exception:
                pass

            _send(q, "done", {
                "step": 7,
                "message": "✅ Analysis complete (local fallback)",
                "sections": sections,
                "raw": raw,
                "file_count": meta.get("file_count"),
                "structure": structure,
            })
            return

        # create a crew factory so _kickoff_with_retry can rebuild with fallback models
        def crew_factory(model_override: str | None = None, temp_override: float | None = None):
            return build_crew(formatted, structure, model=model_override, temperature=temp_override)

        try:
            result, used_crew = _kickoff_with_retry(crew_factory, q)
        except RuntimeError as rexc:
            # All remote models exhausted — produce graceful local fallback
            _send(q, "progress", {"step": 6, "message": "⚠️ Remote models unavailable — generating local fallback summary."})
            raw = _local_fallback_summary(formatted, structure)
            # write debug and continue
            debug_path = os.path.join("jobs", job_id, "debug_raw.txt")
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(raw)
            # minimal sections and meta
            sections = parse_sections(raw, [])
            meta = {
                "repo_name": repo_name or repo_display,
                "repo_display": repo_display,
                "repo_source": repo_source,
                "repo_url": repo_url,
                "primary_stack": _infer_primary_stack(files, repo_path),
                "file_count": len(files),
                "structure": structure,
                "folder_count": len(structure),
                "generated_date": _format_date(datetime.utcnow()),
                "source_tooling": "CrewAI · Groq LLaMA 3.3",
                "badges": ["Repository analysis", "Architecture", "Metrics"],
                "note": "Fallback summary generated locally due to remote model errors",
            }
            report_path = os.path.join("jobs", job_id, "report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(raw)
            meta_path = os.path.join("jobs", job_id, "meta.json")
            try:
                with open(meta_path, "w", encoding="utf-8") as mf:
                    json.dump(meta, mf)
            except Exception:
                pass

            _send(q, "done", {
                "step": 7,
                "message": "✅ Analysis complete (local fallback)",
                "sections": sections,
                "raw": raw,
                "file_count": meta.get("file_count"),
                "structure": structure,
            })
            return

        # Collect ALL task outputs, not just the last one
        task_outputs = []
        for task in used_crew.tasks:
            if hasattr(task, 'output') and task.output:
                task_outputs.append(str(task.output.raw if hasattr(task.output, 'raw') else task.output))

        # Combine all outputs into one document
        combined = "\n\n".join(task_outputs) if task_outputs else str(result)
        raw = combined

        # Also save debug log
        debug_path = os.path.join("jobs", job_id, "debug_raw.txt")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(raw)

        # Attempt to extract machine-readable metadata block from agent output
        meta_from_agent = None
        m = re.search(r"---METADATA-START---(.*?)---METADATA-END---", raw, re.DOTALL)
        if m:
            try:
                meta_from_agent = json.loads(m.group(1).strip())
            except Exception:
                meta_from_agent = None

        sections = parse_sections(raw, task_outputs)

        # Save report
        report_path = os.path.join("jobs", job_id, "report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(raw)

        # Save lightweight metadata for export templates
        meta["file_count"] = len(files)
        meta["structure"] = structure
        meta["folder_count"] = len(structure)
        if meta_from_agent and isinstance(meta_from_agent, dict):
            meta.update(meta_from_agent)
        meta["generated_date"] = _format_date(datetime.utcnow())
        meta.setdefault("repo_name", repo_name or meta.get("repo_display") or f"report-{job_id[:8]}")
        meta.setdefault("repo_display", repo_display)
        meta.setdefault("repo_source", repo_source)
        meta.setdefault("repo_url", repo_url)
        meta.setdefault("primary_stack", meta.get("primary_stack", "Code analysis"))
        meta.setdefault("source_tooling", meta.get("source_tooling", "CrewAI · Groq LLaMA 3.3"))
        meta.setdefault("badges", meta.get("badges", ["Repository analysis", "Architecture", "Metrics"]))
        try:
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta, mf)
        except Exception:
            pass

        _send(q, "done", {
            "step": 7,
            "message": "✅ Analysis complete!",
            "sections": sections,
            "raw": raw,
            "file_count": len(files),
            "structure": structure,
        })

    except Exception as e:
        _send(q, "error", {"message": str(e)})
    finally:
        # Cleanup cloned repo to save disk space
        job_repo = os.path.join("jobs", job_id, "repo")
        if os.path.exists(job_repo):
            shutil.rmtree(job_repo, ignore_errors=True)
        q.put(None)  # sentinel


def parse_sections(raw: str, task_outputs: list = None) -> dict:
    """Extract sections from agent output."""
    sections = {
        "what_it_does": "", "architecture": "", "folders": "",
        "modules": "", "data_flow": "", "dependencies": "",
        "recommendations": "", "readme": "", "how_it_works": "", "metrics": "",
        "runbook": "", "algorithm": "",
    }

    EMOJI_ANCHORS = r"(?:📌|🧱|📂|⚙|🔄|🔗|🚀|📘|🧠|📊|💡|✅|🔧)"
    patterns = [
        ("what_it_does",    r"(?:#{1,3}\s*)?(?:📌\s*)?What (?:the )?[Pp]roject [Dd]oes(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("architecture",    r"(?:#{1,3}\s*)?(?:🧱\s*)?System Architecture(?:[\s\w]*?)(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("folders",         r"(?:#{1,3}\s*)?(?:📂\s*)?Folder[- ]by[- ]Folder(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("modules",         r"(?:#{1,3}\s*)?(?:⚙[️\s]*)?Key Modules?(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("data_flow",       r"(?:#{1,3}\s*)?(?:🔄\s*)?Data Flow(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("dependencies",    r"(?:#{1,3}\s*)?(?:🔗\s*)?Dependenc(?:ies|y)(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("recommendations", r"(?:#{1,3}\s*)?(?:🚀\s*)?Recommendations?(.*?)(?=(?:#{1,3}\s*(?:📘|🧠|📊))|\Z)"),
        ("metrics",         r"(?:#{1,3}\s*)?(?:📊\s*)?Technical Metrics?(.*?)(?=(?:#{1,3}\s*(?:📘|🧠))|\Z)"),
        ("algorithm",       r"(?:#{1,3}\s*)?(?:🧠\s*)?Algorithm(?: profile)?(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("runbook",         r"(?:#{1,3}\s*)?(?:📘\s*)?(?:Runbook|Installation|Usage|Runbook & usage|Installation & usage)(.*?)(?=(?:#{1,3}\s*" + EMOJI_ANCHORS + r")|\Z)"),
        ("readme",          r"(?:#{1,3}\s*)?(?:📘\s*)?README(?:\.md)?(.*?)(?=(?:#{1,3}\s*(?:🧠|How It Works))|\Z)"),
        ("how_it_works",    r"(?:#{1,3}\s*)?(?:🧠\s*)?How It Works(.*?)(?=(?:#{1,3}\s)|\Z)"),
    ]

    for key, pattern in patterns:
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1).strip()
            if len(content) > 30:
                sections[key] = content

    if task_outputs and len(task_outputs) >= 3:
        if not sections["what_it_does"] and not sections["architecture"]:
            arch_raw = task_outputs[2]
            sections["what_it_does"]  = _extract_keyword(arch_raw, "What", "System Architecture") or arch_raw[:1500]
            sections["architecture"]  = _extract_keyword(arch_raw, "System Architecture", "Folder") or arch_raw
            sections["folders"]       = _extract_keyword(arch_raw, "Folder", "Key Module") or sections["folders"]
            sections["modules"]       = _extract_keyword(arch_raw, "Key Module", "Data Flow") or sections["modules"]
            sections["data_flow"]     = _extract_keyword(arch_raw, "Data Flow", "Dependenc") or sections["data_flow"]
            sections["dependencies"]  = _extract_keyword(arch_raw, "Dependenc", "Recommendation") or sections["dependencies"]
            sections["recommendations"] = _extract_keyword(arch_raw, "Recommendation", "Technical Metric") or sections["recommendations"]
            sections["metrics"]       = _extract_keyword(arch_raw, "Technical Metric", None) or sections["metrics"]

        if not sections["readme"] and not sections["how_it_works"]:
            doc_raw = task_outputs[3] if len(task_outputs) > 3 else ""
            sections["readme"]       = _extract_keyword(doc_raw, "README", "How It Works") or doc_raw[:2000]
            sections["how_it_works"] = _extract_keyword(doc_raw, "How It Works", None) or doc_raw

        if not sections["algorithm"] and len(task_outputs) > 2:
            sections["algorithm"] = _extract_keyword(task_outputs[2], "Algorithm", "Data Flow") or sections["algorithm"]

        if not sections["runbook"]:
            sections["runbook"] = sections["readme"] or sections["how_it_works"]

        if not sections["what_it_does"] and len(task_outputs) > 1:
            sections["what_it_does"] = task_outputs[1][:3000]

    if not any(sections.values()):
        sections["what_it_does"] = raw

    return sections


def _extract_keyword(text: str, start_kw: str, end_kw: str | None) -> str:
    """Extract text between two keyword markers (case-insensitive)."""
    start = re.search(rf"(?:#{'{1,3}'}\s*)?(?:[^\n]*?){re.escape(start_kw)}", text, re.IGNORECASE)
    if not start:
        return ""
    s = start.start()
    if end_kw:
        end = re.search(rf"(?:#{'{1,3}'}\s*)?(?:[^\n]*?){re.escape(end_kw)}", text[s + 1:], re.IGNORECASE)
        e = s + 1 + end.start() if end else len(text)
    else:
        e = len(text)
    content = text[s:e].strip()
    # Remove the header line itself
    lines = content.split("\n")
    return "\n".join(lines[1:]).strip() if len(lines) > 1 else content


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    repo_url = (data or {}).get("repo_url", "").strip()

    if not repo_url:
        return jsonify({"error": "repo_url is required"}), 400
    if not os.environ.get("GROQ_API_KEY"):
        return jsonify({"error": "GROQ_API_KEY not set in .env file on the server"}), 500

    import uuid
    job_id = str(uuid.uuid4())
    os.makedirs(os.path.join("jobs", job_id), exist_ok=True)
    progress_queues[job_id] = queue.Queue()

    thread = threading.Thread(target=run_analysis, args=(job_id, repo_url), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/stream/<job_id>")
def stream(job_id: str):
    if job_id not in progress_queues:
        return jsonify({"error": "Job not found"}), 404

    def generate():
        q = progress_queues[job_id]
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
        progress_queues.pop(job_id, None)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/report/<job_id>")
def get_report(job_id: str):
    report_path = os.path.join("jobs", job_id, "report.md")
    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found"}), 404
    with open(report_path, "r", encoding="utf-8") as f:
        return jsonify({"report": f.read()})


@app.route("/export/json/<job_id>")
def export_json(job_id: str):
    report_path = os.path.join("jobs", job_id, "report.md")
    meta_path = os.path.join("jobs", job_id, "meta.json")
    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found"}), 404
    with open(report_path, "r", encoding="utf-8") as f:
        raw = f.read()
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            try:
                meta = json.load(f)
            except Exception:
                meta = {}
    sections = parse_sections(raw)
    return jsonify({"meta": meta, "sections": sections, "raw": raw})


@app.route("/export/<job_id>")
def export_html(job_id: str):
    """Generate and return a beautiful standalone HTML report."""
    report_path = os.path.join("jobs", job_id, "report.md")
    meta_path = os.path.join("jobs", job_id, "meta.json")
    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found"}), 404

    with open(report_path, "r", encoding="utf-8") as f:
        raw = f.read()

    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    sections = parse_sections(raw)
    owner, repo_name, repo_display, repo_source = _parse_repo_url(meta.get("repo_url") or meta.get("repo") or "")
    meta.setdefault("repo_name", repo_name or meta.get("repo") or repo_display or f"report-{job_id[:8]}")
    meta.setdefault("repo_display", repo_display)
    meta.setdefault("repo_source", repo_source or meta.get("repo_source", "GitHub"))
    meta.setdefault("repo_url", meta.get("repo_url", meta.get("repo") or ""))
    meta.setdefault("file_count", meta.get("file_count", 0))
    meta.setdefault("structure", meta.get("structure", {}))
    meta.setdefault("folder_count", len(meta.get("structure", {})))
    meta.setdefault("primary_stack", meta.get("primary_stack", "Code analysis"))
    meta.setdefault("source_tooling", meta.get("source_tooling", "CrewAI · Groq LLaMA 3.3"))
    meta.setdefault("generated_date", _format_date(datetime.utcnow()))
    meta.setdefault("report_summary",
                    f"Deep-dive technical narrative for {meta.get('repo_display', meta.get('repo_name', 'this repository'))} — {meta.get('primary_stack', 'code analysis')}.")
    meta["raw_preview"] = raw[:2000]
    sections = {k: _markdown_to_html(v) for k, v in sections.items()}

    html = render_template("report_template.html", sections=sections, meta=meta)
    return Response(html, mimetype="text/html",
                    headers={"Content-Disposition": f'attachment; filename="report_{job_id[:8]}.html"'})


@app.route("/debug/<job_id>")
def debug_report(job_id: str):
    debug_path = os.path.join("jobs", job_id, "debug_raw.txt")
    if not os.path.exists(debug_path):
        return jsonify({"error": "Debug file not found"}), 404
    with open(debug_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    os.makedirs("jobs", exist_ok=True)
    app.run(debug=True, port=5000, threaded=True, use_reloader=False)
