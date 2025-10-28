"""
Module de segmentation du contenu EPUB en chunks pour la traduction.

Ce module gère la segmentation intelligente du contenu d'un EPUB en morceaux
de taille limitée (en tokens) pour la traduction par LLM. Il préserve le
contexte entre les chunks via un système de chevauchement (overlap).
"""

from dataclasses import dataclass, field
from typing import Iterator, TYPE_CHECKING

import tiktoken

from .htmlpage import TagKey, get_files, HtmlPage
from .logger import get_logger
from ebooklib import epub

if TYPE_CHECKING:
    from .store import Store
    from .stores import MultiStore

logger = get_logger(__name__)

# Ratio par défaut du chevauchement entre chunks (15%)
DEFAULT_OVERLAP_RATIO = 0.15

# Encodage par défaut pour le comptage de tokens (OpenAI o200k_base)
DEFAULT_ENCODING = "o200k_base"


@dataclass
class Chunk:
    """
    Représente un morceau de contenu EPUB à traduire.

    Un chunk contient :
    - Un body : le contenu principal à traduire (mapping TagKey -> texte)
    - Un head : contexte provenant du chunk précédent (pour continuité)
    - Un tail : contexte pour le chunk suivant (pour continuité)

    Le format d'un chunk lors de la conversion en string :
        <head context>
        <0/>Premier texte à traduire
        <1/>Deuxième texte à traduire
        ...
        <tail context>

    Attributes:
        index: Numéro séquentiel du chunk (commence à 0)
        head: Liste de textes de contexte provenant du chunk précédent
        body: Dictionnaire TagKey -> texte des fragments à traduire
        tail: Liste de textes de contexte pour le chunk suivant
        file_range: Dictionnaire HtmlPage -> nombre de fragments dans cette page
    """

    index: int
    head: dict[TagKey, str] = field(default_factory=dict)
    body: dict[TagKey, str] = field(default_factory=dict)
    tail: dict[TagKey, str] = field(default_factory=dict)

    def fetch_body(self) -> Iterator[tuple[HtmlPage, TagKey, str]]:
        """
        Génère des tuples (page, tag_key, texte) pour chaque fragment du body.

        Cette méthode associe chaque fragment de texte à sa page source
        en utilisant file_range pour déterminer les frontières.

        Yields:
            Tuples (HtmlPage, TagKey, texte original)

        Raises:
            ValueError: Si un fragment ne peut pas être associé à une page

        Example:
            >>> for page, tag, text in chunk.fetch():
            ...     translation = translate(text)
            ...     page.replace_text(tag, translation)
        """

        for tag_key, text in self.body.items():
            yield tag_key.page, tag_key, text

    def fetch_all(self) -> Iterator[tuple[HtmlPage, TagKey, str]]:
        """
        Génère des tuples (page, tag_key, texte) pour chaque fragment du chunk.

        Cela inclut les fragments du head, body et tail, dans cet ordre.

        Yields:
            Tuples (HtmlPage, TagKey, texte original)
        """

        for section in (self.head, self.body, self.tail):
            for tag_key, text in section.items():
                yield tag_key.page, tag_key, text

    def __str__(self) -> str:
        """
        Convertit le chunk en format string pour envoi au LLM.

        Le format est :
            <contexte du head>

            <0/>Premier texte
            <1/>Deuxième texte
            ...

            <contexte du tail>

        Returns:
            Représentation textuelle formatée du chunk
        """
        parts: list[str] = []

        # Ajouter le contexte du head
        if self.head:
            parts.extend(self.head.values())

        # Ajouter le body avec indices
        for index, text in enumerate(self.body.values()):
            parts.append(f"<{index}/>{text}")

        # Ajouter le contexte du tail
        if self.tail:
            parts.extend(self.tail.values())

        return "\n\n".join(parts)

    def mark_lines_to_numbered(self, indices_to_mark: list[int]) -> str:
        """
        Génère une représentation du chunk avec numérotation sélective des lignes.

        Cette méthode renvoie le chunk COMPLET (head + body + tail) mais numérote
        UNIQUEMENT les lignes dont les indices sont spécifiés. Les autres lignes
        sont incluses comme contexte non numéroté.

        Utilisé principalement pour les retries de traduction : le LLM voit tout
        le contenu pour maintenir la cohérence, mais sait précisément quelles
        lignes doivent être (re)traduites.

        Args:
            indices_to_mark: Liste des indices (positions dans body) à numéroter
                avec le format <N/>. Les indices absents ne seront pas numérotés.

        Returns:
            String contenant :
            - head (contexte non numéroté)
            - body avec numérotation sélective : <N/>texte pour indices_to_mark
            - tail (contexte non numéroté)

        Example:
            >>> chunk = Chunk(
            ...     body={
            ...         TagKey(...): "First line",
            ...         TagKey(...): "Second line",
            ...         TagKey(...): "Third line",
            ...     },
            ...     head=["Context before"],
            ...     tail=["Context after"],
            ... )
            >>> print(chunk.mark_lines_to_numbered([0, 2]))
            Context before

            <0/>First line

            Second line

            <2/>Third line

            Context after

        Note:
            Le nom "mark_lines_to_numbered" signifie "marquer (numéroter) les lignes
            spécifiées", pas "renvoyer seulement les lignes numérotées".
        """
        parts: list[str] = []

        # Ajouter le contexte du head
        if self.head:
            parts.extend(self.head.values())

        # Ajouter le body avec indices
        for index, text in enumerate(self.body.values()):
            if index in indices_to_mark:
                parts.append(f"<{index}/>{text}")
            else:
                parts.append(text)

        # Ajouter le contexte du tail
        if self.tail:
            parts.extend(self.tail.values())

        return "\n\n".join(parts)

    def get_translation_for_prompt(self, store: "Store|MultiStore") -> tuple[str, bool]:
        translations, missing = store.get_all_from_chunk(self)

        parts: list[str] = []

        # Ajouter le contexte du head
        if self.head:
            parts.extend(map(lambda tag_key: translations[tag_key], self.head.keys()))

        # Ajouter le body avec indices
        for index, tag_key in enumerate(self.body.keys()):
            parts.append(f"<{index}/>{translations[tag_key]}")

        # Ajouter le contexte du tail
        if self.tail:
            parts.extend(map(lambda tag_key: translations[tag_key], self.tail.keys()))

        return "\n\n".join(parts), missing

    def get_body_size(self) -> int:
        """Retourne le nombre de fragments dans le body du chunk."""
        return len(self.body)

    def get_head_size(self) -> int:
        """Retourne le nombre de fragments dans le head du chunk."""
        return len(self.head)

    def get_tail_size(self) -> int:
        """Retourne le nombre de fragments dans le tail du chunk."""
        return len(self.tail)

    def __hash__(self) -> int:
        """Retourne le hash basé sur l'identité de l'objet."""
        return id(self)

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"Chunk(index={self.index}, "
            f"body_items={len(self.body)}, "
            f"head_items={len(self.head)}, "
            f"tail_items={len(self.tail)}, "
        )


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
