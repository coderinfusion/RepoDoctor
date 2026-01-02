import re
import requests
from urllib.parse import urlparse

def parse_repo(repo_url: str) -> tuple[str, str]:
    """
    Accepts:
      https://github.com/owner/repo
      https://github.com/owner/repo/
      https://github.com/owner/repo.git
    Returns: (owner, repo)
    """
    u = urlparse(repo_url.strip())
    if u.netloc.lower() != "github.com":
        raise ValueError("Repo URL must be a github.com URL")

    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Repo URL must look like https://github.com/owner/repo")

    owner = parts[0]
    repo = re.sub(r"\.git$", "", parts[1])
    return owner, repo


def create_issue(token: str, owner: str, repo: str, title: str, body: str) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",

        "Accept": "application/vnd.github+json",
    }
    payload = {"title": title, "body": body}

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub API error {r.status_code}: {r.text[:300]}")
    return r.json()
