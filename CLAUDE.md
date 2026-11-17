# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that discovers tech professionals located in Slovakia on GitHub with a track record of original public projects, tags their tech-stack strengths (frontend/backend/mobile/DevOps/data-AI/etc. — a signal, not a filter), enriches them with a linked Hugging Face profile and public social links when findable, tracks who's new since the last run, and renders a dashboard. It runs both locally and as a scheduled cloud routine (3x/day), is hosted on GitHub Pages, and the data also feeds a Claude Artifact dashboard that is updated separately/manually.

## Commands

```bash
pip install -r requirements.txt   # only dependency: requests
python fetch_profiles.py          # run the full pipeline
```

No build step, no test suite, no linter configured.

Local setup: copy `.env.example` to `.env` and fill in `GITHUB_TOKEN` (no special scopes needed, just raises the rate limit) and `HF_TOKEN` (role: Read). `.env` is gitignored; `fetch_profiles.py` loads it itself via `load_dotenv_if_present()` (no `python-dotenv` dependency).

## Architecture

`fetch_profiles.py` runs as one linear pipeline, each stage feeding the next:

1. **`discover_github()`** — queries GitHub's Search Users API once per entry in `config.SLOVAK_LOCATIONS` (country name + major cities, since GitHub's `location:` qualifier is a loose free-text match and most people only set a city), dedupes by login. Capped by `config.MAX_CANDIDATES_PER_RUN`.
2. **`is_qualified()`** — the "proven projects" gate: a candidate needs at least `config.MIN_NON_FORK_REPOS` original (non-fork) public repos, with at least one of them having both a description and activity within `config.RECENT_ACTIVITY_DAYS` (~2 years), so throwaway or dormant accounts don't qualify. This replaced an earlier AI-keyword score gate — the pipeline now tracks any Slovak tech professional with real project history, not just AI/ML people.
3. **`tag_candidate()`** — for a qualifying candidate, fetches their most-recently-updated repos and matches name/description/language/topics against `config.TECH_KEYWORD_CATEGORIES` (Frontend, Backend, Mobile, DevOps/Cloud, Data/AI, Languages, Testing/QA) using **word-boundary regex**, not substring matching. This matters: an earlier substring-based version falsely tagged people from keywords like `"rag"` and `"bert"` matching inside unrelated words (`storage`, `pragma`, `liberty`). Unlike the old scoring gate, a zero-category match no longer disqualifies anyone — categories are a tech-stack strengths tag shown on the dashboard, not a filter.
4. **`find_hf_username()` / `enrich_huggingface()`** — Hugging Face has no public "search users by location" endpoint, so HF is enrichment only, not a discovery source. It only fires if a candidate's GitHub bio/blog contains a `huggingface.co/<user>` link.
5. **`get_social_accounts()` / `extract_social_links()`** — calls GitHub's public, non-scraping `GET /users/{login}/social_accounts` endpoint (only for candidates that already passed `is_qualified()`, so cost scales with qualifiers, not all discovered candidates) and pulls out `linkedin_url`, `x_url` (GitHub's provider key is still `"twitter"`), and any other self-added links (personal site, Mastodon, etc.) into `other_social`. These are links the person added themselves to their own GitHub profile — never scraped from LinkedIn/X directly.
6. **`load_seen()` / `save_seen()`** — `data/seen_profiles.json` is a login → first-seen-date map. This is the only state that makes "new since last run" meaningful; it's intentionally committed to git (not gitignored) so the scheduled cloud routine's dedup state survives across runs in fresh sandboxes.
7. **`render_dashboard()`** — writes `output/dashboard.html`, a single self-contained static page (no framework, inline CSS, vanilla JS for search/filter), with a "new since last run" section above "all tracked profiles."
8. **`export_json()`** — writes `output/profiles.json`, a flat array export of the same data. This exists specifically to feed the Claude Artifact dashboard (see below) as an uploaded file-source asset; it is not consumed by anything else in this repo.

### Hosting

`output/dashboard.html` is served at a public URL via GitHub Pages ("Deploy from a branch", default branch, `/ (root)` folder — no file relocation needed). The scheduled cloud routine already commits+pushes this file on every run, and GitHub Pages auto-rebuilds on every push to the configured branch, so the hosted page stays current with no extra moving parts.

Two small supporting files at the repo root make this work cleanly: `.nojekyll` (empty, stops GitHub Pages' default Jekyll processing from touching the static output) and `index.html` (a meta-refresh redirect to `output/dashboard.html`, so the bare Pages URL works too, not just the full path).

### Scheduled cloud routine

A Claude Code scheduled routine (`claude.ai/code/routines`) runs this repo 3x/day (09:00/14:00/18:00 Europe/Bratislava). Its prompt: export `GITHUB_TOKEN` from `gh auth token` (the sandbox's own `gh` auth, not a stored secret — there is no secrets mechanism wired into the routine), install deps, run the script, and commit+push only `data/seen_profiles.json` and `output/dashboard.html` if it succeeds. `HF_TOKEN` is not required in that environment; `enrich_huggingface()` works unauthenticated against HF's public endpoint, just with a lower rate limit.

### Claude Artifact dashboard

A separate, polished dashboard lives as a Claude Artifact (built from the "Dashboard" Artifact type), fed by an uploaded copy of `output/profiles.json` as a file-source dataset. **This is not auto-refreshed by the scheduled routine** — the routine updates the git repo only. Keeping the Artifact's data current requires re-uploading `output/profiles.json` as a new asset and updating the `datasets/profiles` store document's `source.url` to point at it (via the `Artifact`/`ArtifactData` tools), which currently happens manually. If asked to automate this, the open question is whether a cloud routine session can be granted `Artifact`/`ArtifactData` in its `allowed_tools` — untested as of this writing.

One gotcha specific to that Artifact: the Dashboard type's data loader flattens nested JSON arrays/objects (e.g. `categories`, `top_projects`) into JSON-text strings rather than passing them through as live JS arrays. The Artifact's page script accounts for this with an `asArray()` helper that `JSON.parse`s string fields before iterating — don't remove it or re-introduce a plain `.forEach()` on dataset fields that may be nested.

## Privacy / scope constraints (do not relax without the user's explicit say)

- Only public profile fields the person chose to expose are used: GitHub location, bio, blog/website, public email, repo metadata, GitHub's public social-accounts API (`GET /users/{login}/social_accounts` — links the person added themselves to their own GitHub profile: LinkedIn, X/Twitter, personal site), plus public HF profile stats when a link is found.
- Still prohibited: scraping LinkedIn, X, or any other site directly; any phone number, anywhere (not available via a public API — never fabricate or source one some other way); email harvesting from commit history or any source other than the GitHub profile's own public email/blog fields.
- This exists for recruitment sourcing; any outreach built on top of it should stay GDPR-compliant (legitimate-interest basis, clear opt-out).
