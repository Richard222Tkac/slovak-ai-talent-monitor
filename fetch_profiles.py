"""
Discovers AI-focused tech professionals located in Slovakia on GitHub, enriches
them with any linked Hugging Face profile, tracks which ones are new since the
last run, and renders an HTML dashboard.

Usage:
    python fetch_profiles.py

Requires GITHUB_TOKEN (and optionally HF_TOKEN) in the environment or a local
.env file (see .env.example). Only public profile fields are read; no scraping
of LinkedIn or any authenticated/private data.
"""

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

GITHUB_API = "https://api.github.com"
HF_API = "https://huggingface.co/api"


def load_dotenv_if_present():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def github_session():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set (check your .env file).")
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "slovak-ai-talent-monitor",
        }
    )
    return session


def discover_github(session):
    """Search GitHub users across Slovak location strings, deduped by login."""
    candidates = {}
    for location in config.SLOVAK_LOCATIONS:
        if len(candidates) >= config.MAX_CANDIDATES_PER_RUN:
            break
        query = f'location:"{location}" type:user'
        url = f"{GITHUB_API}/search/users"
        params = {"q": query, "per_page": 100, "sort": "followers", "order": "desc"}
        resp = session.get(url, params=params, timeout=30)
        time.sleep(config.SEARCH_API_SLEEP_SECONDS)
        if resp.status_code != 200:
            print(f"  [warn] search for '{location}' failed: {resp.status_code} {resp.text[:200]}")
            continue
        for item in resp.json().get("items", []):
            login = item["login"]
            if login not in candidates:
                candidates[login] = item
            if len(candidates) >= config.MAX_CANDIDATES_PER_RUN:
                break
    return candidates


def get_user_detail(session, login):
    resp = session.get(f"{GITHUB_API}/users/{login}", timeout=30)
    time.sleep(config.DETAIL_API_SLEEP_SECONDS)
    if resp.status_code != 200:
        return None
    return resp.json()


def get_user_repos(session, login):
    resp = session.get(
        f"{GITHUB_API}/users/{login}/repos",
        params={"sort": "updated", "per_page": config.MAX_REPOS_PER_CANDIDATE},
        timeout=30,
    )
    time.sleep(config.DETAIL_API_SLEEP_SECONDS)
    if resp.status_code != 200:
        return []
    return resp.json()


_KEYWORD_PATTERN_CACHE = {}


def _keyword_pattern(keyword):
    pattern = _KEYWORD_PATTERN_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        _KEYWORD_PATTERN_CACHE[keyword] = pattern
    return pattern


def score_candidate(repos):
    """Match repo metadata against the AI keyword dictionary.

    Uses word-boundary matching so short keywords (e.g. "rag", "bert") don't
    match inside unrelated words ("storage", "pragma", "liberty").

    Returns (matched_categories: set[str], score: int, top_projects: list[dict]).
    """
    matched_categories = set()
    hit_keywords = set()
    top_projects = []

    for repo in repos:
        haystack = " ".join(
            filter(
                None,
                [
                    repo.get("name", ""),
                    repo.get("description") or "",
                    repo.get("language") or "",
                    " ".join(repo.get("topics") or []),
                ],
            )
        )

        repo_categories = set()
        for category, keywords in config.AI_KEYWORD_CATEGORIES.items():
            for keyword in keywords:
                if _keyword_pattern(keyword).search(haystack):
                    repo_categories.add(category)
                    hit_keywords.add(keyword)

        if repo_categories:
            matched_categories |= repo_categories
            top_projects.append(
                {
                    "name": repo.get("name"),
                    "url": repo.get("html_url"),
                    "description": repo.get("description") or "",
                    "stars": repo.get("stargazers_count", 0),
                }
            )

    top_projects.sort(key=lambda r: r["stars"], reverse=True)
    return matched_categories, len(hit_keywords), top_projects[:3]


HF_URL_RE = re.compile(r"huggingface\.co/([A-Za-z0-9_-]+)", re.IGNORECASE)


def find_hf_username(user_detail):
    fields = " ".join(
        filter(None, [user_detail.get("bio") or "", user_detail.get("blog") or ""])
    )
    match = HF_URL_RE.search(fields)
    if match:
        return match.group(1)
    return None


def enrich_huggingface(hf_username):
    headers = {}
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    try:
        resp = requests.get(
            f"{HF_API}/users/{hf_username}/overview", headers=headers, timeout=15
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {
        "username": hf_username,
        "url": f"https://huggingface.co/{hf_username}",
        "num_models": data.get("numModels"),
        "num_datasets": data.get("numDatasets"),
        "num_spaces": data.get("numSpaces"),
    }


def load_seen():
    path = Path(config.SEEN_PROFILES_PATH)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_seen(seen):
    path = Path(config.SEEN_PROFILES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def render_dashboard(profiles, new_logins):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def row(p, is_new):
        categories = ", ".join(sorted(p["categories"]))
        projects = "<br>".join(
            f'<a href="{html.escape(proj["url"])}" target="_blank">{html.escape(proj["name"])}</a>'
            + (f' — {html.escape(proj["description"])}' if proj["description"] else "")
            for proj in p["top_projects"]
        )
        hf = ""
        if p.get("hf"):
            hf_data = p["hf"]
            parts = []
            if hf_data.get("num_models") is not None:
                parts.append(f'{hf_data["num_models"]} models')
            if hf_data.get("num_datasets") is not None:
                parts.append(f'{hf_data["num_datasets"]} datasets')
            if hf_data.get("num_spaces") is not None:
                parts.append(f'{hf_data["num_spaces"]} spaces')
            extra = f' ({", ".join(parts)})' if parts else ""
            hf = f'<a href="{html.escape(hf_data["url"])}" target="_blank">{html.escape(hf_data["username"])}</a>{extra}'
        contact_bits = []
        if p.get("email"):
            contact_bits.append(html.escape(p["email"]))
        if p.get("blog"):
            blog = p["blog"]
            blog_url = blog if blog.startswith("http") else f"https://{blog}"
            contact_bits.append(f'<a href="{html.escape(blog_url)}" target="_blank">{html.escape(blog)}</a>')
        contact = "<br>".join(contact_bits) or "—"

        new_badge = ' <span class="badge">NEW</span>' if is_new else ""
        name = html.escape(p.get("name") or p["login"])
        return f"""
        <tr>
          <td><a href="{html.escape(p['html_url'])}" target="_blank">{name}</a> (@{html.escape(p['login'])}){new_badge}</td>
          <td>{html.escape(categories)}</td>
          <td>{projects or "—"}</td>
          <td>{hf or "—"}</td>
          <td>{html.escape(p.get('location') or "—")}</td>
          <td>{contact}</td>
          <td>{html.escape(p['first_seen'])}</td>
        </tr>"""

    new_rows = "".join(row(p, True) for p in profiles if p["login"] in new_logins)
    old_rows = "".join(row(p, False) for p in profiles if p["login"] not in new_logins)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Slovak AI Talent Monitor</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 2rem; background: #0f1115; color: #e6e6e6; }}
  h1 {{ font-size: 1.4rem; }}
  .meta {{ color: #9aa0a6; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
  th, td {{ border: 1px solid #333; padding: 8px 10px; text-align: left; font-size: 0.9rem; vertical-align: top; }}
  th {{ background: #1a1d24; }}
  a {{ color: #7cb7ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{ background: #2e7d32; color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; }}
  .note {{ color: #9aa0a6; font-size: 0.85rem; margin-top: 2rem; }}
</style>
</head>
<body>
  <h1>Slovak AI Talent Monitor</h1>
  <div class="meta">Last updated: {now} &middot; {len(profiles)} tracked profiles &middot; {len(new_logins)} new this run</div>

  <h2>New since last run ({len(new_logins)})</h2>
  <table>
    <tr><th>Name</th><th>AI tech stack</th><th>Top projects</th><th>Hugging Face</th><th>Location</th><th>Contact</th><th>First seen</th></tr>
    {new_rows or '<tr><td colspan="7">No new profiles this run.</td></tr>'}
  </table>

  <h2>All tracked profiles ({len(profiles)})</h2>
  <table>
    <tr><th>Name</th><th>AI tech stack</th><th>Top projects</th><th>Hugging Face</th><th>Location</th><th>Contact</th><th>First seen</th></tr>
    {old_rows}
  </table>

  <p class="note">
    Sourced only from public GitHub/Hugging Face profile fields the person chose to make visible
    (location, bio, blog/website, public email). No LinkedIn scraping. If you reach out, include
    a clear way to opt out of further contact.
  </p>
</body>
</html>"""

    out_path = Path(config.DASHBOARD_OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def main():
    load_dotenv_if_present()
    session = github_session()
    seen = load_seen()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Searching GitHub for Slovak users...")
    candidates = discover_github(session)
    print(f"  {len(candidates)} candidate logins found across location queries.")

    profiles = []
    new_logins = set()

    for i, login in enumerate(candidates, 1):
        print(f"  [{i}/{len(candidates)}] inspecting {login}...")
        detail = get_user_detail(session, login)
        if not detail:
            continue
        repos = get_user_repos(session, login)
        categories, score, top_projects = score_candidate(repos)
        if score < config.MIN_AI_SCORE:
            continue

        hf_username = find_hf_username(detail)
        hf_data = enrich_huggingface(hf_username) if hf_username else None

        is_new = login not in seen
        first_seen = seen.get(login, today)
        if is_new:
            seen[login] = today
            new_logins.add(login)

        profiles.append(
            {
                "login": login,
                "name": detail.get("name"),
                "html_url": detail.get("html_url"),
                "location": detail.get("location"),
                "email": detail.get("email"),
                "blog": detail.get("blog"),
                "categories": categories,
                "top_projects": top_projects,
                "hf": hf_data,
                "first_seen": first_seen,
            }
        )

    save_seen(seen)
    out_path = render_dashboard(profiles, new_logins)

    print(f"\nDone. {len(profiles)} AI-focused Slovak profiles tracked, {len(new_logins)} new this run.")
    print(f"Dashboard written to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
