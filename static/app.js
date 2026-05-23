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

async function downloadReport() {
  if (!fullRawReport) return;

  const btn = document.querySelector('.result-actions .btn-secondary');
  const originalText = btn.textContent;
  btn.textContent = '⏳ Generating PDF...';
  btn.disabled = true;

  try {
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });

    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    const margin = 18;
    const contentW = pageW - margin * 2;
    let y = margin;

    // ── Helpers ──────────────────────────────────────────────────────────────
    function checkPage(needed = 10) {
      if (y + needed > pageH - margin) {
        pdf.addPage();
        y = margin;
      }
    }

    function addText(text, fontSize, color, isBold, maxWidth, lineHeight) {
      const safe = sanitizeText(String(text || ''));
      pdf.setFontSize(fontSize);
      pdf.setTextColor(...(color || [0,0,0]));
      pdf.setFont(isBold ? 'helvetica' : 'helvetica', isBold ? 'bold' : 'normal');
      const lines = pdf.splitTextToSize(safe, maxWidth || contentW);
      const lh = lineHeight || Math.max(5, fontSize * 0.6);
      lines.forEach(line => {
        checkPage(lh + 1);
        pdf.text(line, margin, y);
        y += lh;
      });
    }

    function addSectionHeader(title) {
      y += 6;
      checkPage(18);
      pdf.setFontSize(12);
      pdf.setTextColor(0,0,0);
      pdf.setFont('helvetica', 'bold');
      pdf.text(sanitizeText(title), margin, y);
      y += 8;
      // subtle divider
      pdf.setDrawColor(220,220,220);
      pdf.setLineWidth(0.4);
      pdf.line(margin, y, pageW - margin, y);
      y += 6;
    }

    function addBodyText(htmlOrText) {
      if (!htmlOrText || !String(htmlOrText).trim()) return;
      // Create a DOM fragment to preserve code blocks and lists
      const wrapper = document.createElement('div');
      wrapper.innerHTML = htmlOrText;

      const children = Array.from(wrapper.childNodes || []);
      children.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'PRE') {
          // code block
          const code = node.textContent || '';
          checkPage(12);
          const boxW = contentW;
          const boxHEstimated = Math.min(120, (code.split('\n').length + 1) * 6);
          pdf.setFillColor(245,245,245);
          pdf.roundedRect(margin, y, boxW, boxHEstimated, 1.5, 1.5, 'F');
          y += 4;
          pdf.setFont('courier', 'normal');
          addText(code, 9, [20,20,20], false, contentW - 6, 6);
          pdf.setFont('helvetica', 'normal');
          y += 6;
        } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'UL') {
          const items = Array.from(node.querySelectorAll('li'));
          items.forEach(li => {
            addText('\u2022 ' + li.textContent.trim(), 10, [0,0,0], false, contentW - 6, 6);
          });
        } else if (node.nodeType === Node.ELEMENT_NODE && node.tagName === 'CODE') {
          // inline code
          const code = node.textContent || '';
          pdf.setFont('courier', 'normal');
          addText(code, 10, [20,20,80], false, contentW, 6);
          pdf.setFont('helvetica', 'normal');
        } else {
          // plain text / paragraphs / headings
          const txt = node.textContent || '';
          const lines = sanitizeText(txt).split('\n');
          lines.forEach(ln => {
            const t = ln.trim();
            if (!t) { y += 4; return; }
            // simple header detection
            if (/^#{1,3}\s/.test(t)) {
              const clean = t.replace(/^#{1,3}\s/, '');
              addText(clean, 11, [0,0,0], true, contentW, 7);
              y += 2;
            } else {
              addText(t, 10, [0,0,0], false, contentW, 6);
            }
          });
        }
      });
    }

    // sanitize helper: remove emojis and non-printable unicode that break PDF fonts
    function sanitizeText(s) {
      let str = String(s || '');
      str = str.replace(/\u00A0/g, ' ');
      // strip common emoji/unicode ranges that built-in PDF fonts don't support
      try {
        str = str.replace(/[\u{1F300}-\u{1F6FF}]/gu, '').replace(/[\u{1F900}-\u{1F9FF}]/gu, '');
      } catch (e) {
        // older engines may not support u flag - fall back
        str = str.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '');
      }
      // remove other non-basic characters
      str = str.replace(/[^\x09\x0A\x0D\x20-\x7E\n]/g, '');
      // normalize whitespace
      str = str.replace(/\s+/g, ' ').trim();

      // collapse sequences of single-letter tokens (e.g. "r b b h a" -> "rbbha")
      const parts = str.split(' ');
      const out = [];
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        if (p.length === 1 && /^[A-Za-z0-9_\-]$/.test(p)) {
          // start a run
          let run = [p];
          let j = i + 1;
          while (j < parts.length && parts[j].length === 1 && /^[A-Za-z0-9]$/.test(parts[j])) {
            run.push(parts[j]);
            j++;
          }
          if (run.length >= 4) {
            out.push(run.join(''));
            i = j - 1;
            continue;
          }
        }
        out.push(p);
      }
      return out.join(' ').trim();
    }

    // ── Cover Page ────────────────────────────────────────────────────────────
    // White cover background
    pdf.setFillColor(255, 255, 255);
    pdf.rect(0, 0, pageW, pageH, 'F');

    // Title area
    pdf.setFontSize(28);
    pdf.setTextColor(0, 0, 0);
    pdf.setFont('helvetica', 'bold');
    pdf.text('RepoAnalyzer AI', pageW / 2, 60, { align: 'center' });

    pdf.setFontSize(13);
    pdf.setTextColor(60, 60, 60);
    pdf.setFont('helvetica', 'normal');
    pdf.text('GitHub Repository Analysis Report', pageW / 2, 72, { align: 'center' });

    // Repo name box (subtle) - sanitize displayed values
    const repoNameRaw = document.querySelector('.stat-chip .stat-val')?.textContent || 'Repository';
    const repoName = sanitizeText(repoNameRaw) || 'Repository';
    pdf.setFillColor(245,245,245);
    pdf.roundedRect(margin, 85, contentW, 18, 3, 3, 'F');
    pdf.setFontSize(11);
    pdf.setTextColor(0, 0, 0);
    pdf.setFont('helvetica', 'bold');
    pdf.text(repoName, pageW / 2, 97, { align: 'center' });

    // Stats
    const statChips = document.querySelectorAll('.stat-chip');
    let statsText = [];
    statChips.forEach(c => statsText.push(sanitizeText(c.innerText.trim())));
    pdf.setFontSize(9);
    pdf.setTextColor(80, 80, 80);
    pdf.setFont('helvetica', 'normal');
    pdf.text(statsText.join('   |   '), pageW / 2, 116, { align: 'center' });

    // Generated date
    pdf.setFontSize(9);
    pdf.setTextColor(100, 110, 120);
    pdf.text(`Generated: ${new Date().toLocaleString()}`, pageW / 2, 128, { align: 'center' });

    // Powered by (subtle)
    pdf.setFontSize(9);
    pdf.setTextColor(120, 120, 120);
    pdf.text('Powered by CrewAI · Groq LLaMA 3.3 · Flask', pageW / 2, pageH - 20, { align: 'center' });

    // ── Content Pages ─────────────────────────────────────────────────────────
    const sections = [
      { title: 'What the Project Does',      id: 'content-overview' },
      { title: 'System Architecture Overview', id: 'content-architecture' },
      { title: 'Folder-by-Folder Explanation', id: 'content-folders' },
      { title: 'Key Modules Breakdown',        id: 'content-modules' },
      { title: 'Data Flow Explanation',         id: 'content-dataflow' },
      { title: 'Auto-Generated README',         id: 'content-readme' },
      { title: 'How It Works',                  id: 'content-howitworks' },
    ];


    for (const sec of sections) {
      const el = document.getElementById(sec.id);
      const html = el ? el.innerHTML.trim() : '';
      if (!html || html === 'No content generated.') continue;

      pdf.addPage();
      // white page
      pdf.setFillColor(255, 255, 255);
      pdf.rect(0, 0, pageW, pageH, 'F');
      y = margin + 4;

      // use plain titles without emojis
      const titlePlain = (sec.title || '').replace(/[^\x00-\x7F]/g, '').trim() || sec.title;
      addSectionHeader(titlePlain);
      y += 3;
      addBodyText(html);

      // Page number
      pdf.setFontSize(8);
      pdf.setTextColor(100, 110, 120);
      pdf.text(`RepoAnalyzer AI  ·  ${repoName}`, margin, pageH - 8);
      pdf.text(`Page ${pdf.internal.getNumberOfPages()}`, pageW - margin, pageH - 8, { align: 'right' });
    }

    // ── Folder Tree Page ──────────────────────────────────────────────────────
    if (Object.keys(currentStructure).length > 0) {
      pdf.addPage();
      pdf.setFillColor(255, 255, 255);
      pdf.rect(0, 0, pageW, pageH, 'F');
      y = margin + 4;
      addSectionHeader('Repository File Structure');
      y += 3;
      for (const [folder, files] of Object.entries(currentStructure)) {
        checkPage(8);
        pdf.setFontSize(10);
        pdf.setTextColor(30, 30, 30);
        pdf.setFont('helvetica', 'bold');
        pdf.text(`${folder}/`, margin, y);
        y += 6;
        files.forEach(f => {
          checkPage(6);
          pdf.setFontSize(9);
          pdf.setTextColor(90, 90, 90);
          pdf.setFont('helvetica', 'normal');
          pdf.text(`${f}`, margin + 6, y);
          y += 5.5;
        });
        y += 4;
      }
      pdf.setFontSize(8);
      pdf.setTextColor(100, 110, 120);
      pdf.text(`RepoAnalyzer AI  ·  ${repoName}`, margin, pageH - 8);
      pdf.text(`Page ${pdf.internal.getNumberOfPages()}`, pageW - margin, pageH - 8, { align: 'right' });
    }

    pdf.save(`${repoName.replace('/', '_')}_analysis.pdf`);

  } catch (err) {
    alert('PDF generation failed: ' + err.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
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
