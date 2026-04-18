from collections.abc import Callable, Iterator
from itertools import count
from typing import TYPE_CHECKING

import tiktoken

from ebook_translator.config import Config

if TYPE_CHECKING:
    from ebook_translator.htmlpage import TagKey
    from ebook_translator.segmentation import Chunk
    from ebook_translator.segmentation.chunk import Scope


def chunk_generator() -> Callable[[], Chunk]:
    """
    Retourne une fonction générant des chunks avec index séquentiel.

    Returns:
        Fonction qui crée des Chunk avec index incrémental
    """
    from ebook_translator.segmentation import Chunk

    counter = count(0)
    return lambda: Chunk(index=next(counter))


_encoding_cache: dict[str, tiktoken.Encoding] = {}


def get_encoding(encoding_name: str) -> tiktoken.Encoding:
    """
    Récupère l'encodage de tokens spécifié.

    Args:
            encoding_name: Le nom de l'encodage à récupérer

    Returns:
            L'objet d'encodage correspondant
    """
    if encoding_name not in _encoding_cache:
        _encoding_cache[encoding_name] = tiktoken.get_encoding(encoding_name)
    return _encoding_cache[encoding_name]


def count_tokens(text: str, encoding_name: str) -> int:
    """
    Compte le nombre de tokens dans un texte donné.

    Args:
            encoding: L'encodage à utiliser pour le comptage
            text: Le texte à analyser

    Returns:
            Le nombre de tokens dans le texte
    """
    encoding = get_encoding(encoding_name)
    return len(encoding.encode(text))


def turn_resource_to_chunks(
    resource_iterable: Iterator[tuple[TagKey, str]],
    max_tokens: int,
    overlap_ratio: float = 0,
    encoding_name: str = Config.DEFAULT_ENCODING,
) -> Iterator[Chunk]:
    def add_fragment_to_body(
        chunk: Chunk, tag_key: TagKey, text: str, token_count: int = 0
    ) -> None:
        chunk.body[tag_key] = text
        chunk.token_count += (
            token_count if token_count > 0 else count_tokens(text, encoding_name)
        )

    def fill_head_from_previous(
        previous_chunks: dict[Chunk, int], current_chunk: Chunk
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
        overlap_budget = calculate_overlap_tokens()

        collect_text: dict[TagKey, str] = {}
        for chunk in reversed(previous_chunks.keys()):
            # Parcourir le body en ordre inverse
            for tag_key in reversed(chunk.body):
                text = chunk.body[tag_key]
                token_count = count_tokens(text, encoding_name)
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

    def calculate_overlap_tokens() -> int:
        return int(max_tokens * overlap_ratio)

    chunk_queue: dict[Chunk, int] = {}
    _create_new_chunk = chunk_generator()
    current_chunk = _create_new_chunk()
    current_token_count = 0

    for tag_key, text in resource_iterable:
        token_count = count_tokens(text, encoding_name)

        if current_token_count + token_count > max_tokens:
            # Chunk plein : préparer le suivant
            chunk_queue[current_chunk] = calculate_overlap_tokens()
            current_chunk.token_count = current_token_count

            current_chunk = _create_new_chunk()
            add_fragment_to_body(current_chunk, tag_key, text, token_count=token_count)
            fill_head_from_previous(chunk_queue, current_chunk)

            current_token_count = token_count
        else:
            # Ajouter au chunk actuel
            add_fragment_to_body(current_chunk, tag_key, text, token_count=token_count)
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
    yield from chunk_queue.keys()

    # Yield le chunk actuel seulement s'il n'a pas déjà été yielded via la queue
    if current_chunk not in chunk_queue:
        yield current_chunk


def is_included_in_scope(in_scope: Scope, out_scope: Scope) -> bool:
    """
    Vérifie si une portée de fragments est incluse dans une autre.

    Args:
            in_scope: Portée à vérifier (liste de tuples (file_name, line_number))
            out_scope: Portée de référence (liste de tuples (file_name, line_number))

    Returns:
            True si in_scope est entièrement contenu dans out_scope, False sinon
    """
    if (len(in_scope) < 2 or len(out_scope) < 2) or len(in_scope) > len(out_scope):
        return False

    in_iter = iter(in_scope)
    in_file, in_line = next(in_iter, (None, None))
    is_first_out_element = True
    for out_file, out_line in out_scope:
        while not (in_file is None or in_line is None) and in_file == out_file:
            if is_first_out_element:
                is_first_out_element = False
                if in_line < out_line:
                    return False
            elif out_line != -1 and in_line > out_line:
                return False

            in_file, in_line = next(in_iter, (None, None))
            if in_file != out_file or (
                in_line and in_line > out_line and out_line != -1
            ):
                break
        is_first_out_element = False
    return in_file is None and in_line is None
