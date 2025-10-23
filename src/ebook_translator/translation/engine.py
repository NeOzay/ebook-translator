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

from ..config import TemplateNames

from ..htmlpage import BilingualFormat
from ..logger import get_logger
from .parser import (
    parse_llm_translation_output,
    validate_line_count,
    validate_retry_indices,
)

if TYPE_CHECKING:
    from ..llm import LLM
    from ..segment import Chunk
    from ..store import Store
    from ..correction.retry_engine import RetryEngine
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

    def __init__(
        self,
        llm: "LLM",
        store: "Store",
        target_language: str,
        retry_engine: Optional["RetryEngine"] = None,
    ):
        """
        Initialise le moteur de traduction.

        Args:
            llm: Instance du LLM pour la traduction
            store: Instance du Store pour la gestion du cache
            target_language: Code de la langue cible (ex: "fr", "en")
            retry_engine: Moteur de retry automatique (optionnel)
        """
        self.llm = llm
        self.store = store
        self.target_language = target_language
        self.retry_engine = retry_engine
        self.corrected_count = 0  # Statistique : nombre de corrections réussies

    def _request_translation(
        self,
        chunk: "Chunk",
        user_prompt: Optional[str] = None,
        max_line_retries: int = 2,
    ) -> tuple[list[str], bool]:
        """
        Effectue une requête de traduction via LLM et sauvegarde les résultats.

        Cette fonction traduit un chunk complet en utilisant le LLM, parse les résultats,
        valide le nombre de lignes, et effectue des retries si nécessaire.

        Args:
            chunk: Le chunk contenant les textes à traduire
            user_prompt: Prompt utilisateur optionnel pour personnaliser la traduction
            max_line_retries: Nombre max de retries si lignes manquantes (défaut: 2)

        Returns:
            Dictionnaire {line_index: texte_traduit} pour tous les textes du chunk

        Raises:
            ValueError: Si un fichier source est introuvable ou format LLM invalide
            KeyError: Si un index est manquant dans la sortie du LLM
        """
        source_content = str(chunk)

        # Première tentative avec le prompt standard
        prompt = self.llm.render_prompt(
            TemplateNames.First_Pass_Template,
            target_language=self.target_language,
            user_prompt=user_prompt,
        )
        # Contexte pour le log : chunk_<index>
        context = f"chunk_{chunk.index:03d}"
        llm_output = self.llm.query(prompt, source_content, context=context)
        translated_texts = parse_llm_translation_output(llm_output)

        # Valider le nombre de lignes
        is_valid, error_message = validate_line_count(
            translations=translated_texts,
            source_content=source_content,
        )

        # Si validation échoue, tenter des retries
        retry_attempt = 0
        while not is_valid and retry_attempt < max_line_retries:
            retry_attempt += 1
            logger.warning(
                f"⚠️ Lignes manquantes détectées (tentative {retry_attempt}/{max_line_retries})"
            )
            logger.debug(f"Détails: {error_message}")

            # Calculer les indices manquants pour le template
            from .parser import count_expected_lines

            expected_count = count_expected_lines(source_content)
            expected_indices = set(range(expected_count))
            actual_indices = set(translated_texts.keys())
            missing_indices = sorted(expected_indices - actual_indices)

            # Retry avec prompt strict
            retry_prompt = self.llm.render_prompt(
                TemplateNames.Missing_Lines_Template,
                target_language=self.target_language,
                error_message=error_message,
                expected_count=expected_count,
                missing_indices=missing_indices,
                source_content=chunk.mark_lines_to_numbered(missing_indices),
            )

            logger.info(
                f"🔄 Retry avec prompt strict ({len(missing_indices)} lignes manquantes)"
            )
            # Contexte pour le retry : retry_chunk_<index>_attempt_<n>
            retry_context = f"retry_chunk_{chunk.index:03d}_attempt_{retry_attempt}"
            llm_output = self.llm.query(retry_prompt, "", context=retry_context)
            missing_translated_texts = parse_llm_translation_output(llm_output)

            # Valider que le retry a fourni exactement les indices demandés
            is_retry_valid, retry_error = validate_retry_indices(
                missing_translated_texts, missing_indices
            )

            if not is_retry_valid:
                logger.warning(
                    f"⚠️ Le retry n'a pas fourni les bons indices:\n{retry_error}"
                )
                logger.debug(
                    f"  • Indices demandés: {missing_indices[:20]}\n"
                    f"  • Indices reçus: {sorted(missing_translated_texts.keys())[:20]}"
                )
                # Ne pas faire .update() si les indices sont incorrects
                # → La validation globale détectera le problème et retentera
            else:
                # Indices valides → merger avec les traductions existantes
                translated_texts.update(missing_translated_texts)
                logger.debug(
                    f"✅ Retry a fourni les {len(missing_translated_texts)} indices corrects"
                )

            # Re-valider le compte total
            is_valid, error_message = validate_line_count(
                translations=translated_texts,
                source_content=source_content,
            )

            if is_valid:
                logger.info(f"✅ Retry réussi après {retry_attempt} tentative(s)")
                break

        # Si toujours invalide après tous les retries, lever une erreur
        if not is_valid:
            logger.error(
                f"❌ Échec de validation après {max_line_retries} tentatives de retry"
            )
            raise ValueError(
                f"Impossible d'obtenir une traduction complète après {max_line_retries} tentatives.\n"
                f"{error_message}"
            )

        # Mapper les traductions par fichier source
        translation_map = build_translation_map(chunk, translated_texts)

        # Sauvegarder toutes les traductions
        self._save_translations(translation_map)

        # Retourner un dictionnaire plat pour utilisation directe
        return self.store.get_from_chunk(chunk)

    def _apply_translation_with_retry(
        self,
        page: "HtmlPage",
        tag_key: "TagKey",
        original_text: str,
        translated_text: str,
        bilingual_format: BilingualFormat,
    ) -> bool:
        """
        Applique une traduction avec validation précoce et retry automatique.

        Cette méthode vérifie le nombre de segments AVANT d'appeler replace_text()
        pour éviter de modifier le DOM si une correction est nécessaire.

        Args:
            page: Page HTML à modifier
            tag_key: Clé identifiant le texte à remplacer
            original_text: Texte original complet
            translated_text: Texte traduit
            bilingual_format: Format d'affichage bilingue

        Returns:
            True si la traduction a été appliquée (avec ou sans retry)

        Raises:
            KeyError: Si tag_key n'existe pas
            FragmentMismatchError: Si validation échoue et retry désactivé/échoué
        """
        # 1. Récupérer fragments SANS les supprimer (utiliser .get au lieu de .pop)
        text_fragments = page.to_translate.get(tag_key)
        if not text_fragments:
            raise KeyError(
                f"No text fragments found for {tag_key}. "
                f"Either it was already replaced or never extracted."
            )

        # 2. VALIDATION PRÉCOCE pour fragments multiples
        if isinstance(text_fragments, list) and self.retry_engine:
            from ..htmlpage.constants import FRAGMENT_SEPARATOR

            segments = translated_text.split(FRAGMENT_SEPARATOR)
            expected_count = len(text_fragments)
            actual_count = len(segments)

            # Si mismatch détecté → retry AVANT d'appeler replace_text()
            if expected_count != actual_count:
                logger.debug(
                    f"Mismatch détecté en amont : attendu {expected_count}, reçu {actual_count}"
                )

                # Préparer données pour retry
                original_fragments = [
                    frag.strip() for frag in text_fragments if frag.strip()
                ]
                translated_segments = [seg.strip() for seg in segments]

                # Tentative de correction
                result = self.retry_engine.attempt_correction(
                    original_fragments=original_fragments,
                    incorrect_segments=translated_segments,
                    target_language=self.target_language,
                    original_text=original_text,
                )

                if result.success and result.corrected_text:
                    # Utiliser le texte corrigé à la place
                    translated_text = result.corrected_text
                    self.corrected_count += 1
                    self.store.save(
                        page.epub_html.file_name, tag_key.index, translated_text
                    )
                    logger.debug(
                        f"✅ Correction réussie après {result.attempts} tentative(s)"
                    )
                else:
                    # Échec de correction → lever erreur
                    from ..htmlpage.exceptions import FragmentMismatchError

                    logger.error(
                        f"❌ Échec de correction après {result.attempts} tentatives"
                    )
                    raise FragmentMismatchError(
                        original_fragments=original_fragments,
                        translated_segments=translated_segments,
                        original_text=original_text,
                        expected_count=expected_count,
                        actual_count=actual_count,
                    )

        # 3. Appliquer UNE SEULE FOIS (avec texte corrigé ou original)
        try:
            page.replace_text(
                tag_key,
                translated_text,
                bilingual_format=bilingual_format,
                original_text=original_text,
            )
            return True

        except Exception as e:
            # Logger les erreurs non-FragmentMismatchError
            logger.error(
                f"❌ Erreur lors de l'application de la traduction:\n{e}\n"
                f"\n📍 Contexte:\n"
                f"  • Page: {page.epub_html.file_name}\n"
                f"  • Tag: {tag_key}\n"
                f"  • Original: {original_text[:100]}...\n"
                f"  • Translation: {translated_text[:100]}..."
            )
            raise

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
        for (page, tag_key, original_text), translated_text in zip(
            chunk.fetch(), cached_translations
        ):
            if translated_text:
                # Utiliser _apply_translation_with_retry qui gère le retry automatique
                self._apply_translation_with_retry(
                    page=page,
                    tag_key=tag_key,
                    original_text=original_text,
                    translated_text=translated_text,
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
