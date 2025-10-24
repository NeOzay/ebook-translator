"""
Moteur de traduction des chunks d'ebooks.

Ce module gère la traduction effective des chunks, incluant :
- Requêtes vers le LLM
- Mapping des traductions par fichier source
- Gestion du cache
- Application des traductions aux pages HTML
"""

from typing import Callable, Optional, TYPE_CHECKING

from tqdm import tqdm

from ..htmlpage import BilingualFormat
from ..logger import get_logger
from .parser import parse_llm_translation_output

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..store import Store
    from ..htmlpage.page import HtmlPage
    from ..htmlpage.tag_key import TagKey

logger = get_logger(__name__)


def build_translation_map(
    chunk: "Chunk", translated_texts: dict[int, str]
) -> dict[str, dict[str, str]]:
    """
    Construit un mapping {fichier_source: {line_index: texte_traduit}}.

    Utilise chunk.fetch() pour parcourir efficacement les fichiers et textes,
    en utilisant l'index du TagKey comme clé.

    Args:
        chunk: Le chunk contenant les textes originaux
        translated_texts: Dictionnaire {index: texte_traduit} du LLM

    Returns:
        Tuple contenant:
        - Dictionnaire {fichier_source: {line_index: texte_traduit}}
        - Dictionnaire {fichier_source: {line_index: texte_original}}
          (pour maintenir le fallback v1)

    Raises:
        KeyError: Si un index est manquant dans translated_texts
    """
    translation_map: dict[str, dict[str, str]] = {}

    for i, (current_file, tag_key, original_text) in enumerate(chunk.fetch()):
        # Obtenir la traduction
        if i not in translated_texts:
            raise KeyError(f"Index {i} manquant dans translated_texts")

        source_path = current_file.epub_html.file_name
        translated_text = translated_texts[i]
        line_index = tag_key.index

        # Initialiser les dictionnaires pour ce fichier si nécessaire
        if source_path not in translation_map:
            translation_map[source_path] = {}

        # Ajouter la traduction avec l'index de ligne comme clé
        translation_map[source_path][line_index] = translated_text

    return translation_map
