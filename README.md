# Ebook Translator

> Translate EPUB files using Large Language Models (DeepSeek, OpenAI, and other OpenAI-compatible APIs)

[🇫🇷 Version française](README.fr.md)

## Overview

**Ebook Translator** is a Python tool that translates EPUB files using Large Language Models (LLMs) such as DeepSeek, OpenAI, and other OpenAI-compatible APIs. The tool segments ebook content, translates it through a multi-phase pipeline, and reconstructs the translated EPUB while preserving structure and metadata.

## Features

- **EPUB Translation**: Translates entire EPUB files while maintaining structure
- **Multi-Phase Pipeline**: Optional literary analysis and glossary extraction, then translation and refinement
- **LLM-Powered**: Uses advanced language models (DeepSeek, OpenAI, etc.)
- **Smart Segmentation**: Chunks content with token limits and configurable overlap
- **Parallel Processing**: Parallelizes translation calls for better performance
- **Metadata Preservation**: Keeps original title, authors, and structure
- **HTML Structure**: Preserves formatting, images, CSS, and layout
- **Two-Stage Validation**: Pydantic schema first, then content checks with targeted LLM corrections
- **Glossary Learning**: Terminology consistency with weighted proposals and conflict detection
- **Smart Logging**: Session-based logs with contextual naming

## Requirements

- Python 3.14 or higher
- [uv](https://docs.astral.sh/uv/) for dependency management
- API key for DeepSeek or OpenAI

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/NeOzay/ebook-translator.git
   cd ebook-translator
   ```

2. **Install dependencies**:
   ```bash
   uv sync --group dev
   ```

3. **Configure API keys**:
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and add your API key:
   ```bash
   API_KEY=sk-your-api-key-here
   ```

### Getting API Keys

**DeepSeek** (Recommended):
- Create an account at [DeepSeek Platform](https://platform.deepseek.com)
- Navigate to [API Keys](https://platform.deepseek.com/api_keys)
- Generate a new API key

**OpenAI** (Alternative):
- Create an account at [OpenAI Platform](https://platform.openai.com)
- Navigate to [API Keys](https://platform.openai.com/api-keys)
- Generate a new API key

## Usage

The pipeline is configured through chainable builders:

```python
from pathlib import Path

from ebook_translator import Language, LLMBuilder, PhasesBuilder, PipelineBuilder
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels

stats = (
    PipelineBuilder()
    .epub(Path("my_book.epub"))
    .output(Path("my_book_translated.epub"))
    .language(Language.FRENCH)
    .llm(
        LLMBuilder().default_client(
            Deepseek(
                DeepseekModels.FLASH,
                thinking=False,
                config={"temperature": 0.5},
            )
        )
    )
    .phases(
        PhasesBuilder()
        .add_literary_analysis()
        .add_initial_translation()
        .add_refinement()
    )
    .workers(2)
    .run()
)

for phase_name, phase_stats in stats.items():
    print(f"{phase_name}: {phase_stats.chunks_validated} chunks validated")
```

The model, thinking mode, and sampling parameters belong to the **client**: each provider has its own base URL and model enum. `LLMBuilder` only carries `LLM` options (`prompt_dir`, `max_retries`, `retry_delay`, `glossary_max_terms`).

### More Examples

See [examples/](examples/) — in particular [example_pipeline.py](examples/example_pipeline.py) for a full configuration and [example_phase0_analysis.py](examples/example_phase0_analysis.py) for a literary-analysis-only run.

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | ✅ Yes | Fallback API key used by every client provider, loaded from `.env` |
| `MISTRAL_API_KEY` | ⬜ No | Read first by the Mistral provider, before `API_KEY` |

Key resolution lives in `get_api_key` ([llm/clients/base.py](src/ebook_translator/llm/clients/base.py)): a provider may declare a dedicated variable via `_api_key_env` (Mistral does), and `API_KEY` is the shared fallback. A key passed explicitly to the client (`Deepseek(..., api_key=...)`) takes precedence over both. For OpenAI-compatible providers the base URL is not configurable through the environment: it is a class attribute (`Deepseek.base_url`).

## Development

**Type Checking** (must report 0 errors):
```bash
uv run basedpyright src/
```

**Run Tests**:
```bash
uv run pytest --no-cov
```

`uv run pytest` alone keeps the `--cov-fail-under=80` gate from `pyproject.toml`.
Coverage currently sits at ~72%, so it exits 1 even when every test passes.

**All quality checks**:
```bash
uv run pre-commit run --all-files
```

## Architecture

The pipeline runs a configurable list of phases, in order:

```
EPUB → [Phase 0: Literary Analysis]  (optional, sequential)
     → [Glossary Phase]              (optional, sequential)
     → [Phase 1: Initial Translation] (parallel)
     → [Phase 2: Refinement]          (sequential)
     → EPUB Output
```

Within each phase, `PhaseExecutor` segments the content, calls the LLM, validates the output against a Pydantic schema, then hands the result to the validation pool. Validated chunks are written to the cache by a dedicated save thread, and the final EPUB is rebuilt from the HTML DOM.

### Key Components

**Builders** ([pipeline/builder.py](src/ebook_translator/pipeline/builder.py)):
- `PipelineBuilder`, `LLMBuilder`, `PhasesBuilder` — the public configuration API

**Segmentator** ([segmentation/segmentator.py](src/ebook_translator/segmentation/segmentator.py)):
- Chunks content into token-bounded segments with head/body/tail context
- `overlap_ratio` below 1.0 is a percentage, at or above 1.0 a multiple of `max_tokens`

**ValidationWorkerPool** ([validation/](src/ebook_translator/validation/)):
- N `ValidationWorker` threads + 1 `SaveWorker`; the worker class is picked per phase (`UnifiedValidationWorker` with content checks, `SchemaOnlyValidationWorker` without)
- Validation/save decoupling keeps workers off the disk I/O path
- Failed checks trigger targeted LLM corrections; unrecoverable lines are dropped rather than rejecting the whole chunk

**LLM Client** ([llm/llm.py](src/ebook_translator/llm/llm.py)):
- OpenAI-compatible client with automatic retry and exponential backoff
- Structured output through Instructor for JSON phases
- Contextual logging with lazy file creation

**Content Checks** ([checks/content/](src/ebook_translator/checks/content/)):
- `LineCountCheck`: verifies all lines are translated
- `FragmentCountCheck`: verifies `</>` separator counts
- `PunctuationCheck`: verifies quote pair balance
- `SentenceCheck`: verifies sentence integrity

**Persistence** ([persistence/](src/ebook_translator/persistence/), [stores/](src/ebook_translator/stores/)):
- `ByteStore` for raw atomic I/O, `ChunkPersister` for cache layout, `PhaseStorage` to bind them

### Template Architecture

Jinja2 templates live in the `template/` submodule. Each prompt is a **pair** of files — `<name>_system.jinja` and `<name>_user.jinja` — resolved together by the `PhaseTemplate` and `RetryTemplate` enums.

```
template/
├── common/     # shared fragments, pulled in via {% include %}
├── phase/      # phase prompts (translate_base, translate_refine, analyze_chapter*, glossary)
└── retry/      # correction prompts, one per error type
```

### Project Structure

```
ebook-translator/
├── src/ebook_translator/
│   ├── checks/              # ContentCheck protocol + content/ implementations
│   ├── exporter/            # Markdown export for analyses and glossary
│   ├── glossary.py          # Glossary for terminology consistency
│   ├── htmlpage/            # HTML parsing and text replacement
│   ├── llm/                 # LLM client, providers, template renderers, retry registry
│   ├── persistence/         # ChunkPersister implementations
│   ├── pipeline/            # Pipeline, phases, executor, builders, storage
│   ├── segmentation/        # Segmentator, Chunk, chapter detection
│   ├── stores/              # ByteStore / Store
│   ├── translation/         # EPUB I/O
│   └── validation/          # Worker pool, unified worker, save worker, retry helpers
├── src/template/            # Jinja2 prompt templates (submodule)
├── examples/                # Runnable examples
├── tests/                   # Unit tests (374 tests)
├── docs/                    # Specialized documentation
└── logs/                    # Translation logs, one directory per session
    └── run_YYYYMMDD_HHMMSS/
```

For more details, see the complete documentation in [docs/](docs/) or [CLAUDE.md](CLAUDE.md).

## Documentation

| Document | Description |
|----------|-------------|
| **[CLAUDE.md](CLAUDE.md)** | Project overview and quick start |
| **[docs/SETUP.md](docs/SETUP.md)** | Configuration, installation, troubleshooting |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Technical architecture, components |
| **[docs/LITERARY_ANALYSIS.md](docs/LITERARY_ANALYSIS.md)** | Phase 0 and the `AnalyseChapter` schema |
| **[docs/VALIDATION.md](docs/VALIDATION.md)** | Validation system, checks, retry registry |
| **[docs/TEMPLATES.md](docs/TEMPLATES.md)** | LLM template architecture |
| **[docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md)** | Typing, docstrings, tests |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | Version history (0.12.0 onwards) |
| **[docs/CHANGELOG_ARCHIVE.md](docs/CHANGELOG_ARCHIVE.md)** | Version history 0.2.0 → 0.11.0 |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Planned features |
| **[docs/TECHNICAL_DEBT.md](docs/TECHNICAL_DEBT.md)** | Known debt, deliberately deferred |

## Security

**IMPORTANT**:
- ⚠️ **NEVER** commit the `.env` file to git (already in `.gitignore`)
- ⚠️ **NEVER** share your API keys publicly
- ⚠️ If a key is compromised, **revoke it immediately** on the platform

## License

This project is licensed under the MIT License.

## Author

**NeOzay** - [neozay.ozay@gmail.com](mailto:neozay.ozay@gmail.com)

## Links

- [Homepage](https://github.com/NeOzay/ebook-translator)
- [Issues](https://github.com/NeOzay/ebook-translator/issues)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
