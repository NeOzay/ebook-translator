"""
Module de segmentation du contenu EPUB en chunks pour la traduction.

Ce module gère la segmentation intelligente du contenu d'un EPUB en morceaux
de taille limitée (en tokens) pour la traduction par LLM. Il préserve le
contexte entre les chunks via un système de chevauchement (overlap).
"""

from typing import Iterator

import tiktoken

from .chunk import Chunk

from ..htmlpage import TagKey, get_files, HtmlPage
from ..logger import get_logger
from ebooklib import epub

from ..constants import DEFAULT_OVERLAP_RATIO, DEFAULT_ENCODING

logger = get_logger(__name__)


class Segmentator:
    """
    Segmente le contenu d'un EPUB en chunks de taille limitée en tokens.

    Cette classe divise intelligemment le contenu de plusieurs fichiers HTML
    en morceaux (chunks) qui respectent une limite de tokens, avec un système
    de chevauchement (overlap) pour préserver le contexte entre les chunks.

    Le chevauchement fonctionne ainsi :
    - Le début du chunk N+1 contient du contexte du chunk N (head)
    - La fin du chunk N contient du contexte pour le chunk N+1 (tail)

    Attributes:
        epub_htmls: Liste des pages HTML de l'EPUB à segmenter
        max_tokens: Nombre maximum de tokens par chunk
        overlap_ratio: Ratio de chevauchement entre chunks (défaut: 0.15 = 15%)
        _encoding: Encodeur tiktoken pour compter les tokens

    Example:
        >>> segmentator = Segmentator(epub_htmls, max_tokens=2000)
        >>> for chunk in segmentator.get_all_segments():
        ...     translation = llm.translate(str(chunk))
        ...     for page, tag, text in chunk.fetch():
        ...         page.replace_text(tag, translation)
    """

    def __init__(
        self,
        epub_htmls: list[epub.EpubHtml],
        max_tokens: int,
        overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
        encoding: str = DEFAULT_ENCODING,
    ) -> None:
        """
        Initialise le segmentateur.

        Args:
            epub_htmls: Liste des pages HTML à segmenter
            max_tokens: Nombre maximum de tokens par chunk
            overlap_ratio: Ratio de chevauchement
                - Si < 1.0 : pourcentage de max_tokens (ex: 0.15 = 15%)
                - Si >= 1.0 : multiple de max_tokens (ex: 2.0 = 200% = 2× max_tokens)
            encoding: Nom de l'encodage tiktoken à utiliser

        Note:
            Un overlap_ratio >= 1.0 créera un contexte étendu qui peut englober
            plusieurs chunks précédents. Cela augmente la cohérence mais aussi
            la consommation de tokens et le coût des requêtes LLM.
        """
        self.epub_htmls = epub_htmls
        self._encoding = tiktoken.get_encoding(encoding)
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio

        # Warning si overlap_ratio >= 1.0 (contexte très étendu)
        if overlap_ratio >= 1.0:
            overlap_tokens = int(max_tokens * overlap_ratio)
            logger.warning(
                f"⚠️ Overlap ratio très élevé : {overlap_ratio:.1f} "
                f"({overlap_tokens} tokens d'overlap pour {max_tokens} tokens de body). "
                f"Cela augmentera significativement la consommation de tokens et le coût des traductions."
            )

    def count_tokens(self, text: str) -> int:
        """
        Compte le nombre de tokens dans un texte.

        Args:
            text: Le texte à analyser

        Returns:
            Nombre de tokens selon l'encodage configuré
        """
        return len(self._encoding.encode(text))

    def get_all_segments(self) -> Iterator[Chunk]:
        """
        Génère tous les chunks en segmentant le contenu de l'EPUB.

        Cette méthode parcourt tous les fragments de texte des pages HTML
        et les regroupe en chunks respectant la limite de tokens. Elle gère
        automatiquement le chevauchement entre chunks pour préserver le contexte.

        Le système de chevauchement (overlap) fonctionne ainsi :
        - overlap_ratio < 1.0 : Pourcentage de max_tokens (ex: 0.15 = 15%)
        - overlap_ratio >= 1.0 : Multiple de max_tokens (ex: 1.5 = 150% du body)

        Avec overlap_ratio > 1.0, le contexte peut s'étendre sur plusieurs chunks
        précédents. Par exemple, avec overlap_ratio=2.0 et max_tokens=2000 :
        - Chunk 0 : body=2000 tokens, head=[], tail=4000 tokens
        - Chunk 1 : body=2000 tokens, head=4000 tokens (depuis chunk 0), tail=4000 tokens
        - Le head de chunk 1 peut inclure tout le body de chunk 0 + du contexte antérieur

        Yields:
            Les chunks successifs avec leur contexte (head/tail)

        Example:
            >>> # Overlap standard (15%)
            >>> segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=0.15)
            >>> for chunk in segmentator.get_all_segments():
            ...     print(f"Chunk {chunk.index} with {len(chunk.body)} items")

            >>> # Overlap étendu (200% du body)
            >>> segmentator = Segmentator(epub_htmls, max_tokens=2000, overlap_ratio=2.0)
            >>> for chunk in segmentator.get_all_segments():
            ...     # Le head contient ~4000 tokens de contexte des chunks précédents
            ...     print(f"Chunk {chunk.index}: head={len(chunk.head)}, body={len(chunk.body)}, tail={len(chunk.tail)}")
        """
        chunk_queue: dict[Chunk, int] = {}
        # previous_chunk: Chunk | None = None
        current_chunk = self._create_new_chunk(index=0)
        current_token_count = 0
        # overlap_token_budget = self._calculate_overlap_tokens()
        chunk_index = 0

        for page, tag_key, text in get_files(self.epub_htmls):
            token_count = self.count_tokens(text)

            # Vérifier si on dépasse la limite de tokens
            if current_token_count + token_count > self.max_tokens:
                # Chunk plein : préparer le suivant
                chunk_queue[current_chunk] = self._calculate_overlap_tokens()

                chunk_index += 1
                current_chunk = self._create_new_chunk(index=chunk_index)
                self._add_fragment_to_body(current_chunk, page, tag_key, text)
                self._fill_head_from_previous(chunk_queue, current_chunk)

                current_token_count = token_count
            else:
                # Ajouter au chunk actuel
                self._add_fragment_to_body(current_chunk, page, tag_key, text)
                current_token_count += token_count

                # Gérer le tail des chunks précédents
            if chunk_queue:
                for chunk in list(chunk_queue.keys()):
                    # Ajouter au tail tant qu'il reste du budget
                    if chunk_queue[chunk] > 0:
                        chunk.tail[tag_key] = text
                        chunk_queue[chunk] -= token_count

                    # Si le budget est épuisé ou négatif, yield le chunk
                    if chunk_queue[chunk] <= 0:
                        chunk_queue.pop(chunk)
                        yield chunk

        # Yield les chunks restants dans la queue
        for previous_chunk in chunk_queue.keys():
            yield previous_chunk

        # Yield le chunk actuel seulement s'il n'a pas déjà été yielded via la queue
        if current_chunk not in chunk_queue:
            yield current_chunk

    def _create_new_chunk(self, index: int) -> Chunk:
        """
        Crée un nouveau chunk vide.

        Args:
            index: L'index du chunk

        Returns:
            Un nouveau Chunk initialisé
        """
        return Chunk(index=index)

    def _calculate_overlap_tokens(self) -> int:
        """
        Calcule le nombre de tokens disponibles pour le chevauchement.

        Returns:
            Nombre de tokens alloués au chevauchement
        """
        return int(self.max_tokens * self.overlap_ratio)

    def _add_fragment_to_body(
        self, chunk: Chunk, page: HtmlPage, tag_key: TagKey, text: str
    ) -> None:
        """
        Ajoute un fragment de texte au body d'un chunk.

        Met également à jour le file_range pour suivre le nombre de
        fragments par page.

        Args:
            chunk: Le chunk à modifier
            page: La page source du fragment
            tag_key: La clé identifiant le fragment
            text: Le texte du fragment
        """
        chunk.body[tag_key] = text

    def _fill_head_from_previous(
        self, previous_chunks: dict[Chunk, int], current_chunk: Chunk
    ) -> None:
        """
        Remplit le head du chunk actuel avec du contexte des chunks précédents.

        Parcourt les chunks précédents en ordre inverse (du plus récent au plus ancien)
        et prend leurs éléments de body (également en ordre inverse) jusqu'à épuiser
        le budget de tokens de chevauchement.

        Avec overlap_ratio >= 1.0, cette méthode peut remonter sur plusieurs chunks
        précédents pour construire un contexte étendu.

        Args:
            previous_chunks: Dictionnaire des chunks précédents (Chunk -> budget restant)
            current_chunk: Le chunk actuel (destination du contexte)

        Example:
            Avec overlap_ratio=2.0 et max_tokens=2000 (budget=4000 tokens) :
            - Chunk 0 : body=["A", "B", "C"] (2000 tokens total)
            - Chunk 1 : body=["D", "E"] (1500 tokens)
            - Chunk 2 : head sera rempli avec ["E", "D", "C", "B"] (~3500 tokens)
                        Le budget de 4000 tokens permet d'inclure tout chunk 1 + une partie de chunk 0
        """
        overlap_budget = self._calculate_overlap_tokens()

        collect_text: dict[TagKey, str] = {}
        for chunk in reversed(previous_chunks.keys()):
            # Parcourir le body en ordre inverse
            for tag_key in reversed(chunk.body):
                text = chunk.body[tag_key]
                token_count = self.count_tokens(text)
                overlap_budget -= token_count

                if overlap_budget > 0:
                    # Ajouter au début du head
                    collect_text[tag_key] = text
                else:
                    # Budget épuisé
                    break
            if overlap_budget <= 0:
                break
        for tag_key in reversed(collect_text):
            current_chunk.head[tag_key] = collect_text[tag_key]

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        overlap_tokens = self._calculate_overlap_tokens()

        # Affichage différent selon si overlap < ou >= max_tokens
        if self.overlap_ratio < 1.0:
            overlap_str = f"{self.overlap_ratio*100:.0f}% ({overlap_tokens} tokens)"
        else:
            overlap_str = (
                f"{self.overlap_ratio:.1f}× max_tokens ({overlap_tokens} tokens)"
            )

        return (
            f"Segmentator("
            f"pages={len(self.epub_htmls)}, "
            f"max_tokens={self.max_tokens}, "
            f"overlap={overlap_str})"
        )
