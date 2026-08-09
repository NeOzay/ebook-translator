# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ebook-translator** is a modular pipeline for translating EPUB ebooks using OpenAI-compatible LLM APIs (DeepSeek, OpenAI). The pipeline runs a configurable list of phases: optional literary analysis (Phase 0), optional glossary extraction, initial translation (Phase 1), and refinement (Phase 2).

**Public API**: `PipelineBuilder` / `LLMBuilder` / `PhasesBuilder` ([pipeline/builder.py](src/ebook_translator/pipeline/builder.py)) | **Examples**: [examples/](examples/), start with `example_pipeline.py`

There is no `__main__.py`: the package is used as a library, driven by the builders.

## Commands

```bash
# Install dependencies
uv sync --group dev

# Type checking — must report 0 errors
uv run basedpyright src/

# Run all tests. NOTE: coverage is always on (pyproject `addopts`) with a
# --cov-fail-under=80 gate. Coverage currently sits at ~72%, so this command
# exits 1 even when every test passes — read the test summary, not the exit code.
uv run pytest

# Run a specific test file or function
uv run pytest tests/path/to/test_file.py::TestClass::test_function -v

# Tests without the coverage gate
uv run pytest --no-cov

# HTML coverage report (written to htmlcov/)
uv run pytest --cov-report=html

# Comparative pipeline bench: runs N variants, writes bench/runs/<run_id>/
# (`python -m ebook_translator.bench` is equivalent, and needs no install)
uv run ebook-bench bench/config_exemple.py

# Per-phase audit against its spec: reads a cache, no LLM call, writes audit/runs/<id>/
uv run ebook-audit "bench/runs/<run_id>/work/<variant>/cache" --phase glossary

# Format + lint (ruff does both: `format` replaces black, the I-rules sort imports)
uv run ruff format src/ tests/ && uv run ruff check --fix src/ tests/

# All quality checks at once (runs ruff format, ruff check, basedpyright)
uv run pre-commit run --all-files
```

## Pipeline Architecture

`Pipeline` ([pipeline/pipeline.py](src/ebook_translator/pipeline/pipeline.py)) orchestrates:

```
EPUB → [Phase 0: Literary Analysis (optional, sequential)]
     → [Glossary Phase (optional, sequential)]
     → [Phase 1: Initial Translation (parallel)]
     → [Phase 2: Refinement (sequential)]
     → EPUB Output
```

Two type parameters run through the whole system:

- **`M` (payload)** — Pydantic model validating the *shape* of the LLM output
- **`DT` (data)** — `TypedDict` view flowing through queues and cache. `M.build()` produces `DT`; the conversion is not reversible, so the Pydantic instance is dropped at the executor.

Each phase extends `PhaseBase` ([pipeline/base.py](src/ebook_translator/pipeline/base.py)) and declares:
- `execution_mode`: PARALLEL or SEQUENTIAL
- `max_tokens`, `overlap_ratio`, `head_tail_balance`: segmentation parameters
- `chunk_type`, `payload_type` (`M`), `data_type` (`DT`)
- `content_checks`: tuple of `ContentCheck` run after schema validation
- `persister`: `ChunkPersister` determining the cache layout
- `depends_on`: phases whose output is required as input
- Hooks: `before_phase`, `before_chunk`, `after_response` (executor thread, before content checks), `on_save` (SaveWorker thread, after validation and write), `after_phase`

**Within each phase**, `PhaseExecutor` ([pipeline/executor.py](src/ebook_translator/pipeline/executor.py)):
1. `Segmentator` splits HTML items into chunks (head/body/tail)
2. Cached chunks are re-submitted for validation without an LLM call
3. Otherwise: `render_prompt()` → LLM (text or Instructor path) → `payload_type.model_validate()` → `build()` → `DT`
4. Chunks are submitted to `ValidationWorkerPool`
5. `ValidationWorker` threads apply `content_checks` and request targeted corrections
6. `SaveWorker` writes validated data through the phase's `ChunkPersister`

## Key Modules

| Module | Role | Key Files |
|--------|------|-----------|
| `pipeline/` | Orchestration | `pipeline.py`, `base.py`, `executor.py`, `builder.py`, `context.py`, `store_manager.py`, `phase_storage.py` |
| `pipeline/phases/` | Phase implementations | `literary_analysis.py`, `glossary.py`, `initial_translation.py`, `refinement.py` |
| `segmentation/` | Chunking + chapter detection | `segmentator.py`, `chunk.py`, `chapter.py`, `chapter_detector.py` |
| `llm/` | LLM client, providers, templates, retry registry | `llm.py`, `clients/` (`protocol.py`, `base.py`, `client.py`, `deepseek.py`, `mistral.py`), `errors.py`, `template_renderers.py`, `retry_registry.py` |
| `validation/` | Multi-thread validation/save | `validation_worker_pool.py`, `worker_base.py`, `unified_worker.py`, `schema_only_worker.py`, `save_worker.py`, `worker_retry.py` |
| `checks/` | Validation rules | `content_check.py`, `content/` |
| `persistence/` | Cache layout | `chunk_persister.py`, `line_indexed_persister.py`, `memoized_chunk_persister.py` |
| `stores/` | Byte-level cache | `byte_store.py`, `store.py` |
| `exporter/` | Markdown export | `analysis_exporter.py`, `glossary_exporter.py` |
| `bench/` | Comparative bench | `suite.py`, `runner.py`, `worker.py`, `workspace.py`, `collect.py`, `report.py` |
| `audit/` | Per-phase audit against a spec | `auditor.py`, `findings.py`, `source.py`, `glossary_auditor.py`, `report.py`, `specs/` |
| `htmlpage/` | HTML parsing and text replacement | `page.py`, `replacement.py`, `bilingual.py` |
| `translation/` | EPUB I/O | `epub_handler.py`, `language.py` |

## Data Formats

**LLM output format** — single source of truth: `LineIndexedLLMResponse` ([template/phase/translation_models.py](src/template/phase/translation_models.py)):
- Lines numbered with tags: `<0/>text\n<1/>text\n...`
- Fragment separator within a line: `</>` (must be preserved exactly)
- End marker: `[=[END]=]`

The glossary phase has its own textual format, tabular: one line per term, four columns separated by `|`, closed by the same `[=[END]=]` marker — see `LLMGlossaryModel` ([template/phase/glossary_models.py](src/template/phase/glossary_models.py)). It parses the raw string in a `mode="before"` validator; malformed lines are dropped with a `WARNING` rather than retried.

Phase 0 is the only phase with structured output: it goes through Instructor on its own Pydantic schema.

**Persistence** — three layers:
- `ByteStore` ([stores/byte_store.py](src/ebook_translator/stores/byte_store.py)): raw bytes, per-file locks + atomic rename. `FileByteStore` is the disk implementation.
- `ChunkPersister` ([persistence/](src/ebook_translator/persistence/)): decides *what* is written. `LineIndexedPersister` (one file per chunk, `{line_index: text}`), `MemoizedChunkPersister` (`outer_key`/`inner_key` memoization).
- `PhaseStorage` ([pipeline/phase_storage.py](src/ebook_translator/pipeline/phase_storage.py)): binds a persister, a store, and an optional fallback.

`StoreManager` creates one `Store` per phase under `<cache_dir>/<store_key>/`. Default `cache_dir` is `<epub_dir>/.<epub_stem>_cache/`.

**Glossary** ([glossary.py](src/ebook_translator/glossary.py)): learned from translations with weighted proposals, confidence and dominance scores, conflict detection. Populated by `GlossaryPhase`, exported to prompts for Phases 1 and 2.

Confidence is `dominance × mass`, with `mass = w / (w + 2)`. Two thresholds follow, both derived rather than hard-coded: `DEFAULT_MIN_REINJECTION_WEIGHT` (3) decides whether the glossary phase prompt shows a term's proposals or only its surface form, and `converged_weight()` (5) is the unanimous weight needed for high confidence. A book shorter than 5 glossary chunks therefore converges nothing — re-emitting an unconverged term is the mechanism, not a fault.

**Glossary seeding** ([glossary_seed.py](src/ebook_translator/glossary_seed.py)): fills the glossary before any LLM call, so selection mechanisms can be exercised without waiting for a full run. A TOML file states the *intent* — `niveau = "valide" | "arbitrer" | "emergent"`, matching the three groups of `glossary_existing_block.jinja` — and weights are derived from it. `user = true` yields a validated, authoritative entry. Wired through `PipelineBuilder.glossary()` / `.glossary_seed()`, both resolved at `build()` in any order. Example: [bench/seeds/exemple.toml](bench/seeds/exemple.toml).

## Phase 0: Literary Analysis

`LiteraryAnalysisPhase` ([pipeline/phases/literary_analysis.py](src/ebook_translator/pipeline/phases/literary_analysis.py)) produces an `AnalyseChapter` per chapter block (5000 tokens, sequential, 1 worker), validated entirely by its Pydantic schema through Instructor — `content_checks = ()`.

The schema is stratified: `noyau_stable` (genre, register, style, tone, translation guidance) and `couche_narrative` (summary, arcs, tensions, themes, cultural references). Analysis is **incremental**: each block carries forward and enriches the previous block's sheet.

Downstream phases read it through `latest_analysis_for` injected into `Chapters` as an `AnalysisLookup` callable. See [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md).

## Validation System

Validation happens in two stages: the **schema** (`payload_type`, applied by the executor) then the **content** (`content_checks`, applied by the worker).

`ValidationWorkerPool` ([validation/validation_worker_pool.py](src/ebook_translator/validation/validation_worker_pool.py)):
- The worker class is picked **per phase** on `phase.content_checks`: `UnifiedValidationWorker` when checks exist (data must be line-indexed), `SchemaOnlyValidationWorker` otherwise (Phase 0, glossary — data passes through untouched). Both share the `ValidationWorker` base ([validation/worker_base.py](src/ebook_translator/validation/worker_base.py))
- N `UnifiedValidationWorker` threads: apply `content_checks` check-by-check, request targeted LLM corrections on failure
- 1 `SaveWorker` thread (I/O-bound): writes through the phase's `ChunkPersister` in FIFO order
- If a failure survives `max_attempts`, its `relevant_indices` are dropped and the chunk is saved partial — a chunk with holes beats a rejected chunk

Correction routing lives in `RETRY_REGISTRY` ([llm/retry_registry.py](src/ebook_translator/llm/retry_registry.py)), which maps each `ErreursType` to a retry template, a params `TypedDict`, a `build` function, and a merge mode.

**Available checks** ([checks/content/](src/ebook_translator/checks/content/)): `LineCountCheck`, `FragmentCountCheck`, `PunctuationCheck`, `SentenceCheck`. Each implements `run(data, source)` and declares `error_type`, `retry_strategy`, `max_attempts`. See [docs/VALIDATION.md](docs/VALIDATION.md).

## Templates

Jinja2 templates live in the `template/` submodule, rendered via `TemplateRenderer` ([llm/template_renderers.py](src/ebook_translator/llm/template_renderers.py)). Each prompt is a **pair** `<name>_system.jinja` + `<name>_user.jinja`, resolved by the `PhaseTemplate` (prefix `phase/`) and `RetryTemplate` (prefix `retry/`) enums.

- `phase/translate_base_*` — Phase 1 initial translation
- `phase/translate_refine_*` — Phase 2 refinement (includes glossary)
- `phase/analyze_chapter_layered_*` — Phase 0 stratified analysis
- `phase/glossary_*` — glossary extraction
- `retry/*` — correction prompts, one per error type
- `common/*` — shared fragments pulled in via `{% include %}`

Template parameters are `TypedDict`s in [template/template_params.py](src/template/template_params.py). See [docs/TEMPLATES.md](docs/TEMPLATES.md).

## Code Standards

- **Strict typing**: `uv run basedpyright src/` must return 0 errors. All function parameters and return types must be annotated.
- **Docstrings**: Google format only for all public functions/classes (`Args:`, `Returns:`, `Raises:`, `Example:`)
- **Tests**: 80% minimum coverage for new code; all tests must pass before commit
- **Incremental development**: For complex features, decompose into independently testable sub-tasks with atomic commits

Beware of `**kwargs` unpacking typed as `dict[str, Any]`: it hides non-existent keyword arguments from basedpyright. Prefer explicit calls.

See [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) for detailed standards and examples.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | Yes | Fallback API key, read by every provider |
| `MISTRAL_API_KEY` | No | Read first by the Mistral provider, before `API_KEY` |

Key resolution lives in `get_api_key` ([llm/clients/base.py](src/ebook_translator/llm/clients/base.py)): a provider may declare a dedicated variable through `_api_key_env` (Mistral does), and `API_KEY` is the common fallback. A key passed explicitly to the client (`Deepseek(..., api_key=...)`) wins over both. For OpenAI-compatible providers the base URL is a class attribute (`Deepseek.base_url`), not an environment variable.

Copy `.env.example` → `.env` and set your key. See [docs/SETUP.md](docs/SETUP.md).

## Documentation Map

| Document | Content |
|----------|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system design, data flow, all components |
| [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md) | Phase 0 details, `AnalyseChapter` schema |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Validation pipeline, checks, retry registry |
| [docs/TEMPLATES.md](docs/TEMPLATES.md) | Template architecture, variables, format |
| [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | Type annotations, docstrings, tests |
| [docs/BENCH.md](docs/BENCH.md) | Comparative pipeline bench, shared phases, blind arbitration |
| [docs/AUDIT.md](docs/AUDIT.md) | Per-phase audit against its spec, metrics without thresholds |
| [docs/SETUP.md](docs/SETUP.md) | Installation, API keys, dev environment |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned features (not yet implemented) |
| [docs/TECHNICAL_DEBT.md](docs/TECHNICAL_DEBT.md) | Known debt, deliberately deferred, with what it would take to clear it |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Version history (0.12.0 onwards) |
| [docs/CHANGELOG_ARCHIVE.md](docs/CHANGELOG_ARCHIVE.md) | Version history 0.2.0 → 0.11.0, kept as-is |
