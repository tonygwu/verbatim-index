# Predictions acceptance audit, 2026-09-12

Work claimed by `repo-4`. Status: attempted, review in progress.

Scope: compare the extraction and verification specs, classify the 13 recorded
disagreements, assess the 11/24 acceptance rate, and correct the page wording.
No model calls or data changes are part of this audit.

Source pins: public code `0a3b32c`, private data `06f1ec2`.
The supplied corpus check returned exactly `11 13 0.4583` before review.

Verification:

```sh
.venv/bin/python -c "import json;c=json.load(open('data/predictions/index.json'))['corpus'];print(c['accepted'],c['rejected_by_verifier'],round(c['agreement_rate'],4))"
```
