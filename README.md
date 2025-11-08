# Ebook Translator

> Translate EPUB files using Large Language Models (DeepSeek, OpenAI, and other OpenAI-compatible APIs)

[🇫🇷 Version française](README.fr.md)

## Overview

**Ebook Translator** is a Python tool that translates EPUB files using Large Language Models (LLMs) such as DeepSeek, OpenAI, and other OpenAI-compatible APIs. The tool intelligently segments ebook content, translates it using asynchronous LLM calls, and reconstructs the translated EPUB while preserving structure and metadata.

## Features

- **EPUB Translation**: Translates entire EPUB files while maintaining structure
- **LLM-Powered**: Uses advanced language models (DeepSeek, OpenAI, etc.)
- **Smart Segmentation**: Intelligently chunks content with token limits and overlap
- **Async Processing**: Parallelizes translation calls for better performance
- **Metadata Preservation**: Keeps original title, authors, and structure
- **HTML Structure**: Preserves formatting, images, CSS, and layout
- **Automatic Validation**: Structural validation with progressive retry (reasoning mode)
- **Smart Logging**: Session-based logs with contextual naming
- **Quality Control**: 4 structural checks (lines, fragments, punctuation, sentences)
- **Template Architecture**: DRY templates with shared rules (-73% duplication)

## Requirements

- Python 3.12 or higher
- Poetry (for dependency management)
- API key for DeepSeek or OpenAI

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/NeOzay/ebook-translator.git
   cd ebook-translator
   ```

2. **Install dependencies**:
   ```bash
   poetry install
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

### Basic Usage

Create a Python file (e.g., `translate.py`):

```python
from ebook_translator import Language, LLM, EpubTranslator

# Configure the LLM
llm = LLM(
    model_name="deepseek-chat",
    url="https://api.deepseek.com",
    max_retries=3,        # Automatic retry (default)
    retry_delay=1.0,      # Initial delay in seconds
    temperature=0.5,      # Optimal coherence (default since v0.4.0)
)

# Translate the EPUB
translator = EpubTranslator(llm, epub_path="my_book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="my_book_translated.epub",
    max_concurrent=2,     # Number of parallel translations
    overlap_ratio=0.15,   # Context overlap (15%)
)
```

Then run:
```bash
python translate.py
```

### Complete Example

See [start.py](start.py) for a complete configuration example with all available parameters.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | ✅ Yes | - | DeepSeek API key for authentication |
| `DEEPSEEK_URL` | ❌ No | `https://api.deepseek.com` | Base API URL |
| `OPENAI_API_KEY` | ❌ No | - | OpenAI API key (alternative to DeepSeek) |

## Development

**Type Checking**:
```bash
pyright src/ebook_translator
```

**Run Tests**:
```bash
pytest tests/
```

## Architecture

The translation pipeline follows this flow:

1. **EPUB Loading** - Extracts metadata and content
2. **Segmentation** - Chunks content with overlap (default: 15%)
3. **Translation** - Parallel LLM calls with automatic retry
4. **Validation** - Structural verification (lines, fragments, punctuation)
5. **Saving** - Thread-safe persistence via SaveWorker
6. **Reconstruction** - Text replacement in HTML DOM
7. **EPUB Generation** - Creates translated file

### Key Components

**Segmentator** ([segmentation/segmentator.py](src/ebook_translator/segmentation/segmentator.py)):
- Chunks content into 2000-token segments (configurable)
- Supports overlap_ratio >= 1.0 for extended context (v0.7.0)
- Multi-chunk queue system

**ValidationWorkerPool** ([validation/](src/ebook_translator/validation/)):
- Multi-threaded architecture: N ValidationWorkers + 1 SaveWorker
- Validation/save decoupling → +33-50% throughput
- Progressive retry: attempt 1 (normal) + attempt 2 (reasoning)

**LLM Client** ([llm/llm.py](src/ebook_translator/llm/llm.py)):
- Async OpenAI client compatible with any OpenAI API
- Automatic retry with exponential backoff (v0.3.0)
- Reasoning mode support (deepseek-reasoner) for complex corrections (v0.8.0)
- Contextual logging with lazy file creation (v0.6.0)

**Validation Checks** ([checks/](src/ebook_translator/checks/)):
- `LineCountCheck`: Verifies all lines are translated
- `FragmentCountCheck`: Verifies `</>` separator counts
- `PunctuationCheck`: Verifies quote pair balance
- `SentenceCheck`: Verifies sentence counts

### Template Architecture

**Categories**:
- **TRANSLATE** (4 templates): Create new translations
- **CORRECT** (3 templates): Fix structural errors

**Shared Bases** (v0.9.0):
- `common_translate_rules.jinja` (199 lines): Shared TRANSLATE rules
- `common_correct_rules.jinja` (130 lines): Shared CORRECT rules

**Benefits**:
- -73% code duplication (1260 → 329 shared lines)
- 7× easier to maintain (1 file instead of 7)
- 100% guaranteed consistency

### Project Structure

```
ebook-translator/
├── src/ebook_translator/
│   ├── checks/              # Structural validation
│   │   ├── check_tests/    # 4 checks: LineCount, FragmentCount, Punctuation, Sentence
│   │   ├── pipeline.py     # ValidationPipeline orchestrator
│   │   └── retry_helper.py # Progressive retry with reasoning mode
│   ├── glossary.py          # Glossary for terminology consistency
│   ├── llm/                 # LLM client and template renderers
│   ├── pipeline/            # Translation pipeline (new since v0.9.0+)
│   ├── segmentation/        # Content segmentation (Segmentator, Chunk)
│   ├── transition/          # Phase transition management
│   └── validation/          # Multi-threaded architecture (ValidationWorkerPool, SaveWorker)
├── template/                # Jinja2 templates for LLM prompts
│   ├── common_translate_rules.jinja  # Shared TRANSLATE rules
│   ├── common_correct_rules.jinja    # Shared CORRECT rules
│   └── [7 specific templates]
├── tests/                   # Unit tests (107+ tests)
├── docs/                    # Specialized documentation
│   ├── SETUP.md            # Configuration and installation
│   ├── ARCHITECTURE.md     # Technical architecture
│   ├── VALIDATION.md       # Validation system
│   ├── TEMPLATES.md        # Template architecture
│   ├── CHANGELOG.md        # Version history
│   └── ROADMAP.md          # Future improvements
└── logs/                    # Translation logs (per session)
    └── run_YYYYMMDD_HHMMSS/ # Unique session
```

For more details, see the complete documentation in [docs/](docs/) or [CLAUDE.md](CLAUDE.md).

## Documentation

The project includes comprehensive documentation:

| Document | Description |
|----------|-------------|
| **[CLAUDE.md](CLAUDE.md)** | Complete project overview and quick start |
| **[docs/SETUP.md](docs/SETUP.md)** | Configuration, installation, troubleshooting |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Technical architecture, components |
| **[docs/VALIDATION.md](docs/VALIDATION.md)** | Validation system, progressive retry |
| **[docs/TEMPLATES.md](docs/TEMPLATES.md)** | LLM template architecture |
| **[docs/CHANGELOG.md](docs/CHANGELOG.md)** | Version history (v0.2.0 → v0.9.0) |
| **[docs/ROADMAP.md](docs/ROADMAP.md)** | Future improvements (Phase 2) |

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
