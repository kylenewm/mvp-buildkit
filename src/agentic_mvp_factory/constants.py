"""Constants for the council runner."""

# Default models for council workflows
DEFAULT_MODELS = [
    "openai/gpt-5-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash-lite",
]

# Default chair model
DEFAULT_CHAIR_MODEL = "openai/gpt-5-mini"

# Comma-separated string for CLI help
DEFAULT_MODELS_CSV = ",".join(DEFAULT_MODELS)

