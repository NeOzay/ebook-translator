"""
Block splitter pour l'analyse littéraire incrémentale.

Ce module découpe les chapitres longs en blocs de ~4000 tokens pour permettre
une analyse progressive sans dépasser les limites du LLM.

Architecture:
    Chunk (2000 tokens)  →  AnalysisBlock (~4000 tokens)
    ↓                        ↓
    Pour traduction          Pour analyse littéraire
    (head/body/tail)         (texte brut concaténé)

Rationale:
- Traduction (Phase 1): Découpage fin (2000 tokens) pour cohérence locale
- Analyse (Phase 0): Découpage large (4000 tokens) pour compréhension narrative globale
"""

from dataclasses import dataclass
import tiktoken
from typing import Iterator

from ..segmentation import Chunk


@dataclass
class AnalysisBlock:
    """
    Bloc de texte pour l'analyse littéraire (~4000 tokens).

    Un AnalysisBlock contient le texte brut d'un ou plusieurs Chunks,
    concaténés pour former un bloc cohérent d'analyse.

    Attributes:
        chapter_name: Nom du chapitre analysé
        block_number: Numéro séquentiel du bloc (1, 2, 3, ...)
        total_blocks: Nombre total de blocs dans ce chapitre
        text: Contenu textuel du bloc (~4000 tokens)
        token_count: Nombre exact de tokens dans ce bloc

    Example:
        >>> block = AnalysisBlock(
        ...     chapter_name="Chapter 1",
        ...     block_number=1,
        ...     total_blocks=3,
        ...     text="It was a dark and stormy night...",
        ...     token_count=3847
        ... )
        >>> print(f"{block.chapter_name} - Block {block.block_number}/{block.total_blocks}")
        Chapter 1 - Block 1/3
    """

    chapter_name: str
    block_number: int
    total_blocks: int
    text: str
    token_count: int

    @property
    def is_first_block(self) -> bool:
        """Retourne True si c'est le premier bloc du chapitre."""
        return self.block_number == 1

    @property
    def is_last_block(self) -> bool:
        """Retourne True si c'est le dernier bloc du chapitre."""
        return self.block_number == self.total_blocks

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"AnalysisBlock(chapter_name={self.chapter_name!r}, "
            f"block={self.block_number}/{self.total_blocks}, "
            f"tokens={self.token_count})"
        )


class BlockSplitter:
    """
    Découpe les chapitres en blocs de ~4000 tokens pour analyse incrémentale.

    Ce splitter prend des Chunks (segmentation pour traduction) et les regroupe
    en AnalysisBlocks plus larges (pour analyse littéraire).

    Rationale:
    - Les Chunks (2000 tokens) sont optimaux pour traduction (cohérence locale)
    - Les AnalysisBlocks (4000 tokens) sont optimaux pour analyse (compréhension narrative)

    Args:
        target_tokens: Nombre de tokens cible par bloc (défaut: 4000)
        encoding_name: Nom de l'encodage tiktoken (défaut: "cl100k_base" pour GPT-4/DeepSeek)

    Example:
        >>> splitter = BlockSplitter(target_tokens=4000)
        >>> for block in splitter.split_chapter("Chapter 1", chunks):
        ...     print(f"{block.chapter_name} - {block.token_count} tokens")
        Chapter 1 - 3847 tokens
        Chapter 1 - 4129 tokens
        Chapter 1 - 2106 tokens
    """

    def __init__(
        self,
        target_tokens: int = 4000,
        encoding_name: str = "cl100k_base",
    ):
        """
        Initialise le splitter avec la configuration token.

        Args:
            target_tokens: Nombre de tokens cible par bloc (défaut: 4000)
            encoding_name: Nom de l'encodage tiktoken (défaut: "cl100k_base")

        Raises:
            ValueError: Si target_tokens <= 0
        """
        if target_tokens <= 0:
            raise ValueError(f"target_tokens doit être > 0, reçu: {target_tokens}")

        self.target_tokens = target_tokens
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count_tokens(self, text: str) -> int:
        """
        Compte le nombre de tokens dans un texte.

        Args:
            text: Texte à analyser

        Returns:
            Nombre de tokens
        """
        return len(self.encoding.encode(text))

    def split_chapter(
        self,
        chapter_name: str,
        chunks: list[Chunk],
    ) -> Iterator[AnalysisBlock]:
        """
        Découpe un chapitre en blocs d'analyse de ~target_tokens.

        Cette méthode regroupe les Chunks en AnalysisBlocks plus larges
        en respectant les contraintes de tokens.

        Stratégie:
        1. Extraire le texte de tous les chunks (head + body + tail)
        2. Concaténer les chunks jusqu'à atteindre ~target_tokens
        3. Générer un AnalysisBlock quand la limite est atteinte
        4. Continuer jusqu'à épuisement des chunks

        Args:
            chapter_name: Nom du chapitre (ex: "Chapter 1", "Prologue")
            chunks: Liste des Chunks constituant ce chapitre

        Yields:
            AnalysisBlock de ~target_tokens chacun

        Raises:
            ValueError: Si chunks est vide ou si un chunk est trop grand

        Example:
            >>> chunks = [chunk1, chunk2, chunk3]  # 3 chunks de 2000 tokens chacun
            >>> for block in splitter.split_chapter("Chapter 1", chunks):
            ...     print(f"Block {block.block_number}: {block.token_count} tokens")
            Block 1: 4000 tokens
            Block 2: 2000 tokens
        """
        if not chunks:
            raise ValueError(f"Chapter '{chapter_name}': Liste de chunks vide")

        # Extraire le texte complet de chaque chunk
        chunk_texts: list[tuple[str, int]] = []
        for chunk in chunks:
            # Concaténer head + body + tail pour avoir le contexte complet
            text_parts: list[str] = []

            if chunk.head:
                text_parts.extend(chunk.head.values())
            if chunk.body:
                text_parts.extend(chunk.body.values())
            if chunk.tail:
                text_parts.extend(chunk.tail.values())

            text = "\n\n".join(text_parts)
            token_count = self.count_tokens(text)

            # Vérifier que le chunk n'est pas trop grand
            if token_count > self.target_tokens * 1.5:
                raise ValueError(
                    f"Chapter '{chapter_name}', Chunk {chunk.index}: "
                    f"Texte trop grand ({token_count} tokens > {self.target_tokens * 1.5}). "
                    f"Réduisez la taille des chunks de segmentation."
                )

            chunk_texts.append((text, token_count))

        # Regrouper les chunks en blocs de ~target_tokens
        blocks: list[tuple[str, int]] = []
        current_block_texts: list[str] = []
        current_token_count = 0

        for text, token_count in chunk_texts:
            # Si ajouter ce chunk dépasse la limite, créer un nouveau bloc
            if current_token_count > 0 and current_token_count + token_count > self.target_tokens:
                # Finaliser le bloc actuel
                block_text = "\n\n".join(current_block_texts)
                blocks.append((block_text, current_token_count))

                # Commencer un nouveau bloc
                current_block_texts = [text]
                current_token_count = token_count
            else:
                # Ajouter au bloc actuel
                current_block_texts.append(text)
                current_token_count += token_count

        # Finaliser le dernier bloc
        if current_block_texts:
            block_text = "\n\n".join(current_block_texts)
            blocks.append((block_text, current_token_count))

        # Générer les AnalysisBlocks
        total_blocks = len(blocks)
        for block_number, (block_text, token_count) in enumerate(blocks, start=1):
            yield AnalysisBlock(
                chapter_name=chapter_name,
                block_number=block_number,
                total_blocks=total_blocks,
                text=block_text,
                token_count=token_count,
            )

    def split_all_chapters(
        self,
        chapters: dict[str, list[Chunk]],
    ) -> dict[str, list[AnalysisBlock]]:
        """
        Découpe tous les chapitres d'un livre en blocs d'analyse.

        Cette méthode est un helper pour traiter plusieurs chapitres en une fois.

        Args:
            chapters: Dictionnaire {chapter_name: [chunks]}

        Returns:
            Dictionnaire {chapter_name: [AnalysisBlocks]}

        Example:
            >>> chapters = {
            ...     "Prologue": [chunk1, chunk2],
            ...     "Chapter 1": [chunk3, chunk4, chunk5],
            ... }
            >>> analysis_blocks = splitter.split_all_chapters(chapters)
            >>> for chapter_name, blocks in analysis_blocks.items():
            ...     print(f"{chapter_name}: {len(blocks)} blocks")
            Prologue: 1 blocks
            Chapter 1: 2 blocks
        """
        result: dict[str, list[AnalysisBlock]] = {}

        for chapter_name, chunk_list in chapters.items():
            result[chapter_name] = list(self.split_chapter(chapter_name, chunk_list))

        return result
