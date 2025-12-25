# Artifact Registry (V0)

> **Single source of truth for canonical artifacts.**
> Machine-parseable sections below. Do not modify format.

## Canonical

- spec/spec.yaml
- tracker/factory_tracker.yaml
- invariants/invariants.md
- .cursor/rules/00_global.md
- .cursor/rules/10_invariants.md
- prompts/step_template.md
- prompts/review_template.md
- prompts/patch_template.md
- prompts/chair_synthesis_template.md
- docs/ARTIFACT_REGISTRY.md

## Generated

- versions/**

## Forbidden

- tracker/tracker.yaml
- prompts/hotfix_sync.md
- docs/build_guide.md
- COMMIT_MANIFEST.md

---

## Notes

- **Canonical**: Stable paths that `council commit` may write (additive-only).
- **Generated**: Snapshot directories; `versions/**` glob is always allowed.
- **Forbidden**: Deprecated paths; commit will fail if any write matches.

Run drift check:
```bash
python scripts/check_artifacts.py
```
