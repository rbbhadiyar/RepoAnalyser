let currentJobId = null;
let fullRawReport = "";
let currentStructure = {};
let currentSections = {};
let currentRepoUrl = "";
let currentFileCount = 0;

// ── Helpers ──────────────────────────────────────────────────────────────────

function setExample(url) {
  document.getElementById("repoUrl").value = url;
}

function show(id) { document.getElementById(id).classList.remove("hidden"); }
function hide(id) { document.getElementById(id).classList.add("hidden"); }

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.toggle("active", p.id === `tab-${name}`));
}

function setStep(num) {
  const pct = Math.round((num / 7) * 100);
  document.getElementById("progressBar").style.width = pct + "%";
  for (let i = 1; i <= 7; i++) {
    const el = document.getElementById(`step${i}`);
    if (i < num) { el.className = "step done"; }
    else if (i === num) { el.className = "step active"; }
    else { el.className = "step"; }
  }
}

function copySection(id) {
  const text = document.getElementById(id).innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    btn.textContent = "✅ Copied!";
    setTimeout(() => btn.textContent = "📋 Copy", 2000);
  });
}

async function downloadHtmlReport() {
  if (!currentJobId) return alert('No report available to download yet.');
  const url = `/export/${currentJobId}`;
  try {
    const res = await fetch(url, { headers: { Accept: 'text/html' } });
    if (!res.ok) throw new Error('Failed to fetch HTML report.');
    const blob = await res.blob();
    const filename = `repo_report_${currentJobId.slice(0, 8)}.html`;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    alert('HTML download failed: ' + err.message);
  }
}

function resetUI() {
  hide("resultsSection");
  hide("progressSection");
  hide("errorSection");
  show("inputSection");
  document.getElementById("analyzeBtn").disabled = false;
  document.getElementById("progressBar").style.width = "0%";
  for (let i = 1; i <= 7; i++) document.getElementById(`step${i}`).className = "step";
  currentJobId = null;
  fullRawReport = "";
}

// ── Markdown renderer (lightweight) ──────────────────────────────────────────

function renderMarkdown(text) {
  if (!text) return "<em style='color:var(--text2)'>No content generated.</em>";
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="lang-${lang}">${code.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^\s*[-*] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
    .replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/^(?!<[hupbla])(.+)$/gm, "$1")
    .replace(/\n/g, "<br>");
}

function renderPlain(text) {
  if (!text) return "<em style='color:var(--text2)'>No content generated.</em>";
  // Render as markdown for rich display
  return renderMarkdown(text);
}

// ── Folder Tree ───────────────────────────────────────────────────────────────

function renderFolderTree(structure) {
  const el = document.getElementById("content-folders-tree");
  if (!structure || Object.keys(structure).length === 0) { el.style.display = "none"; return; }
  let html = "";
  for (const [folder, files] of Object.entries(structure)) {
    html += `<div class="folder-name">📁 ${folder}/</div>`;
    files.forEach(f => { html += `<div class="file-name">📄 ${f}</div>`; });
  }
  el.innerHTML = html;
}

// ── Stats Bar ─────────────────────────────────────────────────────────────────

function renderStats(fileCount, structure, repoUrl) {
  const folderCount = Object.keys(structure || {}).length;
  const repoName = repoUrl.split("/").slice(-2).join("/");
  document.getElementById("statsBar").innerHTML = `
    <div class="stat-chip">🔗 <span class="stat-val">${repoName}</span></div>
    <div class="stat-chip">📄 <span class="stat-val">${fileCount}</span> files analyzed</div>
    <div class="stat-chip">📁 <span class="stat-val">${folderCount}</span> folders</div>
    <div class="stat-chip">🤖 <span class="stat-val">4</span> AI agents</div>
  `;
}

// ── Populate Results ──────────────────────────────────────────────────────────

function populateResults(sections, fileCount, structure, repoUrl) {
  const map = {
    "content-overview":     sections.what_it_does,
    "content-architecture": sections.architecture,
    "content-folders":      sections.folders,
    "content-modules":      sections.modules,
    "content-dataflow":     sections.data_flow,
    "content-readme":       sections.readme,
    "content-howitworks":   sections.how_it_works,
  };

  // If all sections empty, show raw fallback in overview
  const hasContent = Object.values(sections).some(v => v && v.trim());
  if (!hasContent && sections.raw_fallback) {
    map["content-overview"] = sections.raw_fallback;
  }

  for (const [id, text] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el) {
      el.classList.add("markdown-body");
      el.innerHTML = renderPlain(text || "");
    }
  }

  renderFolderTree(structure);
  renderStats(fileCount, structure, repoUrl);
}

// ── Main Analysis Flow ────────────────────────────────────────────────────────

async function startAnalysis() {
  const repoUrl = document.getElementById("repoUrl").value.trim();

  if (!repoUrl) { alert("Please enter a GitHub repository URL."); return; }

  hide("inputSection");
  hide("errorSection");
  hide("resultsSection");
  show("progressSection");

  document.getElementById("analyzeBtn").disabled = true;
  document.getElementById("progressTitle").textContent = "Starting analysis...";
  document.getElementById("progressRepo").textContent = repoUrl;
  document.getElementById("progressMsg").textContent = "Sending request to server...";
  setStep(1);

  // 1. POST to /analyze
  let jobId;
  try {
    const res = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Server error");
    jobId = data.job_id;
    currentJobId = jobId;
  } catch (err) {
    showError(err.message);
    return;
  }

  // 2. Stream progress via SSE
  const evtSource = new EventSource(`/stream/${jobId}`);

  evtSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);

    if (msg.event === "progress") {
      const d = msg.data;
      setStep(d.step || 1);
      document.getElementById("progressTitle").textContent = d.message || "";
      document.getElementById("progressMsg").textContent = d.message || "";
      if (d.structure) currentStructure = d.structure;
    }

    if (msg.event === "done") {
      evtSource.close();
      const d = msg.data;
      fullRawReport = d.raw || "";
      setStep(7);
      document.getElementById("progressTitle").textContent = "✅ Analysis complete!";
      document.getElementById("progressMsg").textContent = "Rendering report...";

      setTimeout(() => {
        hide("progressSection");
        populateResults(d.sections || {}, d.file_count || 0, d.structure || {}, repoUrl);
        // store globally for report generation
        currentSections = d.sections || {};
        currentFileCount = d.file_count || 0;
        currentRepoUrl = repoUrl;
        show("resultsSection");
        switchTab("overview");
      }, 600);
    }

    if (msg.event === "error") {
      evtSource.close();
      showError(msg.data.message || "Unknown error");
    }
  };

  evtSource.onerror = () => {
    evtSource.close();
    showError("Connection to server lost. Please try again.");
  };
}

function showError(msg) {
  hide("progressSection");
  hide("inputSection");
  document.getElementById("errorMsg").textContent = msg;
  show("errorSection");
  document.getElementById("analyzeBtn").disabled = false;
}

// Allow Enter key on inputs
document.addEventListener("DOMContentLoaded", () => {
  ["repoUrl"].forEach(id => {
    document.getElementById(id).addEventListener("keydown", e => {
      if (e.key === "Enter") startAnalysis();
    });
  });
});
