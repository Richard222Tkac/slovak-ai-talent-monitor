# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that discovers AI-focused tech professionals located in Slovakia on GitHub, enriches them with a linked Hugging Face profile when one is findable, tracks who's new since the last run, and renders a dashboard. It runs both locally and as a scheduled cloud routine (3x/day), and the data also feeds a Claude Artifact dashboard that is updated separately/manually.

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
2. **`score_candidate()`** — for each candidate, fetches their most-recently-updated repos and matches name/description/language/topics against `config.AI_KEYWORD_CATEGORIES` using **word-boundary regex**, not substring matching. This matters: an earlier substring-based version falsely tagged people from keywords like `"rag"` and `"bert"` matching inside unrelated words (`storage`, `pragma`, `liberty`). Candidates below `config.MIN_AI_SCORE` are dropped — there's no other AI-relevance signal available, so this keyword pass is the only filter standing between "all Slovak GitHub users" and "AI-focused ones."
3. **`find_hf_username()` / `enrich_huggingface()`** — Hugging Face has no public "search users by location" endpoint, so HF is enrichment only, not a discovery source. It only fires if a candidate's GitHub bio/blog contains a `huggingface.co/<user>` link.
4. **`load_seen()` / `save_seen()`** — `data/seen_profiles.json` is a login → first-seen-date map. This is the only state that makes "new since last run" meaningful; it's intentionally committed to git (not gitignored) so the scheduled cloud routine's dedup state survives across runs in fresh sandboxes.
5. **`render_dashboard()`** — writes `output/dashboard.html`, a single self-contained static page (no framework, inline CSS), with a "new since last run" section above "all tracked profiles."
6. **`export_json()`** — writes `output/profiles.json`, a flat array export of the same data. This exists specifically to feed the Claude Artifact dashboard (see below) as an uploaded file-source asset; it is not consumed by anything else in this repo.

### Scheduled cloud routine

A Claude Code scheduled routine (`claude.ai/code/routines`) runs this repo 3x/day (09:00/14:00/18:00 Europe/Bratislava). Its prompt: export `GITHUB_TOKEN` from `gh auth token` (the sandbox's own `gh` auth, not a stored secret — there is no secrets mechanism wired into the routine), install deps, run the script, and commit+push only `data/seen_profiles.json` and `output/dashboard.html` if it succeeds. `HF_TOKEN` is not required in that environment; `enrich_huggingface()` works unauthenticated against HF's public endpoint, just with a lower rate limit.

### Claude Artifact dashboard

A separate, polished dashboard lives as a Claude Artifact (built from the "Dashboard" Artifact type), fed by an uploaded copy of `output/profiles.json` as a file-source dataset. **This is not auto-refreshed by the scheduled routine** — the routine updates the git repo only. Keeping the Artifact's data current requires re-uploading `output/profiles.json` as a new asset and updating the `datasets/profiles` store document's `source.url` to point at it (via the `Artifact`/`ArtifactData` tools), which currently happens manually. If asked to automate this, the open question is whether a cloud routine session can be granted `Artifact`/`ArtifactData` in its `allowed_tools` — untested as of this writing.

One gotcha specific to that Artifact: the Dashboard type's data loader flattens nested JSON arrays/objects (e.g. `categories`, `top_projects`) into JSON-text strings rather than passing them through as live JS arrays. The Artifact's page script accounts for this with an `asArray()` helper that `JSON.parse`s string fields before iterating — don't remove it or re-introduce a plain `.forEach()` on dataset fields that may be nested.

## Privacy / scope constraints (do not relax without the user's explicit say)

- Only public profile fields the person chose to expose are used: GitHub location, bio, blog/website, public email, repo metadata, plus public HF profile stats when a link is found.
- No LinkedIn scraping, no email harvesting from commit history or any private data source.
- This exists for recruitment sourcing; any outreach built on top of it should stay GDPR-compliant (legitimate-interest basis, clear opt-out).
