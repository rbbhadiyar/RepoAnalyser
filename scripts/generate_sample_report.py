import json
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

root = Path(__file__).resolve().parents[1]
job_dir = root / 'jobs' / 'sample-job'
report_md = job_dir / 'report.md'
meta_json = job_dir / 'meta.json'
output_html = job_dir / 'report_rendered.html'

with report_md.open('r', encoding='utf-8') as f:
    raw = f.read()

# try to extract sections roughly from report (simple split by headers)
sections = {}
sections['what_it_does'] = 'Demo: ' + raw.split('## 📌 What the Project Does')[-1].split('##')[0].strip()
sections['architecture'] = raw.split('## 🧱 System Architecture Overview')[-1].split('##')[0].strip()
sections['modules'] = raw.split('## ⚙️ Key Modules Breakdown')[-1].split('---METADATA-START---')[0].strip()

meta = json.loads(meta_json.read_text(encoding='utf-8'))
# Ensure template can access meta.top_matches as list of objects
env = Environment(loader=FileSystemLoader(str(root / 'templates')))
tpl = env.get_template('report_template.html')
html = tpl.render(sections=sections, meta=meta)

output_html.write_text(html, encoding='utf-8')
print('Wrote:', output_html)
