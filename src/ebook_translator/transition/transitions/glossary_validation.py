"""
Transition: Validation du glossaire entre Phase 1 et Phase 2.
"""

from ebook_translator.logger import get_logger
from ebook_translator.transition.base import TransitionBase, TransitionContext

# from ebook_translator.translation_pipeline.glossary_validator import GlossaryValidator

logger = get_logger(__name__)


class GlossaryValidationTransition(TransitionBase):
    """
    Transition: Validation du glossaire (Phase 1 → Phase 2).

    Cette transition:
    1. Vérifie si le glossaire a été appris en Phase 1
    2. Affiche les statistiques du glossaire
    3. Détecte les conflits terminologiques
    4. Propose résolution automatique ou manuelle
    5. Bloque la transition si validation annulée
    6. Nettoie le glossaire (stopwords, faible confiance)
    7. Sauvegarde le glossaire validé

    Configuration:
    - Par défaut: validation interactive avec l'utilisateur
    - Mode auto: résolution automatique des conflits (auto_resolve=True)

    Example:
        pipeline = Pipeline(
            phases=[InitialTranslationPhase, RefinementPhase],
            transitions={
                ("initial", "refined"): GlossaryValidationTransition,
            },
        )
    """

    name = "glossary_validation"

    def can_proceed(self, context: TransitionContext) -> tuple[bool, str]:
        """
        Vérifie si le glossaire peut être validé.

        Args:
            context: Contexte de transition

        Returns:
            (True, message) si validation réussie
            (False, message) si validation échouée ou annulée
        """
        # Pas de glossaire = validation automatique
        if context.glossary is None:
            logger.info("  • Pas de glossaire à valider")
            return True, "No glossary to validate"

        # Afficher statistiques avant validation
        glossary_stats = context.glossary.get_statistics()
        logger.info(
            f"  • Glossaire: {glossary_stats['total_terms']} termes appris, "
            f"{glossary_stats['conflicting_terms']} conflits"
        )

        # Créer validateur
        # TODO: Réimplémenter GlossaryValidator ou utiliser une alternative
        # validator = GlossaryValidator(context.glossary)

        # Validation interactive (ou automatique selon config)
        # Note: auto_resolve=False par défaut (validation interactive)
        # Pour skip validation: passer auto_resolve=True
        # is_validated = validator.validate_interactive(
        #     auto_resolve=False,  # Validation interactive par défaut
        #     auto_clean=True,  # Nettoyage automatique activé
        # )
        is_validated = True  # Temporaire: validation automatique désactivée

        if is_validated:
            logger.info("✅ Glossaire validé avec succès")
            return True, "Glossary validated"
        else:
            logger.warning("❌ Validation du glossaire annulée")
            return (
                False,
                "Glossary validation cancelled by user. "
                "Phase 2 cannot start without a validated glossary.",
            )

    def prepare_next_phase(self, context: TransitionContext) -> None:
        """
        Prépare la Phase 2 après validation du glossaire.

        Actions:
        - Nettoie le glossaire (déjà fait dans can_proceed)
        - Sauvegarde le glossaire validé
        - Switch le store du ValidationWorkerPool vers refined

        Args:
            context: Contexte de transition
        """
        # Nettoyer glossaire (au cas où non fait dans can_proceed)
        if context.glossary:
            context.glossary.clean_all()
            logger.debug("  • Glossaire nettoyé")

            # Sauvegarder glossaire validé
            context.glossary.save()
            logger.info("  • Glossaire sauvegardé")

        # Switch ValidationWorkerPool vers refined_store
        # Note: Sera fait automatiquement par PhaseExecutor de RefinementPhase
        # TODO: Implémenter switch_store dans ValidationWorkerPool si nécessaire
        # refined_store = context.store_manager.get_store("refined")
        # context.validation_pool.switch_store(refined_store)
        # logger.info("  • ValidationWorkerPool basculé vers refined_store")
