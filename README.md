# Slovak AI Talent Monitor

Finds AI-focused tech professionals located in Slovakia on GitHub, enriches
them with a linked Hugging Face profile where one is findable, tracks which
ones are new since the last run, and renders `output/dashboard.html`.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in your own tokens (never commit `.env`):
   - `GITHUB_TOKEN`: a GitHub personal access token. No special scopes are
     needed for reading public profiles/repos — being authenticated is enough
     to raise the rate limit. Create one at
     https://github.com/settings/tokens/new
   - `HF_TOKEN`: a Hugging Face access token with the **Read** role. Create one
     at https://huggingface.co/settings/tokens

## Running

```bash
python fetch_profiles.py
```

This will:
- Search GitHub for users whose profile location matches Slovakia or a major
  Slovak city.
- Drop anyone whose repos don't show any AI-related signal (see
  `config.AI_KEYWORD_CATEGORIES`).
- Check each remaining candidate's bio/blog for a linked Hugging Face profile
  and pull basic public stats from it if found.
- Compare against `data/seen_profiles.json` to flag who's new since the last
  run, then update that file.
- Write `output/dashboard.html` with two sections: new-since-last-run, and all
  tracked profiles.

## Data sources & privacy

Only public profile fields the person chose to expose are used: GitHub
location, bio, blog/website, public email (if set), and repo metadata; plus
public Hugging Face profile stats when a link is found. No LinkedIn scraping,
no email harvesting from commit history or private data of any kind.

If you use this for recruitment outreach, keep it compliant with GDPR
(legitimate-interest basis, and give recipients a clear, easy way to opt out
of further contact).

## Scheduling

Intended to run 3x/day as a scheduled cloud agent against this repo: pull,
run `fetch_profiles.py`, commit the updated `data/seen_profiles.json` and
`output/dashboard.html`, and report how many new profiles were found.
