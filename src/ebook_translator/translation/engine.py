"""
Moteur de traduction des chunks d'ebooks.

Ce module gère la traduction effective des chunks, incluant :
- Requêtes vers le LLM
- Mapping des traductions par fichier source
- Gestion du cache
- Application des traductions aux pages HTML
"""

from typing import Optional, TYPE_CHECKING

from tqdm import tqdm

from ..htmlpage import BilingualFormat
from .parser import parse_llm_translation_output

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..store import Store


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


def flatten_translation_map(
    translation_map: dict[str, dict[int, str]],
) -> dict[int, str]:
    """
    Aplatit un mapping hiérarchique en un dictionnaire simple.

    Args:
        translation_map: Dictionnaire {fichier_source: {line_index: traduit}}

    Returns:
        Dictionnaire plat {line_index: texte_traduit}
    """
    result: dict[int, str] = {}
    for file_translations in translation_map.values():
        result.update(file_translations)
    return result


class TranslationEngine:
    """
    Moteur principal de traduction des chunks.

    Cette classe orchestre la traduction des chunks en utilisant le LLM,
    le cache, et applique les traductions aux pages HTML.
    """

    def __init__(self, llm: "LLM", store: "Store", target_language: str):
        """
        Initialise le moteur de traduction.

        Args:
            llm: Instance du LLM pour la traduction
            store: Instance du Store pour la gestion du cache
            target_language: Code de la langue cible (ex: "fr", "en")
        """
        self.llm = llm
        self.store = store
        self.target_language = target_language

    def _request_translation(
        self,
        chunk: "Chunk",
        user_prompt: Optional[str] = None,
    ) -> tuple[list[str], bool]:
        """
        Effectue une requête de traduction via LLM et sauvegarde les résultats.

        Cette fonction traduit un chunk complet en utilisant le LLM, parse les résultats,
        les mappe aux fichiers sources correspondants, et sauvegarde les traductions.

        Args:
            chunk: Le chunk contenant les textes à traduire
            user_prompt: Prompt utilisateur optionnel pour personnaliser la traduction

        Returns:
            Dictionnaire {line_index: texte_traduit} pour tous les textes du chunk

        Raises:
            ValueError: Si un fichier source est introuvable ou format LLM invalide
            KeyError: Si un index est manquant dans la sortie du LLM
        """
        # Générer le prompt et obtenir la traduction du LLM
        prompt = self.llm.render_prompt(
            "translate.jinja",
            target_language=self.target_language,
            user_prompt=user_prompt,
        )
        llm_output = self.llm.query(prompt, str(chunk))
        translated_texts = parse_llm_translation_output(llm_output)

        # Mapper les traductions par fichier source
        translation_map = build_translation_map(chunk, translated_texts)

        # Sauvegarder toutes les traductions
        self._save_translations(translation_map)

        # Retourner un dictionnaire plat pour utilisation directe
        return self.store.get_from_chunk(chunk)

    def translate_chunk(
        self,
        chunk: "Chunk",
        user_prompt: Optional[str] = None,
        bilingual_format: BilingualFormat = BilingualFormat.DISABLE,
        bar: Optional[tqdm] = None,
    ) -> None:
        """
        Traduit un chunk en utilisant le cache ou en faisant un appel LLM.

        Cette fonction vérifie d'abord si les traductions existent dans le cache.
        Si des traductions sont manquantes, elle effectue une requête au LLM pour
        traduire l'ensemble du chunk, puis applique les traductions aux pages HTML.

        Args:
            chunk: Le chunk contenant les textes à traduire
            user_prompt: Prompt utilisateur optionnel pour personnaliser la traduction
            bilingual_format: Format d'affichage bilingue. Si None, remplace
                complètement le texte original. Par défaut : SEPARATE_TAG
        """
        # Vérifier le cache
        cached_translations, has_missing = self.store.get_from_chunk(chunk)

        # Si des traductions manquent, faire un appel LLM
        if has_missing:
            cached_translations, has_missing = self._request_translation(
                chunk, user_prompt
            )
            if has_missing:
                raise ValueError(
                    "Des traductions sont toujours manquantes après l'appel LLM."
                )

        # Appliquer les traductions aux pages HTML
        for (page, tag_key, _), translated_text in zip(
            chunk.fetch(), cached_translations
        ):
            # Utiliser l'index du TagKey pour récupérer la traduction
            # line_index = tag_key.index
            # translated_text = cached_translations.get(index)
            if translated_text:
                page.replace_text(
                    tag_key,
                    translated_text,
                    bilingual_format=bilingual_format,
                )
        if bar:
            bar.update(1)

    def _save_translations(
        self,
        translation_map: dict[str, dict[str, str]],
    ) -> None:
        """
        Sauvegarde toutes les traductions dans le store.

        Args:
            translation_map: Dictionnaire {fichier_source: {line_index: traduit}}
            text_mapping: Dictionnaire {fichier_source: {line_index: texte_original}}
        """
        for source_file, translations in translation_map.items():
            self.store.save_all(source_file, translations)
