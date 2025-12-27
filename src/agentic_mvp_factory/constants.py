"""Constants for the council runner."""

import os

# Default models for council workflows, temporary defaults for testing below
#     "google/gemini-2.5-flash-lite",
#     "google/gemini-3-flash-preview",
# ]

# DEFAULT_CHAIR_MODEL = "google/gemini-3-flash-preview"


#default for actual use

DEFAULT_MODELS = [
    "google/gemini-3-pro-preview",
    "anthropic/claude-opus-4.5"
]

DEFAULT_CHAIR_MODEL = "openai/gpt-5.2"

DEFAULT_TRIAGE_MODEL = 'google/gemini-3-flash-preview'
DEFAULT_TRIAGE_TIMEOUT_S = float(os.getenv("COUNCIL_TRIAGE_TIMEOUT_S", "10"))



# Comma-separated string for CLI help
DEFAULT_MODELS_CSV = ",".join(DEFAULT_MODELS)

