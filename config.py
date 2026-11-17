"""Tunable configuration for the Slovak tech talent monitor."""

# Location strings used as GitHub search qualifiers. GitHub's `location:` qualifier
# does a loose match against the user's free-text profile location field, so we
# query the country name plus the major cities people tend to set instead.
SLOVAK_LOCATIONS = [
    "Slovakia",
    "Slovak Republic",
    "Bratislava",
    "Kosice",
    "Košice",
    "Zilina",
    "Žilina",
    "Nitra",
    "Presov",
    "Prešov",
    "Banska Bystrica",
    "Banská Bystrica",
    "Trnava",
    "Trencin",
    "Trenčín",
]

# Categories of tech stack -> keywords matched against repo name, description,
# topics and primary language. Matching uses word-boundary regex (see
# _keyword_pattern in fetch_profiles.py), not substring matching, so short
# keywords like "rag" or "go" don't match inside unrelated words. These
# categories are a "strengths" tag on a qualifying profile, not a filter --
# see MIN_NON_FORK_REPOS / RECENT_ACTIVITY_DAYS below for the actual gate.
TECH_KEYWORD_CATEGORIES = {
    "Frontend": [
        "react", "vue", "svelte", "angular", "nextjs", "next.js", "webpack",
        "vite", "tailwind", "tailwindcss", "frontend",
    ],
    "Backend": [
        "django", "flask", "fastapi", "spring", "springboot", "spring-boot",
        "express", "nestjs", "rails", "laravel", "dotnet", "asp.net",
        "graphql", "rest-api", "microservices", "backend",
    ],
    "Mobile": [
        "android", "ios", "swift", "kotlin", "flutter", "react-native",
        "xamarin", "jetpack-compose", "swiftui", "mobile-app",
    ],
    "DevOps / Cloud": [
        "docker", "kubernetes", "k8s", "terraform", "ansible", "aws", "azure",
        "gcp", "ci-cd", "jenkins", "github-actions", "helm", "devops",
        "infrastructure-as-code",
    ],
    "Data / AI": [
        "llm", "large language model", "transformers", "huggingface",
        "hugging-face", "langchain", "machine-learning", "machine learning",
        "pytorch", "tensorflow", "nlp", "computer-vision", "data-engineering",
        "data-pipeline", "mlops", "scikit-learn", "sklearn", "spark", "etl",
        "data-science",
    ],
    "Languages": [
        "python", "java", "golang", "rust", "ruby", "php", "scala", "elixir",
        "javascript", "typescript", "csharp",
    ],
    "Testing / QA": [
        "selenium", "cypress", "playwright", "pytest", "junit",
        "test-automation", "qa-automation",
    ],
}

# "Proven projects" qualification bar, replacing the old AI-keyword score gate.
# A candidate must have at least this many original (non-fork) public repos.
MIN_NON_FORK_REPOS = 2

# ...and at least one of those non-fork repos must have both a description and
# a pushed_at within this many days, so stale/abandoned accounts don't qualify.
# ~2 years: long enough to not penalize someone mid-contract on closed-source
# work or between side projects, short enough to exclude dormant accounts.
RECENT_ACTIVITY_DAYS = 730

# How many of a candidate's most-recently-updated repos to inspect. Needs to be
# large enough that a prolific forker's non-fork repos aren't pushed out of the
# window by forks sorted alongside them.
MAX_REPOS_PER_CANDIDATE = 20

# Paths
SEEN_PROFILES_PATH = "data/seen_profiles.json"
DASHBOARD_OUTPUT_PATH = "output/dashboard.html"
PROFILES_JSON_PATH = "output/profiles.json"

# GitHub Search API is rate-limited more strictly (30 req/min authenticated) than
# the regular REST API (5000 req/hr). Sleep this many seconds between search calls.
SEARCH_API_SLEEP_SECONDS = 2.1

# Sleep between per-candidate repo-detail fetches (regular REST API, generous budget).
DETAIL_API_SLEEP_SECONDS = 0.3

# Sleep between per-candidate social-accounts fetches (regular REST API, same
# budget class as DETAIL_API_SLEEP_SECONDS). Only called for qualifying candidates.
SOCIAL_ACCOUNTS_API_SLEEP_SECONDS = 0.3

# Cap on total candidates processed per run, to keep runtime and rate-limit usage bounded.
MAX_CANDIDATES_PER_RUN = 150
