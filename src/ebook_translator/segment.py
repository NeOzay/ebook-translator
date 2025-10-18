"""
Module de segmentation du contenu EPUB en chunks pour la traduction.

Ce module gère la segmentation intelligente du contenu d'un EPUB en morceaux
de taille limitée (en tokens) pour la traduction par LLM. Il préserve le
contexte entre les chunks via un système de chevauchement (overlap).
"""

from dataclasses import dataclass, field
from typing import Iterator

import tiktoken

from .htmlpage import TagKey, get_files, HtmlPage
from ebooklib import epub

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
    - Un file_range : mapping des pages sources et leur nombre de lignes dans ce chunk

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
    head: list[str] = field(default_factory=list)
    body: dict[TagKey, str] = field(default_factory=dict)
    tail: list[str] = field(default_factory=list)

    def fetch(self) -> Iterator[tuple[HtmlPage, TagKey, str]]:
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
        parts = []

        # Ajouter le contexte du head
        if self.head:
            parts.extend(self.head)

        # Ajouter le body avec indices
        for index, text in enumerate(self.body.values()):
            parts.append(f"<{index}/>{text}")

        # Ajouter le contexte du tail
        if self.tail:
            parts.extend(self.tail)

        return "\n\n".join(parts)

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
            overlap_ratio: Ratio de chevauchement (0.15 = 15%)
            encoding: Nom de l'encodage tiktoken à utiliser
        """
        self.epub_htmls = epub_htmls
        self._encoding = tiktoken.get_encoding(encoding)
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio

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

        Yields:
            Les chunks successifs avec leur contexte (head/tail)

        Example:
            >>> for chunk in segmentator.get_all_segments():
            ...     print(f"Chunk {chunk.index} with {len(chunk.body)} items")
        """
        previous_chunk: Chunk | None = None
        current_chunk = self._create_new_chunk(index=0)
        current_token_count = 0
        overlap_token_budget = self._calculate_overlap_tokens()
        chunk_index = 0

        for page, tag_key, text in get_files(self.epub_htmls):
            token_count = self.count_tokens(text)

            # Gérer le tail du chunk précédent
            if previous_chunk:
                if overlap_token_budget > 0:
                    # Ajouter au tail tant qu'il reste du budget
                    previous_chunk.tail.append(text)
                    overlap_token_budget -= token_count
                else:
                    # Budget épuisé : yield le chunk précédent
                    yield previous_chunk
                    previous_chunk = None

            # Vérifier si on dépasse la limite de tokens
            if current_token_count + token_count > self.max_tokens:
                # Chunk plein : préparer le suivant
                previous_chunk = current_chunk

                chunk_index += 1
                current_chunk = self._create_new_chunk(index=chunk_index)
                self._add_fragment_to_chunk(current_chunk, page, tag_key, text)
                self._fill_head_from_previous(previous_chunk, current_chunk)

                current_token_count = token_count
                overlap_token_budget = self._calculate_overlap_tokens()
            else:
                # Ajouter au chunk actuel
                self._add_fragment_to_chunk(current_chunk, page, tag_key, text)
                current_token_count += token_count

        # Yield les chunks restants
        if previous_chunk:
            yield previous_chunk
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

    def _add_fragment_to_chunk(
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
        self, previous_chunk: Chunk, current_chunk: Chunk
    ) -> None:
        """
        Remplit le head du chunk actuel avec du contexte du chunk précédent.

        Prend les derniers éléments du body du chunk précédent (en ordre inverse)
        jusqu'à atteindre le budget de tokens de chevauchement.

        Args:
            previous_chunk: Le chunk précédent (source du contexte)
            current_chunk: Le chunk actuel (destination du contexte)
        """
        overlap_budget = self._calculate_overlap_tokens()
        body_texts = list(previous_chunk.body.values())

        # Parcourir le body en ordre inverse
        for text in reversed(body_texts):
            token_count = self.count_tokens(text)
            overlap_budget -= token_count

            if overlap_budget > 0:
                # Ajouter au début du head
                current_chunk.head.insert(0, text)
            else:
                # Budget épuisé
                break

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"Segmentator("
            f"pages={len(self.epub_htmls)}, "
            f"max_tokens={self.max_tokens}, "
            f"overlap={self.overlap_ratio*100:.0f}%)"
        )
