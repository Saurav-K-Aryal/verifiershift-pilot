# VerifierShift pilot

This study examines which observations justify a task verdict across authored booking, inventory-dispatch and support-escalation schemas. It makes 168 local model calls over 84 unique evidence packets per model. Typed checking resolves 48/48 complete worlds, while Gemma 4:26B resolves 34/48 correctly with 7 false accepts and Qwen 3.5:4B resolves 15/48 with 14 false accepts. Both models review all 24 incomplete observation classes. The added authoritative read changes the information available; it is not an equal-information algorithm improvement or a learned-autonomy guarantee.

Repository: https://github.com/Saurav-K-Aryal/verifiershift-pilot

## Manuscript

Editable sources are distributed publicly **only inside `overleaf.zip`**. Extract/upload `draft.tex`, `refs.bib`, and `figures/` to Overleaf. Select `draft.tex` as the main document and use pdfLaTeX with BibTeX. `references.bib` is an identical compatibility copy; the manuscript reads `refs.bib`. The ZIP contains manuscript assets, while experiment code and raw evidence are separate repository files. `paper.pdf` is a compiled preview.

## Verify recorded results without a model

From a cloned repository, run standard Python 3:

```sh
python3 verify_results.py
python3 reproduce_cpu.py --out results/new_cpu
```

The verifier reconstructs all 48 logical SQL worlds from the fixed generator, compares their captured content with observed packets, runs a separately implemented SQL evaluator, and checks all 168 raw requests/verdicts and recorded counts. It makes zero model/server calls. Original database binaries are omitted; logical content is checked rather than requiring binary SQLite-file equality across library versions. `results/observed/independent_readback.json` preserves the original local readback, which also checked original database hashes.

## Regenerate figures

Only plotting requires an additional package; the plotting environment used Matplotlib 3.11.2.

```sh
python3 -m pip install -r requirements.txt
python3 generate_figures.py
```

The generator reads recorded decisions, checks denominators, and records every figure-input SHA256 in `figure_data.json`. Neither plots nor verification perform model inference.

## Run a fresh native study

This optional step requires an already running local Ollama-compatible server and the two existing model tags. No model is downloaded. Coordinate GPU memory with other work first.

```sh
python3 -m pilots.strengthening.evidence_contracts --stage prepare --out results/new_native
python3 -m pilots.strengthening.evidence_contracts --stage infer --out results/new_native --model gemma4:26b
python3 -m pilots.strengthening.evidence_contracts --stage infer --out results/new_native --model qwen3.5:4b
```

Preparation freezes the actual local model digests. A tag alone does not identify the historical weights; compare `results/observed/model_*/model_provenance.json`. The fixed protocol uses temperature 0, context 4096, maximum 160 output tokens and thinking disabled. Each model block makes 84 calls and explicitly unloads its model. Outputs go into a new directory; no original evidence is overwritten. Native backend and model differences are descriptive confounds, not a release-age comparison.

## Interpretation

The incomplete twin worlds have identical packet bytes and opposite SQL truth. Complete read transactions add the missing authoritative policy and state. The trusted-capture assumption is explicit: hashes do not authenticate an arbitrary forged authority, and the metadata tests do not validate every malformed payload. The contracts are authored, the 48 worlds are paired, and no public-simulator or production agent trajectory is evaluated. Three invalid complete-evidence responses are retained without repair. Qwen's 17 complete-evidence reviews are distinguished from false accepts. Full tables and source/normalization hashes are in the recorded results and `PUBLICATION_PROVENANCE.json`.

## Classification and attribution

Suggested Preprints.org subject: **Computer Science and Mathematics**; topic within subject: **Artificial Intelligence and Machine Learning**. Optional MDPI collection from the verified local guide: *AI Agents: Progress, Architecture, and Applications*; this is a proposed editorial fit, not approval. Keywords: agent verification, policy shifts, tool evidence, evidence contracts, selective review.

Saurav K. Aryal, Howard University, directed the preliminary experiments. Implementation, execution, analysis and manuscript preparation used Codex assistance. The article's future work concerns versioned public-simulator adapters, typed baselines, semantic-label review, and measured cost/coverage; it makes no claim of a funded award or completed deployment.

## Preprints.org classification

Subject: **Computer Science and Mathematics**. Topic within Subject: **Artificial Intelligence and Machine Learning**. See `PREPRINTS_METADATA.txt` for the optional collection and its scope fit.

## Manuscript downloads

[Compiled PDF](paper.pdf) · [Overleaf ZIP](overleaf.zip). The ZIP contains the editable manuscript, bibliography and figures.
