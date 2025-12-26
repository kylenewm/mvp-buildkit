"""Constants for the council runner."""

import os

# Default models for council workflows, temporary defaults for testing purposes due to lower latency
DEFAULT_MODELS = [
    "google/gemini-2.5-flash-lite",
    "google/gemini-3-flash-preview",
]

DEFAULT_CHAIR_MODEL = "google/gemini-3-flash-preview"

# Triage model: cheap + fast, uses first default model
DEFAULT_TRIAGE_MODEL = os.getenv("COUNCIL_TRIAGE_MODEL", DEFAULT_MODELS[0])
DEFAULT_TRIAGE_TIMEOUT_S = float(os.getenv("COUNCIL_TRIAGE_TIMEOUT_S", "10"))




#default for actual use

# DEFAULT_MODELS = [
#     "openai/gpt-5-mini",
#     "anthropic/claude-sonnet-4.5",
#     "google/gemini-2.5-flash-lite",
# ]

# DEFAULT_CHAIR_MODEL = "openai/gpt-5-mini"

# Comma-separated string for CLI help
DEFAULT_MODELS_CSV = ",".join(DEFAULT_MODELS)

