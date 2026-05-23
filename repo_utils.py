import os
import shutil
import requests

SUPPORTED_EXTENSIONS = (".py", ".js", ".ts", ".java", ".cpp", ".go", ".rb", ".md", ".json", ".yml", ".yaml")
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_FILE_CHARS = 3000


def clone_repo(repo_url: str, path: str = "repo") -> tuple[str, str]:
    """Try git clone first, fall back to GitHub API. Returns (path, method)."""
    if os.path.exists(path):
        shutil.rmtree(path)
    ret = os.system(f"git clone --depth=1 {repo_url} {path}")
    if ret == 0 and os.path.exists(path):
        return path, "git"
    # Fallback: GitHub API
    return _fetch_via_github_api(repo_url, path), "api"


def _fetch_via_github_api(repo_url: str, path: str) -> str:
    """Download repo tree via GitHub API and save files locally."""
    # Parse owner/repo from URL
    parts = repo_url.rstrip("/").replace(".git", "").split("/")
    owner, repo = parts[-2], parts[-1]

    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Authorization": f"token {token}"} if token else {}

    # Get default branch
    meta = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=15)
    meta.raise_for_status()
    branch = meta.json().get("default_branch", "main")

    # Get full tree
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    tree_resp = requests.get(tree_url, headers=headers, timeout=15)
    tree_resp.raise_for_status()
    tree = tree_resp.json().get("tree", [])

    os.makedirs(path, exist_ok=True)
    for item in tree:
        if item["type"] != "blob":
            continue
        file_path = item["path"]
        if not any(file_path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            continue
        if any(seg in IGNORE_DIRS for seg in file_path.split("/")):
            continue

        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        try:
            content = requests.get(raw_url, headers=headers, timeout=10).text
        except Exception:
            continue

        full_path = os.path.join(path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(content)

    return path


def get_files(repo_path: str) -> list[dict]:
    code_files = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            if file.endswith(SUPPORTED_EXTENSIONS):
                full_path = os.path.join(root, file)
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                if content:
                    relative_path = os.path.relpath(full_path, repo_path)
                    code_files.append({"file": relative_path, "content": content[:MAX_FILE_CHARS]})
    return code_files


def format_files_for_prompt(files: list[dict]) -> str:
    parts = [f"### File: {f['file']}\n```\n{f['content']}\n```" for f in files]
    return "\n\n".join(parts)


def get_repo_structure(files: list[dict]) -> dict:
    """Build a folder → files mapping for display."""
    structure = {}
    for f in files:
        parts = f["file"].replace("\\", "/").split("/")
        folder = "/".join(parts[:-1]) if len(parts) > 1 else "(root)"
        structure.setdefault(folder, []).append(parts[-1])
    return structure
