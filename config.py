"""Tunable configuration for the Slovak AI talent monitor."""

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

# Categories of AI tech stack -> keywords matched against repo name, description,
# topics and primary language. Matching is case-insensitive substring matching.
AI_KEYWORD_CATEGORIES = {
    "LLM / NLP": [
        "llm", "large language model", "transformers", "huggingface", "hugging-face",
        "langchain", "llama", "gpt", "openai", "nlp", "bert", "rag",
        "retrieval-augmented", "prompt-engineering", "fine-tuning", "fine-tune",
    ],
    "Computer Vision": [
        "computer-vision", "computer vision", "opencv", "cv2", "image-classification",
        "object-detection", "segmentation", "yolo", "diffusers", "stable-diffusion",
        "image-generation",
    ],
    "Deep Learning Frameworks": [
        "pytorch", "tensorflow", "keras", "jax", "mxnet", "onnx",
    ],
    "Classical ML": [
        "scikit-learn", "sklearn", "xgboost", "lightgbm", "machine-learning",
        "machine learning",
    ],
    "MLOps": [
        "mlops", "mlflow", "kubeflow", "model-serving", "model-deployment",
        "airflow", "feature-store",
    ],
}

# Minimum number of distinct AI keyword hits (across all categories) required to
# keep a candidate. Filters out people who merely starred an AI repo once.
MIN_AI_SCORE = 1

# How many of a candidate's most-recently-updated repos to inspect for AI signal.
MAX_REPOS_PER_CANDIDATE = 10

# Paths
SEEN_PROFILES_PATH = "data/seen_profiles.json"
DASHBOARD_OUTPUT_PATH = "output/dashboard.html"

# GitHub Search API is rate-limited more strictly (30 req/min authenticated) than
# the regular REST API (5000 req/hr). Sleep this many seconds between search calls.
SEARCH_API_SLEEP_SECONDS = 2.1

# Sleep between per-candidate repo-detail fetches (regular REST API, generous budget).
DETAIL_API_SLEEP_SECONDS = 0.3

# Cap on total candidates processed per run, to keep runtime and rate-limit usage bounded.
MAX_CANDIDATES_PER_RUN = 150
