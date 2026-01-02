import os
import shutil
import tempfile
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from git import Repo
from dotenv import load_dotenv

from backend.ai_review import call_ai_review
from backend.github_issues import parse_repo, create_issue

load_dotenv()
app = FastAPI(title="RepoDoctor")

# =====================
# Models
# =====================
class AnalyzeRequest(BaseModel):
    repo_url: str

class CreateIssuesRequest(BaseModel):
    repo_url: str
    github_token: str
    issues: list[dict]

# =====================
# Helpers
# =====================
def safe_repo_name(repo_url: str) -> str:
    p = urlparse(repo_url)
    return p.path.strip("/").replace("/", "__") or "repo"

def read_text_file(path: str, max_chars: int = 8000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_chars)
    except Exception:
        return ""

def walk_repo_summary(root: str, max_files: int = 200):
    skip = [".git", "node_modules", "__pycache__", ".venv", "dist", "build"]
    important = [
        "README.md", "LICENSE", ".env.example",
        "pyproject.toml", "requirements.txt",
        "Dockerfile", ".github", "SECURITY.md"
    ]

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        if any(s in dirpath for s in skip):
            continue
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            if len(files) >= max_files:
                break
            files.append(os.path.join(rel, fn))

    key_contents = {}
    for name in important:
        p = os.path.join(root, name)
        if os.path.exists(p):
            key_contents[name] = (
                "DIRECTORY_PRESENT"
                if os.path.isdir(p)
                else read_text_file(p)
            )

    return files[:max_files], key_contents

def basic_heuristics(files, key_contents):
    findings, quickwins, risks = [], [], []
    if "README.md" not in key_contents:
        quickwins.append("Add a README.md with setup and usage instructions.")
    if ".env.example" not in key_contents:
        quickwins.append("Add a .env.example for environment variables.")
    if "Dockerfile" not in key_contents:
        quickwins.append("Add a Dockerfile for reproducible builds.")
    if "LICENSE" not in key_contents:
        risks.append("No LICENSE file found.")
    if not any("test" in f.lower() for f in files):
        risks.append("No obvious tests detected.")
    if len(files) > 180:
        findings.append("Large repo: consider adding docs/architecture.md.")
    return findings, quickwins, risks

# =====================
# API
# =====================
@app.post("/api/analyze")
def analyze_repo(req: AnalyzeRequest):
    repo_url = req.repo_url.strip()
    if not repo_url.startswith("https://github.com/"):
        return {"error": "Invalid GitHub repo URL"}

    tmp_root = tempfile.mkdtemp(prefix="repodoctor_")
    dest = os.path.join(tmp_root, safe_repo_name(repo_url))

    try:
        Repo.clone_from(repo_url, dest, depth=1)
        files, key_contents = walk_repo_summary(dest)
        findings, quickwins, risks = basic_heuristics(files, key_contents)

        ai_review, ai_error = None, None
        try:
            ai_review = call_ai_review(repo_url, files, key_contents)
        except Exception as e:
            ai_error = str(e)

        return {
            "repo_url": repo_url,
            "summary": {
                "file_count_sampled": len(files),
                "key_files_found": list(key_contents.keys()),
            },
            "findings": findings,
            "quick_wins": quickwins,
            "risks": risks,
            "next_steps": [
                "Add CI + basic tests",
                "Document env vars and run steps",
                "Add Docker",
                "Run a dependency security audit",
            ],
            "debug": {
                "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
                "ai_error": ai_error,
            },
            "ai_review": ai_review,
        }
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

@app.post("/api/create-issues")
def create_issues(req: CreateIssuesRequest):
    owner, repo = parse_repo(req.repo_url)
    created = []

    for it in req.issues[:5]:
        body = (
            f"**Severity:** {it['severity']}\n\n"
            f"**Evidence:**\n{it['evidence']}\n\n"
            f"**Suggested fix:**\n{it['fix']}\n\n"
            "_Created by RepoDoctor_"
        )
        issue = create_issue(
            req.github_token.strip(),
            owner, repo,
            it["title"],
            body
        )
        created.append(issue["html_url"])

    return {"created": created}

# =====================
# UI
# =====================
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>RepoDoctor</title>
<style>
:root{
  --bg:#0b0b0f;--panel:#0f0f18;--border:#232333;
  --text:#f2f2f2;--muted:#b6b6c2
}
body{
  font-family:Inter,Arial,sans-serif;
  background:var(--bg);color:var(--text);
  max-width:1100px;margin:40px auto;padding:0 16px
}
h1{font-size:46px;margin:0}
.sub{color:var(--muted);margin:10px 0 24px}
.row{display:flex;gap:10px;align-items:center}
input{
  flex:1;padding:12px 14px;border-radius:12px;
  border:1px solid var(--border);
  background:#11111a;color:#fff
}
button{
  padding:12px 16px;border-radius:12px;
  border:1px solid var(--border);
  background:#1a1a28;color:#fff;cursor:pointer
}
button:hover{background:#23233a}
.status{color:var(--muted)}
.panel{
  margin-top:20px;padding:18px;border-radius:18px;
  border:1px solid var(--border);background:var(--panel)
}
.grid{
  display:grid;grid-template-columns:1.2fr .8fr;
  gap:18px;margin-top:16px
}
.issue{
  padding:16px;border-radius:14px;
  background:rgba(255,255,255,.03);
  border:1px solid var(--border);
  margin-bottom:14px
}
.issue-head{
  display:flex;justify-content:space-between;align-items:center
}
.issue-title{font-size:16px;font-weight:600}
.sev{
  font-size:11px;padding:4px 10px;border-radius:999px;
  text-transform:uppercase;border:1px solid var(--border);
  color:var(--muted)
}
.sev.high{background:rgba(255,165,0,.1)}
.sev.medium{background:rgba(255,255,0,.08)}
.sev.low{background:rgba(0,255,180,.08)}
.sev.critical{background:rgba(255,80,80,.15)}
.issue-label{
  font-size:11px;color:var(--muted);
  text-transform:uppercase;margin-top:10px
}
.issue-text{font-size:14px;line-height:1.5}
.loader-title{font-size:18px;margin-bottom:10px}
.progress-bar{
  height:10px;border-radius:999px;
  border:1px solid var(--border);
  overflow:hidden;background:#0b0b0f
}
.progress-fill{
  height:100%;width:0%;
  background:linear-gradient(90deg,#7c7cff,#7cffc7);
  transition:width .4s ease
}
.hint{
  width:18px;height:18px;border-radius:50%;
  border:1px solid var(--border);
  display:flex;align-items:center;justify-content:center;
  font-size:12px;color:var(--muted);cursor:help
}
</style>
</head>
<body>

<h1>RepoDoctor</h1>
<div class="sub">Paste a GitHub repo URL. Get a senior-style Top 5 review + fixes.</div>

<div class="row">
  <input id="url" placeholder="https://github.com/owner/repo"/>
  <button onclick="runAnalyze()">Analyze</button>
  <span id="status" class="status"></span>
</div>

<div class="row" style="margin-top:10px">
  <input id="gh_token" placeholder="GitHub token (not stored)"/>
  <button onclick="createIssues()">Create Issues</button>
  <span class="hint" title="Creates GitHub issues in your repo using a temporary token.">?</span>
  <span id="issueStatus" class="status"></span>
</div>

<div id="loader" class="panel" style="display:none">
  <div class="loader-title">Analyzing repository</div>
  <div class="progress-bar"><div id="progress" class="progress-fill"></div></div>
  <div id="loader-step" class="status">Initializing…</div>
</div>

<div id="out" class="panel" style="display:none"></div>

<script>
let lastData=null, timer=null;

function runAnalyze(){
  const url = document.getElementById("url").value.trim();
  const out=document.getElementById("out");
  const loader=document.getElementById("loader");
  const bar=document.getElementById("progress");
  const step=document.getElementById("loader-step");
  out.style.display="none";
  loader.style.display="block";
  bar.style.width="0%";

  const stages=[
    [20,"Cloning repository…"],
    [40,"Scanning files…"],
    [60,"Running heuristics…"],
    [80,"AI reviewing code…"]
  ];
  let i=0;
  timer=setInterval(()=>{
    if(i<stages.length){
      bar.style.width=stages[i][0]+"%";
      step.textContent=stages[i][1];
      i++;
    }
  },700);

  fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({repo_url:url})})
  .then(r=>r.json()).then(d=>{
    clearInterval(timer);
    bar.style.width="100%";
    setTimeout(()=>{loader.style.display="none";out.style.display="block"},400);
    lastData=d;
    if(!d.ai_review){out.innerHTML="<pre>"+JSON.stringify(d,null,2)+"</pre>";return;}

    let issues="";
    d.ai_review.top_5.forEach(x=>{
      issues+=`
      <div class="issue">
        <div class="issue-head">
          <div class="issue-title">${x.title}</div>
          <span class="sev ${x.severity}">${x.severity}</span>
        </div>
        <div class="issue-label">Evidence</div>
        <div class="issue-text">${x.evidence}</div>
        <div class="issue-label">Fix</div>
        <div class="issue-text">${x.fix}</div>
      </div>`;
    });

    out.innerHTML=`
      <strong>${d.ai_review.one_liner}</strong>
      <div class="grid">
        <div class="panel"><h3>Top 5 Issues</h3>${issues}</div>
        <div class="panel"><h3>Next 7 Days</h3><ul>${d.ai_review.next_7_days_plan.map(p=>"<li>"+p+"</li>").join("")}</ul></div>
      </div>`;
  });
}

function createIssues(){
  if(!lastData) return;
  issueStatus.textContent="Creating…";
  fetch("/api/create-issues",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
    repo_url:lastData.repo_url,
    github_token:gh_token.value.trim(),
    issues:lastData.ai_review.top_5
  })})
  .then(r=>r.json()).then(d=>{
    issueStatus.innerHTML="Created "+d.created.length+" issues <span style='color:#7CFF9E'>✓</span>";
  });
}
</script>

</body>
</html>
"""
