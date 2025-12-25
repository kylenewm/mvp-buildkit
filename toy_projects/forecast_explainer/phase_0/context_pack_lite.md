# Context Pack Lite — Forecast Explainer CLI (B02)

## What We're Building

A tiny CLI app (`forecast_explainer`) that reads a local JSON file and prints a human-readable weather summary with clothing suggestions.

## Key Facts

- **Build ID**: B02
- **Type**: Python CLI (Click-based)
- **Data Source**: Local `forecast.json` file only
- **No external calls**: Fully offline, deterministic

## Inputs

- `forecast.json`: Contains location and 5-day forecast data
- CLI args:
  - `--file PATH`: Path to forecast JSON (required)
  - `--day N`: Which day to explain (1-5, default 1)
  - `--units {f,c}`: Temperature units (default f)
  - `--style {brief,full}`: Output verbosity (default brief)

## Output

A short summary including:
- Date and location
- High/low temps
- Precipitation chance
- Wind speed
- Condition description
- 1-line "what to wear" suggestion

## Non-Goals

- Do NOT touch factory canonical artifacts
- Do NOT make any web or API calls
- Do NOT add database or caching
- Do NOT build a GUI

## Canonical Paths (Factory)

When the factory commits artifacts for this project:
- `spec/spec.yaml`
- `tracker/factory_tracker.yaml`
- `invariants/invariants.md`
- `.cursor/rules/00_global.md`
- `.cursor/rules/10_invariants.md`
- `prompts/step_template.md`
- `prompts/review_template.md`
- `prompts/patch_template.md`
- `prompts/chair_synthesis_template.md`
- `versions/<timestamp>_<run_id>/...`

## Success Criteria

```bash
python -m forecast_explainer explain --file data/forecast.json --day 2
# Prints: "Wednesday Dec 25: High 45°F, Low 33°F, 30% precip. Cloudy. Wear a warm jacket."
```

