"""
Classe principale HtmlPage pour parser et manipuler les pages HTML des EPUB.
"""

from typing import TYPE_CHECKING, Iterator, Union
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from ebooklib import epub

from .constants import FRAGMENT_SEPARATOR, IGNORED_TAGS
from .tag_key import TagKey
from .bilingual import BilingualFormat
from .replacement import TextReplacer, find_root_tag

if TYPE_CHECKING:
    from typing import Self

# Type alias pour améliorer la lisibilité
TextFragment = Union[NavigableString, list[NavigableString]]


class HtmlPage:
    """
    Représente une page HTML d'un EPUB avec ses textes traduisibles.

    Cette classe implémente un pattern Singleton basé sur l'EpubHtml source
    pour éviter de parser plusieurs fois la même page. Elle extrait les
    fragments de texte traduisible et permet de les remplacer par leur
    traduction.

    Attributes:
        epub_html: L'objet EpubHtml source
        soup: L'arbre BeautifulSoup parsé
        to_translate: Dictionnaire mapping TagKey -> fragments de texte
        all_dump: Indique si tous les textes ont été extraits
    """

    # Cache global des pages déjà parsées
    _cache: dict[epub.EpubHtml, "HtmlPage"] = {}

    def __new__(cls, epub_html: epub.EpubHtml) -> "HtmlPage":
        """
        Implémente le pattern Singleton pour chaque EpubHtml.

        Args:
            epub_html: L'objet EpubHtml à parser

        Returns:
            Instance de HtmlPage (nouvelle ou depuis le cache)
        """
        cached = cls._cache.get(epub_html)
        if cached is not None:
            return cached

        instance = super().__new__(cls)
        cls._cache[epub_html] = instance
        return instance

    def __init__(self, epub_html: epub.EpubHtml) -> None:
        """
        Initialise la page HTML et parse son contenu.

        Args:
            epub_html: L'objet EpubHtml contenant le HTML à parser
        """
        # Éviter la ré-initialisation si déjà dans le cache
        if hasattr(self, "soup"):
            return

        self.epub_html = epub_html
        html_content = epub_html.content.decode("utf-8")
        self.soup = BeautifulSoup(html_content, "html.parser")
        self.to_translate: dict[TagKey, TextFragment] = {}
        self.all_dump = False
        self._replacer = TextReplacer(self.soup)

    def dump(self) -> Iterator[tuple[TagKey, str]]:
        """
        Extrait tous les fragments de texte traduisibles de la page.

        Cette méthode parcourt le body de la page HTML et groupe les fragments
        de texte par balise parente (p, h1-h6). Les fragments multiples dans
        la même balise sont joints avec le séparateur '</>' .

        Yields:
            Tuples (TagKey, texte) pour chaque groupe de fragments

        Example:
            >>> page = HtmlPage(epub_html)
            >>> for tag_key, text in page.dump():
            ...     print(f"{tag_key}: {text}")
        """
        body = self.soup.find("body")
        if not body:
            return

        current_parent: Tag | None = None
        current_fragments: TextFragment = []

        index = 0
        for text_fragment in body.find_all(string=True):
            # Ignorer les textes vides et ceux dans des balises non-traduisibles
            if self._should_ignore_fragment(text_fragment):
                continue

            # Vérifier si ce fragment appartient au même parent
            if self._has_same_parent(text_fragment, current_parent):
                current_fragments = self._append_fragment(
                    current_fragments, text_fragment
                )
            else:
                # Nouveau parent : yield le groupe précédent
                if current_parent and current_fragments:
                    yield self._store_fragments(
                        index, current_parent, current_fragments
                    )
                index += 1
                # Commencer un nouveau groupe
                current_parent = find_root_tag(text_fragment.parent)
                current_fragments = text_fragment

        # Yield le dernier groupe
        if current_parent and current_fragments:
            yield self._store_fragments(index, current_parent, current_fragments)

        self.all_dump = True

    def replace_text(
        self,
        tag_key: TagKey,
        translated_text: str,
        bilingual_format: BilingualFormat = BilingualFormat.DISABLE,
        original_text: str = "",
    ) -> None:
        """
        Remplace les fragments de texte originaux par leur traduction.

        Si le texte contient le séparateur '</>', il sera divisé pour
        remplacer chaque fragment individuellement. Une fois tous les textes
        remplacés, le contenu de l'EPUB est automatiquement mis à jour.

        Args:
            tag_key: La clé identifiant les fragments à remplacer
            translated_text: Le texte traduit (peut contenir des '</>')
            bilingual_format: Format d'affichage bilingue. Si None, remplace
                complètement le texte original. Si fourni, conserve l'original
                avec la traduction dans le format spécifié.
            original_text: Texte original complet (pour retry automatique en cas d'erreur)

        Raises:
            KeyError: Si le tag_key n'existe pas dans to_translate
            FragmentMismatchError: Si le nombre de segments ne correspond pas (avec données retry)
            ValueError: Fallback si FragmentMismatchError non disponible

        Example:
            >>> # Remplacement simple (pas bilingue)
            >>> page.replace_text(tag_key, "Texte traduit")

            >>> # Mode bilingue avec balises séparées (recommandé)
            >>> page.replace_text(tag_key, "Translated text",
            ...                   bilingual_format=BilingualFormat.SEPARATE_TAG)
            >>> # Résultat:
            >>> # <p class="original" style="color: #9ca3af;">Original text</p>
            >>> # <p class="translation">Translated text</p>

            >>> # Mode bilingue inline
            >>> page.replace_text(tag_key, "Translated text",
            ...                   bilingual_format=BilingualFormat.INLINE)
            >>> # Résultat: "Original text | Translated text"

        """
        text_fragments = self.to_translate.pop(tag_key, None)
        if not text_fragments:
            raise KeyError(
                f"No text fragments found for {tag_key}. "
                f"Either it was already replaced or never extracted."
            )

        if isinstance(text_fragments, list):
            self._replacer.replace_multiple_fragments(
                text_fragments, translated_text, bilingual_format, original_text
            )
        else:
            self._replacer.replace_single_fragment(
                text_fragments, translated_text, bilingual_format
            )

        # Si tous les textes ont été remplacés, sauvegarder le contenu
        if self.all_dump and not self.to_translate:
            self._save_content()

    def _should_ignore_fragment(self, fragment: NavigableString) -> bool:
        """
        Détermine si un fragment de texte doit être ignoré.

        Args:
            fragment: Le fragment à tester

        Returns:
            True si le fragment doit être ignoré
        """
        if not fragment.strip():
            return True

        parent = fragment.parent
        if parent and parent.name in IGNORED_TAGS:
            return True

        return False

    def _has_same_parent(
        self, fragment: NavigableString, last_parent: Tag | None
    ) -> bool:
        """
        Vérifie si un fragment appartient au même parent que le précédent.

        Args:
            fragment: Le fragment à tester
            last_parent: Le parent du groupe précédent

        Returns:
            True si le fragment appartient au même groupe
        """
        if last_parent is None:
            return False

        parent = fragment.parent
        while parent:
            if parent is last_parent:
                return True
            parent = parent.parent

        return False

    def _append_fragment(
        self, fragments: TextFragment, new_fragment: NavigableString
    ) -> list[NavigableString]:
        """
        Ajoute un fragment à la collection existante.

        Args:
            fragments: Les fragments existants
            new_fragment: Le nouveau fragment à ajouter

        Returns:
            Liste contenant tous les fragments
        """
        if isinstance(fragments, list):
            fragments.append(new_fragment)
            return fragments
        else:
            return [fragments, new_fragment]

    def _store_fragments(
        self, index: int, parent: Tag, fragments: TextFragment
    ) -> tuple[TagKey, str]:
        """
        Stocke les fragments dans le dictionnaire et retourne le tuple à yield.

        Args:
            parent: La balise parente
            fragments: Les fragments à stocker

        Returns:
            Tuple (TagKey, texte formaté)
        """
        tag_key = TagKey(index, parent, self)
        self.to_translate[tag_key] = fragments
        text = self._format_text(fragments)
        return tag_key, text

    def _format_text(self, fragments: TextFragment) -> str:
        """
        Formate les fragments en une chaîne avec le séparateur '</>' .

        IMPORTANT: Préserve les espaces de début/fin de chaque fragment pour
        maintenir l'espacement correct autour des balises imbriquées.

        Args:
            fragments: Le ou les fragments à formater

        Returns:
            Chaîne formatée avec séparateurs et espaces préservés
        """
        if isinstance(fragments, list):
            # Préserver les espaces de bordure
            formatted = []
            for fragment in fragments:
                text = str(fragment)
                # Détecter les espaces de bordure
                leading = len(text) - len(text.lstrip())
                trailing = len(text) - len(text.rstrip())

                # Normaliser uniquement le texte interne (sans les bordures)
                core = text.strip()
                core = " ".join(core.split())  # Normaliser espaces multiples/newlines

                # Reconstituer avec les espaces de bordure (max 1 espace de chaque côté)
                prefix = " " if leading > 0 else ""
                suffix = " " if trailing > 0 else ""
                formatted.append(prefix + core + suffix)

            return FRAGMENT_SEPARATOR.join(formatted)
        else:
            # Fragment unique
            text = str(fragments)
            leading = len(text) - len(text.lstrip())
            trailing = len(text) - len(text.rstrip())

            core = text.strip()
            core = " ".join(core.split())

            prefix = " " if leading > 0 else ""
            suffix = " " if trailing > 0 else ""
            return prefix + core + suffix

    def _save_content(self) -> None:
        """Sauvegarde le contenu HTML modifié dans l'EpubHtml."""
        self.epub_html.set_content(self.soup.encode("utf-8"))

    def __str__(self) -> str:
        """Retourne le nom du fichier pour l'affichage."""
        return str(self.epub_html.file_name)

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        return (
            f"HtmlPage({self.epub_html.file_name}, {len(self.to_translate)} fragments)"
        )


def get_files(
    epub_htmls: list[epub.EpubHtml],
) -> Iterator[tuple[HtmlPage, TagKey, str]]:
    """
    Génère des tuples (page, tag_key, texte) pour tous les fichiers EPUB.

    Cette fonction est un générateur qui parse chaque page HTML et extrait
    tous ses fragments de texte traduisibles.

    Args:
        epub_htmls: Liste des objets EpubHtml à traiter

    Yields:
        Tuples (HtmlPage, TagKey, texte) pour chaque fragment

    Example:
        >>> for page, tag_key, text in get_files(epub_htmls):
        ...     translation = translate(text)
        ...     page.replace_text(tag_key, translation)
    """
    for epub_html in epub_htmls:
        page = HtmlPage(epub_html)
        for tag_key, text in page.dump():
            yield page, tag_key, text
