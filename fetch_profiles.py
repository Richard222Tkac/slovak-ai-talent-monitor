"""
Discovers tech professionals located in Slovakia on GitHub with a track record
of original public projects, tags their tech-stack strengths, enriches them
with any linked Hugging Face profile and public social links, tracks which
ones are new since the last run, and renders an HTML dashboard.

Usage:
    python fetch_profiles.py

Requires GITHUB_TOKEN (and optionally HF_TOKEN) in the environment or a local
.env file (see .env.example). Only public profile fields and GitHub's public
social-accounts API are read; no scraping of LinkedIn/X or any
authenticated/private data.
"""

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
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


def is_qualified(user_detail, repos):
    """"Proven projects" bar: at least MIN_NON_FORK_REPOS original repos, with
    at least one of them described and pushed within RECENT_ACTIVITY_DAYS."""
    non_fork = [r for r in repos if not r.get("fork")]
    if len(non_fork) < config.MIN_NON_FORK_REPOS:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(days=config.RECENT_ACTIVITY_DAYS)
    for repo in non_fork:
        if not (repo.get("description") or "").strip():
            continue
        pushed_at = repo.get("pushed_at")
        if not pushed_at:
            continue
        pushed_dt = datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if pushed_dt >= cutoff:
            return True
    return False


def tag_candidate(repos):
    """Tag tech-stack categories (a strengths signal, not a filter) and pick
    the top 3 original (non-fork) repos by star count.

    Uses word-boundary matching so short keywords (e.g. "go", "rag") don't
    match inside unrelated words ("storage", "pragma", "liberty").

    Returns (matched_categories: set[str], top_projects: list[dict]).
    """
    matched_categories = set()

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
        for category, keywords in config.TECH_KEYWORD_CATEGORIES.items():
            for keyword in keywords:
                if _keyword_pattern(keyword).search(haystack):
                    matched_categories.add(category)

    non_fork = [r for r in repos if not r.get("fork")]
    top_projects = sorted(
        (
            {
                "name": r.get("name"),
                "url": r.get("html_url"),
                "description": r.get("description") or "",
                "stars": r.get("stargazers_count", 0),
            }
            for r in non_fork
        ),
        key=lambda r: r["stars"],
        reverse=True,
    )[:3]
    return matched_categories, top_projects


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


def get_social_accounts(session, login):
    """GitHub's public social-accounts API: links the user added themselves to
    their own GitHub profile (LinkedIn, X/Twitter, personal site, etc). Public,
    non-scraping -- never pulls data from LinkedIn/X directly."""
    resp = session.get(f"{GITHUB_API}/users/{login}/social_accounts", timeout=30)
    time.sleep(config.SOCIAL_ACCOUNTS_API_SLEEP_SECONDS)
    if resp.status_code != 200:
        return []
    return resp.json()


def extract_social_links(social_accounts):
    """Pull LinkedIn/X links out of GitHub's social-accounts response. GitHub
    tags most of these by provider, but some links a user enters as a
    "generic" account still point at linkedin.com/x.com/twitter.com -- catch
    those by domain too so a real LinkedIn link doesn't get buried as a
    nameless "Generic" entry."""
    def is_domain(url, domain):
        return domain in (url or "").lower()

    linkedin_url = next(
        (a["url"] for a in social_accounts
         if a.get("provider") == "linkedin" or is_domain(a.get("url"), "linkedin.com")),
        None,
    )
    x_url = next(
        (a["url"] for a in social_accounts
         if a.get("provider") == "twitter" or is_domain(a.get("url"), "x.com") or is_domain(a.get("url"), "twitter.com")),
        None,
    )
    other_social = [
        a for a in social_accounts
        if a.get("url") not in (linkedin_url, x_url)
    ]
    return linkedin_url, x_url, other_social


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
    all_categories = sorted({c for p in profiles for c in p["categories"]})

    def row(p, is_new):
        categories = sorted(p["categories"])
        chips = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in categories) or "—"
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

        social_bits = []
        if p.get("linkedin_url"):
            social_bits.append(f'<a href="{html.escape(p["linkedin_url"])}" target="_blank">LinkedIn</a>')
        if p.get("x_url"):
            social_bits.append(f'<a href="{html.escape(p["x_url"])}" target="_blank">X</a>')
        for acct in p.get("other_social") or []:
            label = html.escape((acct.get("provider") or "link").title())
            social_bits.append(f'<a href="{html.escape(acct["url"])}" target="_blank">{label}</a>')
        social = " &middot; ".join(social_bits) or "—"

        new_badge = ' <span class="badge">NEW</span>' if is_new else ""
        name = html.escape(p.get("name") or p["login"])
        search_blob = html.escape(
            " ".join([p.get("name") or "", p["login"], p.get("location") or ""]).lower()
        )
        categories_attr = html.escape("|".join(categories))
        return f"""
        <tr data-search="{search_blob}" data-categories="{categories_attr}">
          <td><a href="{html.escape(p['html_url'])}" target="_blank">{name}</a> (@{html.escape(p['login'])}){new_badge}</td>
          <td>{chips}</td>
          <td>{projects or "—"}</td>
          <td>{hf or "—"}</td>
          <td>{html.escape(p.get('location') or "—")}</td>
          <td>{contact}</td>
          <td>{social}</td>
          <td>{html.escape(p['first_seen'])}</td>
        </tr>"""

    new_rows = "".join(row(p, True) for p in profiles if p["login"] in new_logins)
    old_rows = "".join(row(p, False) for p in profiles if p["login"] not in new_logins)
    header_row = (
        "<tr><th>Name</th><th>Tech stack</th><th>Top projects</th><th>Hugging Face</th>"
        "<th>Location</th><th>Contact</th><th>Social</th><th>First seen</th></tr>"
    )
    chip_buttons = "".join(
        f'<button type="button" class="chip-filter" data-category="{html.escape(c)}">{html.escape(c)}</button>'
        for c in all_categories
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slovak Tech Talent Monitor</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; padding: 2rem; background: #0f1115; color: #e6e6e6; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2.5rem; }}
  .meta {{ color: #9aa0a6; margin-bottom: 1.5rem; }}
  .controls {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 1rem; }}
  #search {{ background: #1a1d24; border: 1px solid #333; color: #e6e6e6; padding: 8px 12px; border-radius: 6px; font-size: 0.9rem; min-width: 220px; }}
  #search:focus {{ outline: none; border-color: #7cb7ff; }}
  .chip-filter {{ background: #1a1d24; border: 1px solid #333; color: #c9ccd1; padding: 5px 11px; border-radius: 999px; font-size: 0.8rem; cursor: pointer; }}
  .chip-filter:hover {{ border-color: #555; }}
  .chip-filter.active {{ background: #2a5d8f; border-color: #7cb7ff; color: #fff; }}
  .table-wrap {{ overflow-x: auto; border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; min-width: 900px; }}
  th, td {{ border: 1px solid #2a2d34; padding: 8px 10px; text-align: left; font-size: 0.9rem; vertical-align: top; }}
  th {{ background: #1a1d24; position: sticky; top: 0; }}
  tr:nth-child(even) td {{ background: #15171d; }}
  a {{ color: #7cb7ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .badge {{ background: #2e7d32; color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; }}
  .chip {{ display: inline-block; background: #22262e; color: #c9ccd1; font-size: 0.75rem; padding: 2px 8px; border-radius: 999px; margin: 1px 3px 1px 0; white-space: nowrap; }}
  .note {{ color: #9aa0a6; font-size: 0.85rem; margin-top: 2rem; }}
  tr.hidden {{ display: none; }}
</style>
</head>
<body>
  <h1>Slovak Tech Talent Monitor</h1>
  <div class="meta">Last updated: {now} &middot; {len(profiles)} tracked profiles &middot; {len(new_logins)} new this run</div>

  <div class="controls">
    <input type="search" id="search" placeholder="Search name, login, location...">
    {chip_buttons}
  </div>

  <h2>New since last run ({len(new_logins)})</h2>
  <div class="table-wrap">
  <table data-table="new">
    {header_row}
    {new_rows or '<tr><td colspan="8">No new profiles this run.</td></tr>'}
  </table>
  </div>

  <h2>All tracked profiles ({len(profiles)})</h2>
  <div class="table-wrap">
  <table data-table="all">
    {header_row}
    {old_rows}
  </table>
  </div>

  <p class="note">
    Sourced only from public GitHub/Hugging Face profile fields the person chose to make visible
    (location, bio, blog/website, public email, and GitHub's public social-accounts API for
    self-added LinkedIn/X/website links). No scraping of LinkedIn or X directly, no phone numbers.
    If you reach out, include a clear way to opt out of further contact.
  </p>

<script>
(function() {{
  var search = document.getElementById('search');
  var chips = document.querySelectorAll('.chip-filter');
  var rows = document.querySelectorAll('tr[data-search]');
  var activeCategories = new Set();

  function apply() {{
    var query = search.value.trim().toLowerCase();
    rows.forEach(function(row) {{
      var matchesSearch = !query || row.dataset.search.indexOf(query) !== -1;
      var rowCategories = row.dataset.categories ? row.dataset.categories.split('|') : [];
      var matchesCategories = activeCategories.size === 0 ||
        Array.from(activeCategories).some(function(c) {{ return rowCategories.indexOf(c) !== -1; }});
      row.classList.toggle('hidden', !(matchesSearch && matchesCategories));
    }});
  }}

  search.addEventListener('input', apply);
  chips.forEach(function(chip) {{
    chip.addEventListener('click', function() {{
      var category = chip.dataset.category;
      if (activeCategories.has(category)) {{
        activeCategories.delete(category);
        chip.classList.remove('active');
      }} else {{
        activeCategories.add(category);
        chip.classList.add('active');
      }}
      apply();
    }});
  }});
}})();
</script>
</body>
</html>"""

    out_path = Path(config.DASHBOARD_OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def export_json(profiles, new_logins):
    """Flat JSON export of tracked profiles, for consumers other than the HTML dashboard."""
    rows = []
    for p in profiles:
        hf = p.get("hf") or {}
        rows.append(
            {
                "login": p["login"],
                "name": p.get("name") or p["login"],
                "github_url": p["html_url"],
                "categories": sorted(p["categories"]),
                "top_projects": p["top_projects"],
                "hf_username": hf.get("username"),
                "hf_url": hf.get("url"),
                "hf_models": hf.get("num_models"),
                "hf_datasets": hf.get("num_datasets"),
                "hf_spaces": hf.get("num_spaces"),
                "location": p.get("location"),
                "email": p.get("email"),
                "blog": p.get("blog"),
                "linkedin_url": p.get("linkedin_url"),
                "x_url": p.get("x_url"),
                "other_social": p.get("other_social") or [],
                "first_seen": p["first_seen"],
                "is_new": p["login"] in new_logins,
            }
        )
    out_path = Path(config.PROFILES_JSON_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
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
        if not is_qualified(detail, repos):
            continue
        categories, top_projects = tag_candidate(repos)

        social_accounts = get_social_accounts(session, login)
        linkedin_url, x_url, other_social = extract_social_links(social_accounts)

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
                "linkedin_url": linkedin_url,
                "x_url": x_url,
                "other_social": other_social,
                "categories": categories,
                "top_projects": top_projects,
                "hf": hf_data,
                "first_seen": first_seen,
            }
        )

    save_seen(seen)
    out_path = render_dashboard(profiles, new_logins)
    json_path = export_json(profiles, new_logins)

    print(f"\nDone. {len(profiles)} Slovak tech profiles tracked, {len(new_logins)} new this run.")
    print(f"Dashboard written to: {out_path.resolve()}")
    print(f"JSON export written to: {json_path.resolve()}")


if __name__ == "__main__":
    main()
