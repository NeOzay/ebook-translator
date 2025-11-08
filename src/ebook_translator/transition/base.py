"""
Classes de base pour les transitions entre phases.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from ebook_translator.pipeline.store_manager import StoreManager
    from ebook_translator.pipeline.context import PhaseStats
    from ebook_translator.validation import ValidationWorkerPool
    from ebook_translator.quality import Glossary


@dataclass
class TransitionContext:
    """
    Contexte passé aux transitions entre phases.

    Contient les ressources nécessaires pour valider et préparer
    la transition d'une phase à une autre.
    """

    store_manager: "StoreManager"
    """Gestionnaire de stores pour accéder aux caches"""

    validation_pool: "ValidationWorkerPool"
    """Pool de validation (peut être reconfiguré par la transition)"""

    previous_stats: dict[str, "PhaseStats"]
    """Statistiques de toutes les phases exécutées jusqu'ici"""

    glossary: "Glossary | None" = None
    """Glossaire optionnel"""

    def get_stats(self, phase_name: str) -> "PhaseStats | None":
        """
        Récupère les stats d'une phase spécifique.

        Args:
            phase_name: Nom de la phase

        Returns:
            PhaseStats si la phase a été exécutée, None sinon
        """
        return self.previous_stats.get(phase_name)


class TransitionBase(ABC):
    """
    Classe de base abstraite pour les transitions entre phases.

    Une transition est exécutée entre deux phases pour:
    - Valider que la phase précédente s'est bien déroulée
    - Préparer la phase suivante (ex: exporter glossaire, switch store)

    Utilise le pattern Singleton comme PhaseBase.

    Example:
        class GlossaryValidationTransition(TransitionBase):
            name = "glossary_validation"

            def can_proceed(self, context: TransitionContext) -> tuple[bool, str]:
                if context.glossary is None:
                    return True, "No glossary to validate"

                conflicts = context.glossary.get_conflicts()
                if not conflicts:
                    return True, "No conflicts"

                # Validation interactive
                validator = GlossaryValidator(context.glossary)
                validated = validator.validate_interactive(conflicts)

                return validated, "Validated" if validated else "Cancelled"

            def prepare_next_phase(self, context: TransitionContext) -> None:
                if context.glossary:
                    context.glossary.clean_all()
    """

    # === Configuration obligatoire ===

    name: ClassVar[str]
    """Identifiant unique de la transition"""

    # === Singleton ===

    _instances: ClassVar[dict[type["TransitionBase"], "TransitionBase"]] = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
        return cls._instances[cls]

    # === Validation de configuration ===

    def __init_subclass__(cls, **kwargs):
        """Valide que tous les champs obligatoires sont définis."""
        super().__init_subclass__(**kwargs)

        if not hasattr(cls, "name"):
            raise TypeError(f"Transition '{cls.__name__}' must define class attribute 'name'")

    # === Méthodes abstraites ===

    @abstractmethod
    def can_proceed(self, context: TransitionContext) -> tuple[bool, str]:
        """
        Vérifie si la transition peut se faire.

        Cette méthode est appelée AVANT prepare_next_phase().
        Si elle retourne False, la transition est bloquée et l'exécution
        du pipeline s'arrête.

        Args:
            context: Contexte de la transition

        Returns:
            Tuple (can_proceed, message):
                - can_proceed: True si la transition peut continuer
                - message: Message descriptif (succès ou raison du blocage)

        Example:
            def can_proceed(self, context):
                stats = context.get_stats("initial")
                if stats.rejection_rate() > 0.1:
                    return False, f"Quality too low: {stats.rejection_rate():.1%} rejected"
                return True, "Quality threshold met"
        """
        pass

    @abstractmethod
    def prepare_next_phase(self, context: TransitionContext) -> None:
        """
        Prépare la phase suivante.

        Cette méthode est appelée APRÈS can_proceed() si elle a retourné True.
        Elle peut modifier le contexte pour préparer la phase suivante.

        Utilisations typiques:
        - Switch du store du ValidationWorkerPool
        - Export du glossaire
        - Nettoyage de données temporaires
        - Logging de transition

        Args:
            context: Contexte de la transition

        Example:
            def prepare_next_phase(self, context):
                # Switch vers le store de la phase suivante
                refined_store = context.store_manager.get_store("refined")
                context.validation_pool.switch_store(refined_store)

                # Export glossaire
                if context.glossary:
                    context.glossary.export_to_file(Path("cache/glossary.json"))
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
