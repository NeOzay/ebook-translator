"""
Validation interactive du glossaire avant la Phase 2.

Ce module fournit une interface interactive pour :
- Afficher les statistiques du glossaire après Phase 1
- Détecter et résoudre les conflits terminologiques
- Permettre la validation manuelle des traductions
- Bloquer la transition Phase 1 → Phase 2 jusqu'à validation complète
"""

from typing import TYPE_CHECKING

from ..logger import get_logger

if TYPE_CHECKING:
    from ..glossary import Glossary

logger = get_logger(__name__)


class GlossaryValidator:
    """
    Validateur interactif du glossaire pour transition Phase 1 → Phase 2.

    Responsabilités:
    - Afficher le résumé du glossaire (termes appris, conflits)
    - Proposer résolution des conflits (choix automatique ou manuel)
    - Permettre édition manuelle des traductions
    - Sauvegarder le glossaire validé

    Example:
        >>> validator = GlossaryValidator(glossary)
        >>> is_valid = validator.validate_interactive()
        >>> if is_valid:
        ...     print("Glossaire validé, Phase 2 peut démarrer")
    """

    def __init__(self, glossary: "Glossary"):
        """
        Initialise le validateur.

        Args:
            glossary: Instance du glossaire à valider
        """
        self.glossary = glossary

    def validate_interactive(self, auto_resolve: bool = False) -> bool:
        """
        Lance la validation interactive du glossaire.

        Args:
            auto_resolve: Si True, résout automatiquement les conflits
                         en choisissant la traduction la plus fréquente (défaut: False)

        Returns:
            True si le glossaire est validé (aucun conflit non résolu)
            False si l'utilisateur annule la validation

        Example:
            >>> validator = GlossaryValidator(glossary)
            >>> if validator.validate_interactive():
            ...     # Glossaire validé, continuer vers Phase 2
            ...     pass
        """
        logger.info("=" * 60)
        logger.info("📚 VALIDATION DU GLOSSAIRE")
        logger.info("=" * 60)

        # Afficher statistiques
        self._display_statistics()

        # Détecter conflits
        conflicts = self.glossary.get_conflicts()

        if not conflicts:
            logger.info("✅ Aucun conflit détecté dans le glossaire")
            self._display_sample_terms()
            return self._confirm_validation()

        # Conflits détectés
        logger.warning(f"⚠️  {len(conflicts)} terme(s) avec traductions conflictuelles détecté(s)")
        self._display_conflicts(conflicts)

        if auto_resolve:
            logger.info("🤖 Résolution automatique des conflits...")
            self._auto_resolve_conflicts(conflicts)
            logger.info("✅ Conflits résolus automatiquement")
            return True

        # Résolution manuelle
        return self._resolve_conflicts_interactive(conflicts)

    def _display_statistics(self) -> None:
        """Affiche les statistiques du glossaire."""
        stats = self.glossary.get_statistics()

        logger.info(
            f"\n📊 STATISTIQUES DU GLOSSAIRE:\n"
            f"  • Termes appris: {stats['total_terms']}\n"
            f"  • Termes validés: {stats['validated_terms']}\n"
            f"  • Termes en conflit: {stats['conflicting_terms']}\n"
            f"  • Traductions uniques: {stats['unique_translations']}"
        )

    def _display_sample_terms(self, max_terms: int = 10) -> None:
        """
        Affiche un échantillon de termes appris.

        Args:
            max_terms: Nombre maximum de termes à afficher (défaut: 10)
        """
        high_conf_terms = self.glossary.get_high_confidence_terms(min_confidence=0.8)

        if not high_conf_terms:
            logger.info("\n(Aucun terme haute confiance à afficher)")
            return

        logger.info(f"\n📖 ÉCHANTILLON DE TERMES (haute confiance >80%):")

        count = 0
        for source, translation in sorted(high_conf_terms.items()):
            if count >= max_terms:
                remaining = len(high_conf_terms) - max_terms
                if remaining > 0:
                    logger.info(f"  ... et {remaining} autre(s) terme(s)")
                break

            logger.info(f"  • {source} → {translation}")
            count += 1

    def _display_conflicts(self, conflicts: dict[str, list[str]]) -> None:
        """
        Affiche les conflits détectés.

        Args:
            conflicts: Dictionnaire {terme_source: [traductions_conflictuelles]}
        """
        logger.info("\n⚠️  CONFLITS TERMINOLOGIQUES:")

        for source_term, translations in sorted(conflicts.items()):
            # Récupérer les compteurs pour chaque traduction
            term_data = self.glossary._glossary[source_term]
            total = sum(term_data.values())

            logger.info(f"\n  • {source_term}:")
            for trans in translations:
                count = term_data[trans]
                percentage = (count / total) * 100
                logger.info(f"    - '{trans}' ({count}×, {percentage:.0f}%)")

    def _auto_resolve_conflicts(self, conflicts: dict[str, list[str]]) -> None:
        """
        Résout automatiquement les conflits en choisissant la traduction la plus fréquente.

        Args:
            conflicts: Dictionnaire {terme_source: [traductions_conflictuelles]}
        """
        for source_term in conflicts:
            # Récupérer la traduction la plus fréquente
            most_frequent = self.glossary.get_translation(
                source_term, min_confidence=0.0
            )
            if most_frequent:
                self.glossary.validate_translation(source_term, most_frequent)
                logger.debug(
                    f"  • {source_term} → {most_frequent} (automatique)"
                )

    def _resolve_conflicts_interactive(self, conflicts: dict[str, list[str]]) -> bool:
        """
        Résout les conflits de manière interactive avec l'utilisateur.

        Args:
            conflicts: Dictionnaire {terme_source: [traductions_conflictuelles]}

        Returns:
            True si tous les conflits sont résolus, False si annulé
        """
        logger.info("\n" + "=" * 60)
        logger.info("🔧 RÉSOLUTION DES CONFLITS")
        logger.info("=" * 60)
        logger.info(
            "\nPour chaque terme en conflit, vous pouvez :\n"
            "  • Taper le numéro de la traduction à utiliser\n"
            "  • Taper 'a' pour résoudre automatiquement (choix le plus fréquent)\n"
            "  • Taper 's' pour passer (résolution automatique à la fin)\n"
            "  • Taper 'q' pour quitter sans valider"
        )

        skipped_terms = []

        for i, (source_term, translations) in enumerate(sorted(conflicts.items()), 1):
            term_data = self.glossary._glossary[source_term]
            total = sum(term_data.values())

            logger.info(f"\n[{i}/{len(conflicts)}] Terme: '{source_term}'")
            for j, trans in enumerate(translations, 1):
                count = term_data[trans]
                percentage = (count / total) * 100
                logger.info(f"  {j}. '{trans}' ({count}×, {percentage:.0f}%)")

            # Demander à l'utilisateur
            while True:
                try:
                    choice = input("Votre choix: ").strip().lower()

                    if choice == 'q':
                        logger.warning("❌ Validation annulée par l'utilisateur")
                        return False

                    if choice == 's':
                        skipped_terms.append(source_term)
                        logger.info("⏭️  Terme passé (résolution automatique à la fin)")
                        break

                    if choice == 'a':
                        most_frequent = self.glossary.get_translation(
                            source_term, min_confidence=0.0
                        )
                        if most_frequent:
                            self.glossary.validate_translation(source_term, most_frequent)
                            logger.info(f"✅ Résolu automatiquement: {source_term} → {most_frequent}")
                        break

                    # Choix numérique
                    choice_num = int(choice)
                    if 1 <= choice_num <= len(translations):
                        selected = translations[choice_num - 1]
                        self.glossary.validate_translation(source_term, selected)
                        logger.info(f"✅ Validé: {source_term} → {selected}")
                        break
                    else:
                        logger.warning(f"⚠️  Numéro invalide (1-{len(translations)})")

                except ValueError:
                    logger.warning("⚠️  Entrée invalide. Tapez un numéro, 'a', 's' ou 'q'")
                except KeyboardInterrupt:
                    logger.warning("\n❌ Validation annulée par l'utilisateur")
                    return False

        # Résoudre automatiquement les termes passés
        if skipped_terms:
            logger.info(f"\n🤖 Résolution automatique de {len(skipped_terms)} terme(s) passé(s)...")
            for source_term in skipped_terms:
                most_frequent = self.glossary.get_translation(
                    source_term, min_confidence=0.0
                )
                if most_frequent:
                    self.glossary.validate_translation(source_term, most_frequent)
                    logger.debug(f"  • {source_term} → {most_frequent}")

        logger.info("\n✅ Tous les conflits ont été résolus")
        return True

    def _confirm_validation(self) -> bool:
        """
        Demande confirmation à l'utilisateur pour valider le glossaire.

        Returns:
            True si l'utilisateur confirme, False sinon
        """
        self._display_sample_terms()

        logger.info("\n" + "=" * 60)
        logger.info("❓ CONFIRMATION")
        logger.info("=" * 60)

        while True:
            try:
                choice = input(
                    "Valider ce glossaire pour la Phase 2 ? [O/n]: "
                ).strip().lower()

                if choice in ['', 'o', 'oui', 'y', 'yes']:
                    logger.info("✅ Glossaire validé")
                    return True
                elif choice in ['n', 'non', 'no']:
                    logger.warning("❌ Validation annulée par l'utilisateur")
                    return False
                else:
                    logger.warning("⚠️  Réponse invalide. Tapez 'O' (oui) ou 'n' (non)")

            except KeyboardInterrupt:
                logger.warning("\n❌ Validation annulée par l'utilisateur")
                return False

    def export_summary(self) -> str:
        """
        Exporte un résumé textuel du glossaire validé.

        Returns:
            Résumé formaté pour affichage ou sauvegarde

        Example:
            >>> summary = validator.export_summary()
            >>> print(summary)
        """
        stats = self.glossary.get_statistics()
        conflicts = self.glossary.get_conflicts()

        summary = [
            "=" * 60,
            "📚 RÉSUMÉ DU GLOSSAIRE VALIDÉ",
            "=" * 60,
            "",
            "📊 Statistiques:",
            f"  • Termes appris: {stats['total_terms']}",
            f"  • Termes validés: {stats['validated_terms']}",
            f"  • Conflits résolus: {stats['conflicting_terms']}",
            "",
        ]

        if conflicts:
            summary.append("⚠️  ATTENTION: Conflits non résolus:")
            for source, translations in sorted(conflicts.items()):
                summary.append(f"  • {source}: {', '.join(translations)}")
            summary.append("")

        # Échantillon de termes haute confiance
        high_conf = self.glossary.get_high_confidence_terms(min_confidence=0.8)
        if high_conf:
            summary.append("📖 Termes haute confiance (échantillon):")
            for i, (source, translation) in enumerate(sorted(high_conf.items())):
                if i >= 20:
                    remaining = len(high_conf) - 20
                    summary.append(f"  ... et {remaining} autre(s) terme(s)")
                    break
                summary.append(f"  • {source} → {translation}")

        summary.append("=" * 60)

        return "\n".join(summary)
