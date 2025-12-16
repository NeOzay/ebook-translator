from typing import TYPE_CHECKING

from .chunk import Chunk

if TYPE_CHECKING:
    from ebook_translator.stores import Store


class TranslatedChunk(Chunk):
    """
    Représente un segment de texte traduit.
    Contient le texte original, le texte traduit, et des métadonnées associées.
    """

    def __init__(self, chunk: Chunk, store: Store):
        super().__init__(chunk.index)
        self.original_chunk = chunk
        translations, self.has_missing = store.get_all_from_chunk(chunk)

        # Ajouter le contexte du head
        if chunk.head:
            self.head.update(
                (tag_key, translations[tag_key] or "") for tag_key in chunk.head
            )

        # Ajouter le body avec indices
        if chunk.body:
            self.body.update(
                (tag_key, translations[tag_key] or "") for tag_key in chunk.body
            )

        # Ajouter le contexte du tail
        if chunk.tail:
            self.tail.update(
                (tag_key, translations[tag_key] or "") for tag_key in chunk.tail
            )
