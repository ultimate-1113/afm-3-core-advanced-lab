# Evaluation records

These records contain **AI-generated output**, including deliberately retained incorrect answers, in `result.text`, streamed snapshots, OCR text and tool-related fields. They are preliminary evaluation evidence; a successful generation status does not mean the answer is correct.

Only synthetic tasks and fixtures were used. Published logs replace machine-specific repository paths with `<LAB_ROOT>`; ANSI color escapes in CLI logs are removed. Prompts, generated answers, timing, token usage and grading data are preserved. Original host logs are retained outside this repository.

The repository's MIT license does not relicense model-generated output or grant model-training rights. The measured host's macOS license, section 6.E, prohibits using AI outputs to train, fine-tune or improve another AI model. See [the license review](../reports/license-review.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).

`regraded.jsonl` is derived from the case data and raw answers using the latest evaluator. `recovery-final.jsonl` and `resources.jsonl` replace invalid intermediate measurements for analysis. Intermediate records remain available and are explicitly excluded where applicable. `retry-initial.jsonl` used the misleading field name `model_invoked` for dispatch to the Runner; `retry.jsonl` uses `runner_request_sent`, and context errors can occur before actual generation.

`measurement-artifact-manifest.json` describes the original measurement snapshot, including unshipped build artifacts. Its hashes need not match path-normalized or portability-adjusted publication files. `final-artifact-manifest.json` describes the published snapshot and excludes build binaries and itself.
