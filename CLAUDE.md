# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ebook-translator** is a modular pipeline for translating EPUB ebooks using OpenAI-compatible LLM APIs (DeepSeek, OpenAI). The pipeline has three phases: optional literary analysis (Phase 0), initial translation (Phase 1), and refinement (Phase 2).

**Entry point**: `src/ebook_translator/__main__.py` | **Example**: `examples/test.py`

## Commands

```bash
# Install dependencies
uv sync --group dev

# Type checking — must report 0 errors
uv run basedpyright src/

# Run all tests
uv run pytest

# Run a specific test file or function
uv run pytest tests/path/to/test_file.py::TestClass::test_function -v

# Run tests with coverage
uv run pytest --cov=src/ebook_translator --cov-report=html

# Format + lint
uv run black src/ tests/ && uv run isort src/ tests/ && uv run ruff check src/ tests/

# All quality checks at once (runs black, isort, ruff, basedpyright)
uv run pre-commit run --all-files
```

## Pipeline Architecture

`Pipeline` ([pipeline/pipeline.py](src/ebook_translator/pipeline/pipeline.py)) orchestrates:

```
EPUB → [Phase 0: Literary Analysis (optional, sequential)]
     → [Phase 1: Initial Translation (parallel)]
     → [Transition: GlossaryValidation (optional)]
     → [Phase 2: Refinement (sequential)]
     → EPUB Output
```

Each phase extends `PhaseBase` ([pipeline/base.py](src/ebook_translator/pipeline/base.py)) and declares:
- `execution_mode`: PARALLEL or SEQUENTIAL
- `max_tokens`, `overlap_ratio`: segmentation parameters
- `checks`: list of `Check` instances run after each LLM response
- Hooks: `before_phase/chunk`, `after_phase/chunk`

**Within each phase**, `PhaseExecutor` ([pipeline/executor.py](src/ebook_translator/pipeline/executor.py)):
1. `Segmentator` splits HTML items into `Chunk` objects (head/body/tail)
2. Chunks are submitted to `ValidationWorkerPool`
3. `ValidationWorker` threads translate via LLM and validate with checks
4. `SaveWorker` writes validated translations to `Store`

## Key Modules

| Module | Role | Key Files |
|--------|------|-----------|
| `pipeline/` | Orchestration | `pipeline.py`, `base.py`, `executor.py`, `context.py`, `store_manager.py` |
| `pipeline/phases/` | Phase implementations | `literary_analysis.py`, `initial_translation.py`, `refinement.py` |
| `segmentation/` | Chunking + chapter detection | `segmentator.py`, `chunk.py`, `chapter_detector.py` |
| `llm/` | LLM client + Jinja2 templates | `llm.py`, `template_renderers.py` |
| `validation/` | Multi-thread validation/save | `validation_worker_pool.py`, `validation_worker.py`, `save_worker.py` |
| `checks/` | Validation rules | `pipeline.py`, `check_tests/` |
| `stores/` | Translation cache (JSON) | `store.py` |
| `htmlpage/` | HTML parsing and text replacement | `page.py`, `replacement.py` |
| `translation/` | EPUB I/O + LLM output parsing | `epub_handler.py`, `parser.py` |
| `analysis/` | Phase 0 data types + validator | `translation_context.py`, `validator.py` |
| `transition/` | Between-phase logic | `transitions/glossary_validation.py` |

## Data Formats

**LLM output format** (parsed by [translation/parser.py](src/ebook_translator/translation/parser.py)):
- Lines numbered with tags: `<0/>text\n<1/>text\n...`
- Fragment separator within a line: `</>` (must be preserved exactly)
- End marker: `[=[END]=]`

**Store** ([stores/store.py](src/ebook_translator/stores/store.py)): JSON files at `cache/{phase_name}/` mapping `{line_index: translated_text}`. Thread-safe with per-file locks + atomic rename.

**Glossary** ([glossary.py](src/ebook_translator/glossary.py)): Learned automatically from translations, exported to prompts for Phase 2. Pre-populated by Phase 0 with `proposition_traduction` from `ContexteTraduction`.

## Phase 0: Literary Analysis

`LiteraryAnalysisPhase` ([pipeline/phases/literary_analysis.py](src/ebook_translator/pipeline/phases/literary_analysis.py)) runs before translation to extract a `ContexteTraduction` JSON ([analysis/translation_context.py](src/ebook_translator/analysis/translation_context.py)) per chapter:
- Literary analysis (tone, style, themes, cultural references, translation guidance)
- Glossary with `proposition_traduction` per term (auto-populates `Glossary`)

Uses `SequentialChapterDetector` ([segmentation/chapter_detector.py](src/ebook_translator/segmentation/chapter_detector.py)) via EPUB spine. Each `ChapterChunk` is up to 8000 tokens. See [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md).

## Validation System

`ValidationWorkerPool` ([validation/validation_worker_pool.py](src/ebook_translator/validation/validation_worker_pool.py)):
- N `ValidationWorker` threads (CPU-bound): apply `ValidationPipeline` checks, request LLM corrections on failure
- 1 `SaveWorker` thread (I/O-bound): writes to `Store` in FIFO order
- Progressive retry: attempt 1 (normal model) → attempt 2 (reasoning model, `deepseek-reasoner`)
- Chunks are rejected and logged if validation still fails after retries

**Available checks** ([checks/check_tests/](src/ebook_translator/checks/check_tests/)): `LineCountCheck`, `FragmentCountCheck`, `PunctuationCheck`, `SentenceCheck`. Each implements `validate()` and `correct()`. See [docs/VALIDATION.md](docs/VALIDATION.md).

## Templates

Jinja2 templates in `template/` rendered via `TemplateRenderer` ([llm/template_renderers.py](src/ebook_translator/llm/template_renderers.py)):
- `translate_base.jinja` — Phase 1 initial translation
- `translate_refine.jinja` — Phase 2 refinement (includes glossary)
- `analyze_chapter_simplified.jinja` — Phase 0 analysis (JSON mode)
- `retry_*.jinja` — Correction templates for validation failures
- `common_translate_rules.jinja`, `common_correct_rules.jinja` — Shared base rules (DRY)

## Code Standards

- **Strict typing**: `uv run basedpyright src/` must return 0 errors. All function parameters and return types must be annotated.
- **Docstrings**: Google format only for all public functions/classes (`Args:`, `Returns:`, `Raises:`, `Example:`)
- **Tests**: 80% minimum coverage for new code; all tests must pass before commit
- **Incremental development**: For complex features, decompose into independently testable sub-tasks with atomic commits

See [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) for detailed standards and examples.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | Yes | DeepSeek API key |
| `DEEPSEEK_URL` | No | API base URL (default: `https://api.deepseek.com`) |
| `OPENAI_API_KEY` | No | Alternative to DeepSeek |

Copy `.env.example` → `.env` and set your key. See [docs/SETUP.md](docs/SETUP.md).

## Documentation Map

| Document | Content |
|----------|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system design, data flow, all components |
| [docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md) | Phase 0 details, `ContexteTraduction` schema |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Validation pipeline, checks, retry logic |
| [docs/TEMPLATES.md](docs/TEMPLATES.md) | Template architecture, variables, format |
| [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | Type annotations, docstrings, tests |
| [docs/SETUP.md](docs/SETUP.md) | Installation, API keys, dev environment |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned features (not yet implemented) |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Version history |
