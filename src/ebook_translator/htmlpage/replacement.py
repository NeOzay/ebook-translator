"""
Méthodes pour remplacer le texte original par sa traduction dans le DOM.
"""

from typing import TYPE_CHECKING
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from .constants import FRAGMENT_SEPARATOR, VALID_ROOT_TAGS
from .bilingual import BilingualFormat, format_bilingual_inline

if TYPE_CHECKING:
    from typing import Union

    TextFragment = Union[NavigableString, list[NavigableString]]


class TextReplacer:
    """
    Classe utilitaire pour remplacer le texte dans les pages HTML.

    Cette classe contient toutes les méthodes liées au remplacement de texte,
    incluant les différents formats bilingues.
    """

    def __init__(self, soup: BeautifulSoup) -> None:
        """
        Initialise le replacer avec une instance BeautifulSoup.

        Args:
            soup: L'instance BeautifulSoup pour créer de nouvelles balises
        """
        self.soup = soup

    def replace_single_fragment(
        self,
        fragment: NavigableString,
        translated_text: str,
        bilingual_format: BilingualFormat,
    ) -> None:
        """
        Remplace un fragment unique avec son texte traduit.

        Args:
            fragment: Le fragment original
            translated_text: Le texte traduit
            bilingual_format: Format d'affichage bilingue (None pour remplacement simple)
        """
        if bilingual_format == BilingualFormat.SEPARATE_TAG:
            # Créer une balise séparée pour la traduction
            self.create_separate_translation_tag(fragment, translated_text)
        elif bilingual_format == BilingualFormat.INLINE:
            # Format inline
            original_text = fragment.strip()
            combined_text = format_bilingual_inline(original_text, translated_text)
            fragment.replace_with(combined_text)
        else:
            # bilingual_format is DISABLE : remplacement simple
            fragment.replace_with(translated_text)

    def replace_multiple_fragments(
        self,
        fragments: list[NavigableString],
        translated_text: str,
        bilingual_format: BilingualFormat,
    ) -> None:
        """
        Remplace plusieurs fragments avec un texte traduit segmenté.

        Args:
            fragments: Liste des fragments originaux
            translated_text: Texte traduit avec séparateurs '</>
            bilingual_format: Format d'affichage bilingue (None pour remplacement simple)

        Raises:
            ValueError: Si le nombre de segments ne correspond pas
        """
        segments = translated_text.split(FRAGMENT_SEPARATOR)

        if len(segments) != len(fragments):
            raise ValueError(
                f"Mismatch in fragment count: expected {len(fragments)}, "
                f"got {len(segments)} segments in translation. "
                f"Original: {fragments}, Translation segments: {segments}"
            )

        # Pour SEPARATE_TAG, créer une seule balise de traduction avec le texte complet
        if bilingual_format == BilingualFormat.SEPARATE_TAG:
            # Trouver la balise racine (commune à tous les fragments)
            root_tag = find_root_tag(fragments[0].parent)

            if root_tag:
                # Styler la balise originale
                self.style_original_tag(root_tag)

                # Créer une balise de traduction complète avec le texte reconstruit
                self.create_translation_tag_after(root_tag, translated_text)
            else:
                # Fallback : remplacer chaque fragment individuellement
                for fragment, translated_segment in zip(fragments, segments):
                    fragment.replace_with(translated_segment)
        else:
            # Pour les autres formats, remplacer chaque fragment individuellement
            for fragment, translated_segment in zip(fragments, segments):
                if fragment:
                    if bilingual_format == BilingualFormat.INLINE:
                        # Format inline
                        original_text = fragment.strip()
                        combined_text = format_bilingual_inline(
                            original_text, translated_segment
                        )
                        fragment.replace_with(combined_text)
                    else:
                        # bilingual_format is DISABLE : remplacement simple
                        fragment.replace_with(translated_segment)

    def style_original_tag(self, root_tag: Tag) -> None:
        """
        Applique le style à la balise originale (classe et couleur).

        Args:
            root_tag: La balise à styler
        """
        # Ajouter la classe "original" et le style à la balise originale
        original_classes = root_tag.get("class")
        if original_classes:
            if isinstance(original_classes, list):
                if "original" not in original_classes:
                    root_tag["class"] = " ".join(original_classes + ["original"])
            else:
                if "original" not in str(original_classes):
                    root_tag["class"] = f"{original_classes} original"
        else:
            root_tag["class"] = "original"

        # Ajouter le style inline pour la couleur de l'original (gris clair)
        root_tag["style"] = "color: #9ca3af;"

    def create_translation_tag_after(self, root_tag: Tag, translated_text: str) -> None:
        """
        Crée une nouvelle balise de traduction après la balise originale.

        Cette méthode reconstruit le contenu de la traduction en préservant
        la structure des balises imbriquées du tag original.

        Args:
            root_tag: La balise parente originale
            translated_text: Le texte traduit complet (peut contenir des '</>``)
        """
        # Récupérer les classes originales
        original_classes = root_tag.get("class")

        # Créer une nouvelle balise du même type pour la traduction
        new_tag = self.soup.new_tag(root_tag.name)

        # Ajouter la classe "translation" pour le style CSS
        if original_classes:
            # Conserver les classes existantes et ajouter "translation"
            if isinstance(original_classes, list):
                # Retirer 'original' si présent et ajouter 'translation'
                classes = [c for c in original_classes if c != "original"]
                new_tag["class"] = " ".join(classes + ["translation"])
            else:
                classes_str = str(original_classes).replace("original", "").strip()
                if classes_str:
                    new_tag["class"] = f"{classes_str} translation"
                else:
                    new_tag["class"] = "translation"
        else:
            new_tag["class"] = "translation"

        # Ajouter l'attribut lang pour indiquer la langue de traduction
        new_tag["lang"] = "translated"

        # Parser le texte traduit et reconstruire la structure
        self.reconstruct_tag_content(new_tag, root_tag, translated_text)

        # Insérer la nouvelle balise juste après la balise originale
        root_tag.insert_after(new_tag)

    def reconstruct_tag_content(
        self, new_tag: Tag, original_tag: Tag, translated_text: str
    ) -> None:
        """
        Reconstruit le contenu de la nouvelle balise en préservant la structure des balises imbriquées.

        Si le texte traduit contient des séparateurs '</>`, cette méthode essaie de
        reconstruire la structure HTML originale avec le texte traduit.

        Args:
            new_tag: La nouvelle balise à remplir
            original_tag: La balise originale (pour la structure)
            translated_text: Le texte traduit (peut contenir des '</>``)
        """
        if FRAGMENT_SEPARATOR not in translated_text:
            # Pas de fragments multiples : juste insérer le texte
            new_tag.string = translated_text
            return

        # Diviser le texte traduit en segments
        segments = translated_text.split(FRAGMENT_SEPARATOR)

        # Parcourir la structure originale et reconstruire avec les segments traduits
        segment_index = 0

        def clone_structure(source: Tag, target: Tag) -> None:
            """Clone la structure HTML de source vers target avec le texte traduit."""
            nonlocal segment_index

            for child in source.children:
                if isinstance(child, NavigableString):
                    # C'est un fragment de texte : utiliser le segment traduit
                    if child.strip() and segment_index < len(segments):
                        target.append(segments[segment_index])
                        segment_index += 1
                elif isinstance(child, Tag):
                    # C'est une balise : la cloner et continuer récursivement
                    new_child = self.soup.new_tag(child.name)

                    # Copier les attributs
                    for attr, value in child.attrs.items():
                        new_child[attr] = value

                    target.append(new_child)
                    clone_structure(child, new_child)

        clone_structure(original_tag, new_tag)

    def create_separate_translation_tag(
        self, fragment: NavigableString, translated_text: str
    ) -> None:
        """
        Crée une nouvelle balise séparée pour la traduction après la balise originale.

        Cette méthode trouve la balise parente racine (p, h1, etc.) contenant
        le fragment, et insère une nouvelle balise identique juste après avec
        la traduction. Les balises sont stylées avec des couleurs différentes :
        - Original : couleur gris clair (#9ca3af)
        - Traduction : couleur normale (pas de style)

        Args:
            fragment: Le fragment de texte original
            translated_text: Le texte traduit

        Example:
            Avant: <p>Original text</p>
            Après:
                <p class="original" style="color: #9ca3af;">Original text</p>
                <p class="translation">Translated text</p>
        """
        # Trouver la balise parente racine (p, h1, etc.)
        root_tag = find_root_tag(fragment.parent)

        if not root_tag:
            # Fallback : remplacer directement le fragment
            fragment.replace_with(translated_text)
            return

        # Styler la balise originale
        self.style_original_tag(root_tag)

        # Créer la balise de traduction
        self.create_translation_tag_after(root_tag, translated_text)


def find_root_tag(tag: Tag | None) -> Tag | None:
    """
    Trouve la balise racine valide la plus proche.

    Remonte l'arbre DOM jusqu'à trouver une balise dans VALID_ROOT_TAGS.

    Args:
        tag: La balise de départ

    Returns:
        La balise racine trouvée, ou None
    """
    if tag is None:
        return None

    current = tag
    while current:
        if current.name in VALID_ROOT_TAGS:
            return current
        current = current.parent

    return None
