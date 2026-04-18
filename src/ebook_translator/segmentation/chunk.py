from collections.abc import Iterator
from dataclasses import dataclass, field

from ebook_translator.config import Config
from ebook_translator.segmentation.helper import turn_resource_to_chunks

from ..htmlpage import HtmlPage, TagKey

type Scope = list[tuple[str, int]]
"""
Liste de tuples (file_name, line_number) où line_number est -1 pour "tout le fichier".
Premier tuple : début, dernier tuple : fin, tuples intermédiaires : fichiers traversés.
"""


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
        scope: Portée du chunk (liste de tuples (file_name, line_number))
        token_count: Nombre de tokens dans le body
        token_encoding: Encodage utilisé pour le comptage de tokens
    """

    index: int
    head: dict[TagKey, str] = field(default_factory=dict[TagKey, str])
    body: dict[TagKey, str] = field(default_factory=dict[TagKey, str])
    tail: dict[TagKey, str] = field(default_factory=dict[TagKey, str])

    token_count: int = field(default=0)
    token_encoding: str = field(default=Config.DEFAULT_ENCODING)

    @property
    def scope(self) -> Scope:
        """
        Portée du chunk (liste de tuples (file_name, line_number)).

        Le résultat est mis en cache après le premier calcul pour éviter
        les recalculs coûteux lors d'accès répétés.

        Returns:
            Liste de tuples (file_name, line_number) représentant la portée du chunk
        """
        if not hasattr(self, "_scope_cache"):
            self._scope_cache = self.calculate_scope()
        return self._scope_cache

    def fetch_body(self) -> Iterator[tuple[HtmlPage, TagKey, str]]:
        """
        Génère des tuples (page, tag_key, texte) pour chaque fragment du body.

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
        return self.prepare_for_prompt()

    def prepare_for_prompt(
        self,
        index_to_mark: list[int] | None = None,
        include_head: bool = True,
        include_tail: bool = True,
    ) -> str:
        parts: list[str] = []

        # Ajouter le contexte du head
        if include_head and self.head:
            parts.extend(self.head.values())

        for index, text in enumerate(self.body.values()):
            if index_to_mark is None or index in index_to_mark:
                parts.append(f"<{index}/>{text}")
            else:
                parts.append(text)

        # Ajouter le contexte du tail
        if include_tail and self.tail:
            parts.extend(self.tail.values())

        return "\n\n".join(parts)

    def prepare_for_prompt_split(
        self, index_to_mark: list[int] | None = None
    ) -> tuple[str, str, str]:
        head_str = "\n\n".join(self.head.values()) if self.head else ""

        body: list[str] = []
        for index, text in enumerate(self.body.values()):
            if not index_to_mark or index in index_to_mark:
                body.append(f"<{index}/>{text}")
            else:
                body.append(text)
        body_str = "\n\n".join(body)

        tail_str = "\n\n".join(self.tail.values()) if self.tail else ""
        return head_str, body_str, tail_str

    def split_chunk(self, max_tokens: int, overlap_ratio: float) -> Iterator[Chunk]:
        yield from turn_resource_to_chunks(
            iter(self.body.items()),
            max_tokens,
            overlap_ratio,
            self.token_encoding,
        )

    def calculate_scope(self) -> Scope:
        """
        Calcule la portée du chunk (position début/fin).

        Format : Liste de tuples (file_name, line_number) où :
        - Premier tuple : début (file_name, line_number)
        - Tuples intermédiaires : fichiers traversés (file_name, -1 pour "tout le fichier")
        - Dernier tuple : fin (file_name, line_number)

        Returns:
            Liste de tuples représentant la portée du chunk

        Example:
            >>> chunk = Chunk(index=0, body={...})
            >>> scope = chunk.calculate_scope()
            >>> # [("chapter01.xhtml", 0), ("chapter01.xhtml", 150)]
        """
        if not self.body:
            return []

        # Obtenir le premier et dernier TagKey
        first_tag_key = next(iter(self.body.keys()))
        last_tag_key = next(reversed(self.body.keys()))

        # Extraire file_name et line_number
        debut_file = first_tag_key.page.epub_html.file_name
        debut_line = int(first_tag_key.index)

        fin_file = last_tag_key.page.epub_html.file_name
        fin_line = int(last_tag_key.index)

        # Construire la liste de tuples
        scope: list[tuple[str, int]] = [(debut_file, debut_line)]

        # Collecter tous les fichiers intermédiaires
        seen_files: set[str] = {debut_file}
        for tag_key in self.body:
            file_name = tag_key.page.epub_html.file_name
            if file_name not in seen_files and file_name != fin_file:
                # Fichier intermédiaire : -1 pour "tout le fichier"
                scope.append((file_name, -1))
                seen_files.add(file_name)

        # Ajouter la fin si différente du début
        if debut_file != fin_file or debut_line != fin_line:
            scope.append((fin_file, fin_line))

        return scope

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
