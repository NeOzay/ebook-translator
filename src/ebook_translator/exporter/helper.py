import re
import unicodedata
from pathlib import Path

from ebook_translator.logger import logging

logger = logging.getLogger(__name__)


def save_markdown(markdown_content: str, output_path: Path | str) -> None:
    """
    Sauvegarde le contenu Markdown dans un fichier.

    Args:
        markdown_content: Contenu Markdown à sauvegarder
        output_path: Chemin du fichier de sortie

    Example:
        >>> md = export_to_markdown(raw_json)
        >>> save_markdown(md, "cache/analysis/Chapter_1.md")
    """
    output_path = Path(output_path) if isinstance(output_path, str) else output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write(markdown_content)

    logger.info(f"Exporté Markdown: {output_path}")


# ------------------------------
# Helpers internes
# ------------------------------


def normalize_text(text: str) -> str:
    """
    Nettoie un texte pour rendu Markdown.

    - Supprime espaces en tête/queue
    - Remplace séquences d'espaces par un seul espace

    Args:
        text: Texte d'entrée

    Returns:
        Texte normalisé
    """
    s = text.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def slugify(label: str) -> str:
    """
    Convertit un label en slug Markdown (ancres H2 compatibles GitHub).

    Args:
        label: Libellé humain

    Returns:
        Slug en minuscules, sans accents, séparé par des tirets
    """
    s = unicodedata.normalize("NFKD", label)
    # s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s
