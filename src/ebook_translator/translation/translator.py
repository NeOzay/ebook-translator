"""
Orchestration de la traduction complète d'EPUB.

Ce module fournit la fonction principale pour traduire un fichier EPUB
de bout en bout, incluant :
- Chargement de l'EPUB source
- Segmentation du contenu
- Traduction via LLM
- Reconstruction de l'EPUB traduit
"""

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ebooklib import epub

from ..htmlpage import BilingualFormat
from ..store import Store
from ..segment import Segmentator
from ..worker import TranslationWorker
from .epub_handler import (
    copy_epub_metadata,
    extract_html_items_in_spine_order,
    reconstruct_html_item,
)

if TYPE_CHECKING:
    from ..llm import LLM


class Language(Enum):
    SIMPLIFIED_CHINESE = "Chinois simplifié"
    TRADITIONAL_CHINESE = "Chinois Traditionnel"
    ENGLISH = "Anglais"
    FRENCH = "Francais"
    GERMAN = "Allemand"
    SPANISH = "Espagnole"
    RUSSIAN = "Russe"
    ITALIAN = "Italien"
    PORTUGUESE = "Portugais"
    JAPANESE = "Japonais"
    KOREAN = "Coréen"


class EpubTranslator:
    """
    Orchestrateur principal de traduction d'EPUB.

    Cette classe gère le processus complet de traduction d'un EPUB,
    de la lecture à l'écriture du fichier traduit.
    """

    def __init__(
        self,
        llm: "LLM",
        epub_path: str | Path,
    ):
        """
        Initialise le traducteur d'EPUB.

        Args:
            llm: Instance du LLM à utiliser pour la traduction
        """
        self.llm = llm
        self.epub_path: Path = (
            epub_path if isinstance(epub_path, Path) else Path(epub_path)
        )

    def translate(
        self,
        target_language: Language | str,
        output_epub: str | Path,
        max_concurrent: int = 1,
        bilingual_format: BilingualFormat = BilingualFormat.SEPARATE_TAG,
        user_prompt: str | None = None,
        cache_path: str | Path | None = None,
        max_tokens: int = 1500,
        auto_correct_errors: bool = True,
        max_correction_retries: int = 2,
    ) -> None:
        """
        Traduit un fichier EPUB en utilisant un LLM.

        Cette fonction orchestre le processus complet :
        1. Charge l'EPUB source
        2. Segmente le contenu en chunks
        3. Traduit chaque chunk via le LLM
        4. Reconstruit l'EPUB avec le contenu traduit
        5. Sauvegarde le résultat

        Args:
            epub_path: Chemin vers le fichier EPUB source
            output_epub: Chemin de sortie pour l'EPUB traduit
            target_language: Code de langue cible (ex: "francais")
            max_concurrent: Nombre maximum de traductions parallèles (défaut: 1)
            bilingual_format: Format d'affichage bilingue. Options :
                - BilingualFormat.SEPARATE_TAG : Balises séparées (défaut)
                - BilingualFormat.INLINE : Original | Traduction
                - None : Remplace complètement l'original
            user_prompt: Prompt utilisateur optionnel pour personnaliser la traduction
            cache_path: Chemin vers le dossier de cache (défaut: .{epub_name}_cache)
            max_tokens: Taille maximale des chunks en tokens (défaut: 1500)
            auto_correct_errors: Active la correction automatique des erreurs de segmentation
                via retry LLM (défaut: True)
            max_correction_retries: Nombre de tentatives de correction automatique (défaut: 2)

        Raises:
            FileNotFoundError: Si le fichier EPUB source n'existe pas
            ValueError: Si les paramètres sont invalides
        """
        # Validation des entrées
        if not self.epub_path.exists():
            raise FileNotFoundError(
                f"Le fichier EPUB source n'existe pas : {self.epub_path}"
            )

        target_language = (
            target_language
            if isinstance(target_language, str)
            else target_language.value
        )

        output_epub = (
            output_epub if isinstance(output_epub, Path) else Path(output_epub)
        )

        print(f"📖 Chargement de l'EPUB : {self.epub_path}")
        source_book = epub.read_epub(self.epub_path)

        # Extraire les items HTML dans l'ordre du spine
        print("📑 Extraction des chapitres...")
        html_items, target_book = extract_html_items_in_spine_order(source_book)

        # Copier les métadonnées
        print("📝 Copie des métadonnées...")
        copy_epub_metadata(source_book, target_book, str(target_language))
        # Initialiser le système de stockage
        match cache_path:
            case None:
                cache_path = Path(
                    self.epub_path.parent / f".{self.epub_path.stem}_cache"
                )
            case str():
                cache_path = Path(cache_path)

        store = Store(cache_path)

        # Initialiser le worker de traduction
        print(f"🤖 Initialisation du traducteur (langue cible: {target_language})")

        worker = TranslationWorker(
            self.llm,
            target_language,
            store,
            bilingual_format,
            user_prompt=user_prompt,
            auto_correct_errors=auto_correct_errors,
            max_correction_retries=max_correction_retries,
        )

        # Segmenter et traduire
        print(
            f"🔄 Début de la traduction "
            f"(max {max_concurrent} traduction(s) parallèle(s))..."
        )
        segmentator = Segmentator(html_items, max_tokens)
        worker.run(segmentator, max_threads_count=max_concurrent)

        # Reconstruire les items traduits
        print("🔨 Reconstruction de l'EPUB traduit...")
        for item in html_items:
            reconstruct_html_item(item)
            target_book.add_item(item)

        # Sauvegarder l'EPUB traduit
        print(f"💾 Sauvegarde de l'EPUB traduit...")
        if not output_epub.parent.exists():
            print(
                "📂 Attention : le dossier de sortie n'existe pas, création en cours..."
            )
            output_epub.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(output_epub, target_book)
        print(f"✅ EPUB traduit enregistré sous : {output_epub}")
