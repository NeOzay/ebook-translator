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
from ebook_translator import Language
from ebook_translator import LLM, BilingualFormat, EpubTranslator

# Configure the LLM
llm = LLM(
    model_name="deepseek-chat",
    log_dir="logs",
    url="https://api.deepseek.com",
    max_tokens=1300,
)

# Translate the EPUB
translator = EpubTranslator(llm, epub_path="my_book.epub")
translator.translate(
    target_language=Language.FRENCH,
    output_epub="my_book_translated.epub",
    max_concurrent=5,
    bilingual_format=BilingualFormat.SEPARATE_TAG,
)
```

Then run:
```bash
python translate.py
```

### Bilingual Format Options

- `BilingualFormat.INLINE`: Original and translation in the same paragraph
- `BilingualFormat.SEPARATE_TAG`: Original and translation in separate paragraphs
- `BilingualFormat.DISABLE`: Completely replaces the original

### Complete Example

See [start.py](start.py) for a complete configuration example with all available parameters.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | ✅ Yes | - | DeepSeek API key for authentication |

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

1. **EPUB Loading** - Reads EPUB, extracts metadata and spine order
2. **Segmentation** - Chunks content into token-limited segments with overlap
3. **Translation** - Parallelizes LLM translation calls
4. **Reconstruction** - Replaces original text with translations in DOM
5. **EPUB Generation** - Writes new EPUB with translated content

### Key Components

- **Segmentator** ([segment.py](src/ebook_translator/segment.py)) - Chunks content with token limits and overlap
- **HtmlPage** ([htmlpage.py](src/ebook_translator/htmlpage.py)) - Parses and reconstructs HTML with translations
- **AsyncLLMTranslator** ([llm.py](src/ebook_translator/llm.py)) - Async wrapper for LLM API calls
- **TranslationWorkerFuture** ([worker.py](src/ebook_translator/worker.py)) - Parallelizes translation tasks

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
