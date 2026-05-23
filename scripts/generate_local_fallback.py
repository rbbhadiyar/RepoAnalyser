import os
import json
import uuid
from datetime import datetime
from repo_utils import clone_repo, get_files, format_files_for_prompt, get_repo_structure

JOB_PREFIX = "manual-fallback-"

def local_fallback_summary(formatted_files: str, structure: dict) -> str:
    import re
    lines = []
    total_files = 0
    for block in re.split(r"\n\n#+ File:", formatted_files):
        if not block.strip():
            continue
        total_files += 1
        m = re.search(r"^\s*([^\n]+)\n```\n([\s\S]{0,600})```", block, re.MULTILINE)
        if m:
            fname = m.group(1).strip()
            snippet = m.group(2).strip().split('\n')[:6]
            snippet = ' '.join([s.strip() for s in snippet])[:300]
        else:
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


def generate(repo_url: str):
    job_id = JOB_PREFIX + uuid.uuid4().hex[:8]
    job_dir = os.path.join('jobs', job_id)
    os.makedirs(job_dir, exist_ok=True)
    clone_path = os.path.join(job_dir, 'repo')
    print('Cloning', repo_url)
    repo_path, method = clone_repo(repo_url, clone_path)
    files = get_files(repo_path)
    structure = get_repo_structure(files)
    formatted = format_files_for_prompt(files)
    raw = local_fallback_summary(formatted, structure)
    report_path = os.path.join(job_dir, 'report.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(raw)
    meta = {
        'file_count': len(files),
        'structure': structure,
        'generated_date': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        'note': 'Manual local fallback generated',
        'repo_url': repo_url,
    }
    with open(os.path.join(job_dir, 'meta.json'), 'w', encoding='utf-8') as mf:
        json.dump(meta, mf)
    with open(os.path.join(job_dir, 'debug_raw.txt'), 'w', encoding='utf-8') as df:
        df.write(raw)
    print('Wrote report to', report_path)
    return job_id

if __name__ == '__main__':
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else 'https://github.com/psf/requests'
    jid = generate(repo)
    print('Job id:', jid)
