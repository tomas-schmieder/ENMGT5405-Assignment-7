# Context-window metrics (assignment §4.5)

Ten distinct 2025 tax documents (`data/fixtures/bench_ten_docs`) are processed sequentially by the Document Extraction agent in one thread, in the same fixed order, with the same model, prompt and schema. *Strategy off* replays the whole thread on every call; *strategy on* (selective recall) sends the current document plus a compact summary of session decisions. See `scripts/context_benchmark.py` and `src/memory.py`.

## Measured token counts: NOT YET RUN

No live run has been recorded in this repository yet, because it needs an Anthropic API key. Run on a machine with `ANTHROPIC_API_KEY` set:

```bash
python run.py benchmark --no-context-strategy
python run.py benchmark
python run.py metrics
```

This rewrites this file with the measured per-document table and chart. No token numbers are shown here until then.

## Harness dry run (size proxy, NOT tokens)

The same harness run offline (OCR instead of a model call). It records what would be sent: characters of text and the number of images per call. This only checks that the harness and both context strategies behave as designed; it is not a token measurement.

| Doc | Form | OFF images sent | OFF text chars | ON images sent | ON text chars |
|---:|---|---:|---:|---:|---:|
| 1 | W-2 | 1 | 844 | 1 | 904 |
| 2 | 1099-INT | 2 | 1,411 | 1 | 1,099 |
| 3 | 1099-DIV | 3 | 1,879 | 1 | 1,152 |
| 4 | 1099-R | 4 | 2,395 | 1 | 1,221 |
| 5 | W-2 | 5 | 2,844 | 1 | 1,301 |
| 6 | 1099-INT | 6 | 3,408 | 1 | 1,404 |
| 7 | SSA-1099 | 7 | 3,877 | 1 | 1,468 |
| 8 | 1099-DIV | 8 | 4,370 | 1 | 1,576 |
| 9 | 1099-INT | 9 | 4,893 | 1 | 1,662 |
| 10 | 1099-R | 10 | 5,369 | 1 | 1,723 |

Result consistency: 10/10 documents extracted identically in both runs.

