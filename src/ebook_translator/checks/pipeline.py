"""
Pipeline de validation strict avec correction automatique.

Ce module orchestre l'exécution séquentielle des checks avec
correction inline et retry automatique.
"""

from typing import TYPE_CHECKING

from ..logger import get_logger
from .base import Check, CheckResult, ValidationContext, ErrorData

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class ValidationPipeline:
    """
    Pipeline strict de validation avec correction inline.

    Ce pipeline exécute les checks de manière séquentielle et s'arrête
    à la première erreur. Si un check échoue, il tente de corriger
    automatiquement via check.correct() et re-valide. Ce processus
    se répète jusqu'à max_retries.

    Flux d'exécution:
    1. Exécuter check₁.validate()
    2. Si échec → check₁.correct() → re-validate() (max N fois)
    3. Si succès → passer à check₂
    4. Répéter jusqu'au dernier check
    5. Si tous OK → retourner traductions finales
    6. Si échec après max_retries → retourner échec

    Attributes:
        checks: Liste ordonnée des checks à exécuter

    Example:
        >>> from .line_count_check import LineCountCheck
        >>> from .fragment_count_check import FragmentCountCheck
        >>>
        >>> pipeline = ValidationPipeline([
        ...     LineCountCheck(),
        ...     FragmentCountCheck(),
        ... ])
        >>>
        >>> success, final_translations, results = pipeline.validate_and_correct(context)
        >>> if success:
        ...     store.save_all(source_file, final_translations)
        >>> else:
        ...     logger.error("Validation échouée", results)
    """

    def __init__(self, checks: list[Check]):
        """
        Initialise le pipeline avec une liste de checks.

        Args:
            checks: Liste ordonnée des checks à exécuter (ordre important!)

        Example:
            >>> pipeline = ValidationPipeline([
            ...     LineCountCheck(),      # Vérifie nombre de lignes d'abord
            ...     FragmentCountCheck(),  # Puis nombre de fragments
            ... ])
        """
        self.checks = checks

    def validate_and_correct(
        self, context: ValidationContext
    ) -> tuple[bool, dict[int, str], list[CheckResult]]:
        """
        Valide et corrige les traductions avec pipeline strict.

        Cette méthode exécute tous les checks de manière séquentielle.
        Pour chaque check :
        - Valide les traductions actuelles
        - Si échec : tente correction et re-valide (max_retries fois)
        - Si succès : passe au check suivant
        - Si échec après max_retries : arrête le pipeline

        Args:
            context: Contexte de validation avec chunk et traductions

        Returns:
            Tuple (success, final_translations, all_results)
            - success: True si tous checks OK, False si un check a échoué
            - final_translations: Traductions finales (corrigées si nécessaire)
            - all_results: Liste de tous les CheckResult (pour logs/debug)

        Example:
            >>> context = ValidationContext(
            ...     chunk=chunk,
            ...     translated_texts={0: "Bonjour"},  # Manque ligne 1
            ...     original_texts={0: "Hello", 1: "World"},
            ...     llm=llm,
            ...     target_language="fr",
            ...     phase="initial",
            ...     max_retries=2,
            ... )
            >>>
            >>> success, final, results = pipeline.validate_and_correct(context)
            >>> # success=True si ligne 1 corrigée, False sinon
            >>> # final={0: "Bonjour", 1: "Monde"} si corrigé
            >>> # results contient tous les CheckResult
        """
        # Copier traductions actuelles (seront modifiées par corrections)
        current_translations: dict[int, str] = dict(context.translated_texts)
        all_results: list[CheckResult] = []

        # Exécuter chaque check séquentiellement
        for check in self.checks:
            retry_count = 0

            # Boucle de retry pour ce check
            while retry_count <= context.max_retries:
                # Mettre à jour le contexte avec les traductions actuelles
                context.translated_texts = current_translations

                # Valider
                result = check.validate(context)
                all_results.append(result)

                if result.is_valid:
                    # Check OK → passer au suivant
                    logger.debug(f"✅ {check.name}: OK (chunk {context.chunk.index})")
                    break  # Sortir de la boucle retry

                # Check échoué → tenter correction si retries restants
                if retry_count < context.max_retries:
                    logger.warning(
                        f"⚠️ {check.name} échoué (tentative {retry_count + 1}/{context.max_retries}): "
                        f"{result.error_message}"
                    )

                    try:
                        # Tenter correction
                        logger.debug(
                            f"🔧 Correction {check.name} en cours (chunk {context.chunk.index})..."
                        )
                        current_translations = check.correct(context, result.error_data)
                        retry_count += 1

                        logger.debug(
                            f"🔄 Correction {check.name} terminée, re-validation..."
                        )

                    except Exception as e:
                        # Correction impossible → passer au filtrage
                        logger.warning(
                            f"⚠️ Correction {check.name} échouée (chunk {context.chunk.index}): {e}"
                        )
                        # Incrémenter retry_count pour sortir de la boucle
                        retry_count = context.max_retries

                else:
                    # Max retries atteint → tenter filtrage si check supporte get_invalid_lines
                    logger.warning(
                        f"⚠️ {check.name} échoué après {context.max_retries} tentatives "
                        f"(chunk {context.chunk.index}), filtrage des lignes invalides..."
                    )

                    # Obtenir les indices des lignes invalides
                    invalid_indices = check.get_invalid_lines(
                        context, result.error_data
                    )

                    if invalid_indices:
                        # Construire FilteredLine pour chaque ligne invalide
                        self._build_filtered_lines(
                            context, check, invalid_indices, check.name, result
                        )

                        # Filtrer les traductions : retirer lignes invalides
                        current_translations = {
                            idx: text
                            for idx, text in current_translations.items()
                            if idx not in invalid_indices
                        }

                        # Filtrer original_texts aussi
                        context.original_texts = {
                            idx: text
                            for idx, text in context.original_texts.items()
                            if idx not in invalid_indices
                        }

                        logger.warning(
                            f"🔧 {check.name} chunk {context.chunk.index}: {len(invalid_indices)} ligne(s) filtrée(s), "
                            f"{len(current_translations)} ligne(s) conservée(s)"
                        )

                        # Continuer avec les lignes valides au check suivant
                        break  # Sortir de la boucle retry, passer au check suivant
                    else:
                        # Pas de lignes invalides identifiées → échec complet
                        logger.error(
                            f"❌ {check.name} échoué mais aucune ligne invalide identifiée "
                            f"(chunk {context.chunk.index})"
                        )
                        return False, current_translations, all_results

        # Tous checks OK
        logger.debug(
            f"✅ Tous checks OK pour chunk {context.chunk.index} "
            f"({len(self.checks)} checks passés)"
        )
        return True, current_translations, all_results

    def validate_only(self, context: ValidationContext) -> list[CheckResult]:
        """
        Valide sans corriger (mode lecture seule).

        Utile pour vérifier le cache sans déclencher de corrections.
        Exécute tous les checks sans s'arrêter à la première erreur.

        Args:
            context: Contexte de validation (context.llm peut être None)

        Returns:
            Liste de tous les CheckResult (un par check)

        Example:
            >>> # Valider traductions en cache sans correction
            >>> context = ValidationContext(
            ...     chunk=chunk,
            ...     translated_texts=cached_translations,
            ...     original_texts=original_texts,
            ...     llm=None,  # Pas de LLM nécessaire
            ...     target_language="fr",
            ...     phase="initial",
            ...     max_retries=0,
            ... )
            >>>
            >>> results = pipeline.validate_only(context)
            >>> if any(not r.is_valid for r in results):
            ...     print("Cache invalide, retraduction nécessaire")
        """
        results: list[CheckResult] = []

        for check in self.checks:
            result = check.validate(context)
            results.append(result)

            if not result.is_valid:
                logger.debug(
                    f"⚠️ {check.name} échoué (lecture seule): {result.error_message}"
                )

        return results

    def _build_filtered_lines(
        self,
        context: ValidationContext,
        check: Check,
        invalid_indices: set[int],
        check_name: str,
        result: CheckResult,
    ) -> None:
        """
        Construit les FilteredLine pour chaque ligne invalide et les ajoute au contexte.

        Cette méthode récupère les métadonnées depuis chunk.body (TagKey) pour
        construire des FilteredLine avec toutes les informations nécessaires
        (file_name, file_line, chunk_index, chunk_line).

        Args:
            context: Contexte de validation (sera modifié pour ajouter filtered_lines)
            invalid_indices: Set des indices de lignes invalides
            check_name: Nom du check qui a filtré
            result: CheckResult contenant error_message et error_data

        Example:
            >>> invalid_indices = {5, 10, 15}
            >>> self._build_filtered_lines(context, invalid_indices, "line_count", result)
            >>> # context.filtered_lines contient maintenant 3 FilteredLine
        """
        from .base import FilteredLine

        # Énumérer le body pour récupérer les TagKey
        body_items = list(context.chunk.body.items())

        for chunk_line_idx in invalid_indices:
            # Vérifier que l'index est valide
            if chunk_line_idx >= len(body_items):
                logger.warning(
                    f"[ValidationPipeline] Index invalide {chunk_line_idx} "
                    f"(body size: {len(body_items)}), skip"
                )
                continue

            # Récupérer TagKey et texte original
            tag_key, original_text = body_items[chunk_line_idx]

            # Construire raison du filtrage depuis error_message
            reason = check.build_filter_reason(chunk_line_idx, result.error_data)

            # Construire FilteredLine
            filtered = FilteredLine(
                file_name=tag_key.page.epub_html.file_name,
                file_line=tag_key.index,  # Index du fragment dans le fichier HTML
                chunk_index=context.chunk.index,
                chunk_line=chunk_line_idx,
                check_name=check_name,
                reason=reason,
                original_text=original_text,  # Limiter à 100 chars
                translated_text=context.translated_texts.get(chunk_line_idx, ""),
            )

            context.filtered_lines.append(filtered)

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        check_names = [check.name for check in self.checks]
        return f"ValidationPipeline({check_names})"
