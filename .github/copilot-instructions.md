# Copilot Instructions - ebook-translator

AI coding assistant guide for the **ebook-translator** project: a modular LLM-powered EPUB translation system with strict validation and quality control.

## Architecture Overview

**Modular pipeline architecture** with phase-based execution:

```
EPUB → Phase 1 (Initial Translation 2000 tokens) → Glossary Transition →
Phase 2 (Refinement 300 tokens) → HTML Reconstruction → Translated EPUB
```

### Key Components

- **Pipeline** ([`pipeline/`](../src/ebook_translator/pipeline/)): Orchestrates phases and transitions. Each phase extends `PhaseBase` with declarative configuration (singleton pattern).
- **Segmentator** ([`segmentation/`](../src/ebook_translator/segmentation/)): Chunks content by tokens with configurable overlap (default: 15%). Supports `overlap_ratio >= 1.0` for extended context.
- **ValidationWorkerPool** ([`validation/`](../src/ebook_translator/validation/)): Multi-threaded architecture with N ValidationWorkers + 1 SaveWorker for +33-50% throughput. SaveWorker provides FIFO ordering and thread-safe callbacks.
- **LLM Client** ([`llm/llm.py`](../src/ebook_translator/llm/llm.py)): Async OpenAI-compatible client with exponential backoff retry and reasoning mode support (`deepseek-reasoner`).
- **Templates** ([`template/`](../template/)): DRY Jinja2 architecture with shared bases (`common_translate_rules.jinja`, `common_correct_rules.jinja`) reducing duplication by 73%.

### Data Flow

1. **Segmentation**: Content → Chunks (head/body/tail with overlap)
2. **Translation**: LLM query → Parser → ValidationPipeline → SaveWorker → Store
3. **Progressive Retry**: Failed validation → Attempt 1 (normal) → Attempt 2 (reasoning mode) → +10-20% success rate
4. **Reconstruction**: HtmlPage text replacement preserving DOM structure

## Critical Patterns

### 1. Phase Creation (Declarative Configuration)

Phases use **class-level configuration** (no `__init__` parameters):

```python
class MyPhase(PhaseBase):
    name = "my_phase"                    # Store key
    max_tokens = 1500
    overlap_ratio = 0.15
    execution_mode = ExecutionMode.PARALLEL
    checks = [LineCountCheck(), FragmentCountCheck()]
    max_workers = 4                      # Optional, default: 4

    @classmethod
    def render_prompt(cls, chunk: Chunk, context: ChunkContext) -> str:
        return context.llm.renderer.render_translate(context.target_language)
```

**Important**: Phases are **singletons**. Access via class methods, never `self`.

### 2. Translation Format (STRICT)

All LLM outputs must follow this structure:

```
<0/>Translated first line
<1/>Second line</>with fragment separator
<2/>Third line
[=[END]=]
```

**Mandatory elements**:
- `<N/>` numbering: MUST match original exactly (no additions/deletions/modifications)
- `</>` separators: MUST preserve exact count (marks multi-fragment HTML tags)
- `[=[END]=]` marker: Validates completion

**Validation checks**:
- `LineCountCheck`: Verifies all lines translated
- `FragmentCountCheck`: Verifies `</>` count preserved
- `PunctuationCheck`: Verifies quote pair balance
- `SentenceCheck`: Verifies sentence integrity

### 3. Store Management (Thread-Safe)

Use `StoreManager` for multi-phase caching:

```python
store_manager = StoreManager(cache_dir=Path("cache"))
initial_store = store_manager.get_store("initial")
refined_store = store_manager.get_store("refined")

# Thread-safe save with file locks
initial_store.save(key="chunk_001", value={"0": "Translation"})
```

**Windows caveat**: Store handles `PermissionError` during atomic writes (temp file + rename pattern).

### 4. Glossary System

Automatic terminology learning:

```python
# Phase 1: No glossary
class InitialTranslationPhase(PhaseBase):
    @classmethod
    def after_chunk(cls, chunk, result, context):
        context.glossary.learn(result, chunk.body)  # Auto-learn

# Transition: Filter conflicts
class GlossaryValidationTransition(TransitionBase):
    @classmethod
    def execute(cls, context):
        glossary = context.glossary
        filter_conflicting_translations(glossary)  # 1 term → 1 translation

# Phase 2: Use glossary
class RefinementPhase(PhaseBase):
    @classmethod
    def before_chunk(cls, chunk, context):
        context.glossary.export_for_translation()  # Inject into prompt
```

## Development Workflow

### Strict Type Checking (MANDATORY)

**basedpyright strict mode**: 0 errors tolerated.

```python
# ✅ GOOD: Complete typing
def validate_chunk(
    chunk: Chunk,
    texts: dict[int, str],
    llm: LLM,
    max_retries: int = 2
) -> dict[int, str]:
    result: dict[int, str] = {}
    return result

# ❌ BAD: Missing types
def validate_chunk(chunk, texts, llm, max_retries=2):
    result = {}
    return result
```

**Type aliases for clarity**:

```python
from typing import TypeAlias

TranslationMap: TypeAlias = dict[int, str]
GlossaryData: TypeAlias = dict[str, dict[str, int]]
```

### Testing Requirements

- **Coverage**: ≥80% for new code
- **Pattern**: AAA (Arrange-Act-Assert)
- **Mocking**: Use `unittest.mock` for LLM calls

```python
def test_validation_with_mock_llm():
    # Arrange
    mock_llm = Mock()
    mock_llm.query.return_value = "<0/>Translation\n[=[END]=]"

    # Act
    result = translator.translate(chunk, mock_llm)

    # Assert
    assert result == {0: "Translation"}
    mock_llm.query.assert_called_once()
```

### Pre-Commit Checklist

```bash
uv run basedpyright src/                    # Type checking (strict)
uv run pytest --cov=src/ebook_translator  # Tests + coverage ≥80%
uv run pre-commit run --all-files      # ruff format, ruff check, basedpyright
```

### Commit Messages

**Convention**: `type: description`

```bash
feat: Add QuotationMarkCheck for balanced quote validation
fix: Chunk overlap calculation when max_tokens < overlap_tokens
refactor: Extract template rendering to dedicated class
test: Add integration tests for progressive retry system
docs: Update ARCHITECTURE.md with SaveWorker benefits
```

## Common Tasks

### Add a New Validation Check

1. Create check class:

```python
# checks/check_tests/my_check.py
class MyCheck(Check):
    name = "MyCheck"

    def validate(self, context: ValidationContext) -> CheckResult:
        # Return CheckResult(is_valid=True/False, error_data={})

    def correct(self, context: ValidationContext) -> dict[int, str]:
        # Use context.llm.query() with correction template
```

2. Add to phase:

```python
class InitialTranslationPhase(PhaseBase):
    checks = [LineCountCheck(), FragmentCountCheck(), MyCheck()]
```

3. Create template in `template/retry_correct_my_check.jinja`:

```jinja
{% include 'common_correct_rules.jinja' %}

## Specific correction instructions
[...]
```

### Add a New Phase

```python
# pipeline/phases/my_phase.py
class MyPhase(PhaseBase):
    name = "my_phase"
    max_tokens = 1000
    overlap_ratio = 0.2
    execution_mode = ExecutionMode.PARALLEL
    depends_on = [InitialTranslationPhase]  # Optional
    checks = [LineCountCheck()]

    @classmethod
    def render_prompt(cls, chunk, context):
        # Access previous phase results:
        initial = context.store_manager.get_store("initial")
        translation = initial.get(chunk.key)
        return context.llm.renderer.render_custom(chunk, translation)
```

### Modify LLM Templates

**Do NOT edit individual templates for shared rules**. Edit base templates instead:

```bash
# For TRANSLATE templates (translate_base, translate_refine, etc.)
vim template/common_translate_rules.jinja

# For CORRECT templates (retry_correct_*)
vim template/common_correct_rules.jinja

# Test changes
uv run python test_template_manual.py translate_base
```

## Project Structure

```
src/ebook_translator/
├── pipeline/           # Phase orchestration (Pipeline, PhaseBase)
│   ├── phases/        # Concrete phases (InitialTranslation, Refinement)
│   ├── context.py     # PhaseContext, ChunkContext (shared state)
│   └── executor.py    # PhaseExecutor (chunk processing)
├── validation/        # Multi-threaded validation
│   ├── validation_worker_pool.py  # N workers + SaveWorker
│   ├── validation_worker.py       # CPU-bound validation
│   └── save_worker.py              # I/O-bound persistence
├── checks/            # Validation checks
│   ├── check_tests/  # LineCount, FragmentCount, Punctuation, Sentence
│   ├── pipeline.py   # ValidationPipeline (orchestrator)
│   └── retry_helper.py  # Progressive retry (normal → reasoning)
├── segmentation/      # Content chunking (Segmentator, Chunk)
├── llm/               # LLM client + template rendering
├── translation/       # Engine, Parser, EpubHandler
├── stores/            # Thread-safe caching (Store, MultiStore)
├── htmlpage/          # DOM manipulation (HtmlPage, TagKey)
├── transition/        # Phase transitions (GlossaryValidation)
└── glossary.py        # Terminology management

template/              # Jinja2 prompts
├── common_translate_rules.jinja  # Shared TRANSLATE rules (199 lines)
├── common_correct_rules.jinja    # Shared CORRECT rules (130 lines)
├── translate_base.jinja          # Phase 1 (initial translation)
├── translate_refine.jinja        # Phase 2 (refinement)
└── retry_correct_*.jinja         # Correction templates

tests/                 # Unit tests (107+ tests, ≥80% coverage)
docs/                  # Technical documentation
├── ARCHITECTURE.md   # Complete architecture guide
├── VALIDATION.md     # Validation system deep-dive
├── TEMPLATES.md      # Template architecture
├── CODING_STANDARDS.md  # Type checking, docstrings, testing
└── DEVELOPMENT.md    # Incremental development guide
```

## Configuration

**Environment variables** (`.env`):

```bash
DEEPSEEK_API_KEY=sk-...    # Required
DEEPSEEK_URL=https://api.deepseek.com  # Optional (default)
```

**pyproject.toml key settings**:

- basedpyright: `typeCheckingMode = "strict"` (0 errors tolerated)
- Pytest: `--cov-fail-under=80` (coverage enforcement)
- Ruff: `line-length = 88`
- Python: `>=3.12` (uses modern syntax: `|` unions, `match` statements)

## Known Limitations

1. **Overlap validation**: No automatic check that `overlap_ratio * max_tokens < total_content`. Monitor warnings in logs.
2. **Windows file locks**: Store retries on `PermissionError` (antivirus, file indexing). Rare but handled gracefully.
3. **LLM hallucinations**: ValidationPipeline catches structural errors but not semantic issues (use glossary + Phase 2 refinement).
4. **Template changes**: Modifying shared bases affects ALL templates. Test thoroughly with `test_all_templates.py`.

## Key Files Reference

- **[example_pipeline.py](../example_pipeline.py)**: Complete usage example with all features
- **[CLAUDE.md](../CLAUDE.md)**: Project overview for Claude Code users
- **[CONTRIBUTING.md](../CONTRIBUTING.md)**: Development standards and workflow
- **[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)**: Detailed component breakdown
- **[docs/VALIDATION.md](../docs/VALIDATION.md)**: Validation system architecture

## Troubleshooting

**"API key not found"**: Check `.env` exists and `DEEPSEEK_API_KEY` is set.

**Type errors**: Run `uv run basedpyright src/` and fix ALL errors (strict mode).

**Tests failing**: Check coverage with `uv run pytest --cov-report=html`, open `htmlcov/index.html`.

**Template rendering issues**: Use `uv run python test_template_manual.py <template_name>` to debug.

**Store permission errors (Windows)**: Store auto-retries 3 times with exponential backoff. Check antivirus exclusions for `cache/` directory.

---

**For detailed architecture, see [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md). For coding standards, see [docs/CODING_STANDARDS.md](../docs/CODING_STANDARDS.md).**
