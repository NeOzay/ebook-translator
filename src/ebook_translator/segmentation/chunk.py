from collections.abc import Iterator
from dataclasses import dataclass, field

from ebook_translator.config import Config
from ebook_translator.segmentation.helper import turn_resource_to_chunks

from ..htmlpage import HtmlPage, TagKey


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
        chapter_name: Nom optionnel du chapitre (pour segmentation par chapitre)
        file_range: Dictionnaire HtmlPage -> nombre de fragments dans cette page
    """

    index: int
    head: dict[TagKey, str] = field(default_factory=dict[TagKey, str])
    body: dict[TagKey, str] = field(default_factory=dict[TagKey, str])
    tail: dict[TagKey, str] = field(default_factory=dict[TagKey, str])
    token_count: int = 0
    token_encoding: str = field(default=Config.DEFAULT_ENCODING)

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

    def split_chunk(self, max_tokens: int, overlap_ratio: float) -> Iterator["Chunk"]:
        yield from turn_resource_to_chunks(
            iter(self.body.items()),
            max_tokens,
            overlap_ratio,
            self.token_encoding,
        )

    def calculate_chunk_hash(self) -> str:
        """Calcule un hash unique basé sur le contenu du chunk."""
        import hashlib

        hasher = hashlib.md5()

        # Inclure le body
        for text in self.body.values():
            hasher.update(text.encode("utf-8"))

        return hasher.hexdigest()

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
