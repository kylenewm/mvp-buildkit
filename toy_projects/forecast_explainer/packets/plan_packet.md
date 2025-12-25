# Planning Packet — Forecast Explainer CLI (B02)

## Build Intent

Create a deterministic Python CLI that reads a local forecast JSON file and prints a human-readable weather summary with clothing suggestions.

**Build ID**: B02  
**Type**: Toy project for factory validation  
**Complexity**: Trivial (1-2 hour implementation)

## Requirements

### Functional
1. Read `forecast.json` from a specified path
2. Parse daily forecast entries (date, temps, precip, wind, condition)
3. Print a human-readable summary for a selected day
4. Include a 1-line clothing suggestion based on conditions
5. Support temperature unit conversion (F ↔ C)
6. Support brief vs full output modes

### Non-Functional
- Fully offline (no network calls)
- Deterministic output (same input → same output)
- Python 3.9+ compatible
- CLI built with Click

## CLI Interface

```bash
# Basic usage
python -m forecast_explainer explain --file PATH --day N

# Full options
python -m forecast_explainer explain \
  --file toy_projects/forecast_explainer/data/forecast.json \
  --day 2 \
  --units c \
  --style full
```

## Data Format

```json
{
  "location": "New York, NY",
  "timezone": "America/New_York",
  "daily": [
    {
      "date": "2025-12-24",
      "high_f": 42,
      "low_f": 32,
      "precip_pct": 20,
      "wind_mph": 12,
      "condition": "Cloudy"
    }
  ]
}
```

## Deliverables

The planning council should produce an implementation plan with:

### Tracker Steps (~6-8 steps)
1. Project scaffolding (pyproject.toml, src layout)
2. Data model (Pydantic or dataclass for forecast)
3. JSON loader with validation
4. Temperature conversion utilities
5. Summary formatter
6. Clothing suggester logic
7. CLI entrypoint with Click
8. Integration tests

### Repo Outputs (canonical paths only)
- `spec/spec.yaml` — project specification
- `tracker/factory_tracker.yaml` — step tracker
- `invariants/invariants.md` — project invariants
- `.cursor/rules/00_global.md` — global cursor rules
- `.cursor/rules/10_invariants.md` — invariant rules
- `prompts/step_template.md` — step execution prompt
- `prompts/review_template.md` — review prompt
- `prompts/patch_template.md` — patch prompt
- `prompts/chair_synthesis_template.md` — synthesis prompt
- `versions/<timestamp>_<run_id>/...` — snapshot

**Forbidden paths** (do not reference):
- `tracker/tracker.yaml` (deprecated)
- `prompts/hotfix_sync.md` (deprecated)
- `docs/build_guide.md` (deprecated)

## Proof Commands

After implementation, verify with:

```bash
# Day 1 summary (brief)
python -m forecast_explainer explain \
  --file toy_projects/forecast_explainer/data/forecast.json \
  --day 1

# Expected output (example):
# Tuesday Dec 24, New York, NY
# High: 42°F | Low: 32°F | Precip: 20% | Wind: 12 mph
# Condition: Cloudy
# → Wear a warm jacket and bring an umbrella just in case.

# Day 3 summary with Celsius
python -m forecast_explainer explain \
  --file toy_projects/forecast_explainer/data/forecast.json \
  --day 3 \
  --units c

# Full style output
python -m forecast_explainer explain \
  --file toy_projects/forecast_explainer/data/forecast.json \
  --day 2 \
  --style full
```

## Constraints

- No web or API calls
- No database or caching
- No GUI
- Do not modify factory canonical files
- Keep implementation under 200 lines

## Success Criteria

1. `python -m forecast_explainer explain --file <path> --day N` runs without error
2. Output is deterministic (same file + args → same output)
3. All 5 days in forecast.json can be explained
4. Clothing suggestion adapts to temperature and precipitation

