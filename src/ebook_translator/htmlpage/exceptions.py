"""
Exceptions spécifiques au module htmlpage.

Ce module définit les exceptions personnalisées pour la gestion
des erreurs lors de la manipulation et traduction des pages HTML.
"""


class FragmentMismatchError(ValueError):
    """
    Exception levée quand le nombre de segments traduits ne correspond pas
    au nombre de fragments originaux.

    Cette exception contient toutes les données nécessaires pour tenter
    une correction automatique via le RetryEngine.

    Attributes:
        original_fragments: Liste des fragments de texte originaux
        translated_segments: Liste des segments traduits (nombre incorrect)
        original_text: Texte original complet avant traduction
        expected_count: Nombre de fragments attendus
        actual_count: Nombre de segments reçus
    """

    def __init__(
        self,
        original_fragments: list[str],
        translated_segments: list[str],
        original_text: str,
        expected_count: int,
        actual_count: int,
    ):
        """
        Initialise l'exception avec les données de l'erreur.

        Args:
            original_fragments: Liste des fragments originaux
            translated_segments: Liste des segments traduits incorrects
            original_text: Texte original complet
            expected_count: Nombre de fragments attendus
            actual_count: Nombre de segments reçus
        """
        self.original_fragments = original_fragments
        self.translated_segments = translated_segments
        self.original_text = original_text
        self.expected_count = expected_count
        self.actual_count = actual_count

        # Message d'erreur concis pour le log
        message = (
            f"Fragment count mismatch: expected {expected_count}, "
            f"got {actual_count} segments"
        )
        super().__init__(message)

    def __repr__(self) -> str:
        return (
            f"FragmentMismatchError(expected={self.expected_count}, "
            f"actual={self.actual_count})"
        )
