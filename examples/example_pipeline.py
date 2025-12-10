"""
Exemple d'utilisation du pipeline de traduction modulaire.

Ce script démontre comment utiliser le nouveau Pipeline modulaire pour traduire
un EPUB avec des phases configurables et des transitions entre phases.
"""

from pathlib import Path

from ebook_translator.llm import LLM
from ebook_translator.pipeline import Pipeline
from ebook_translator.pipeline.phases import InitialTranslationPhase, RefinementPhase
from ebook_translator.transition.transitions import GlossaryValidationTransition


def main():
    """Exemple complet d'utilisation du pipeline modulaire."""

    # Fichiers EPUB
    source_epub = Path(
        "books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 02 [J-Novel Club][Premium].epub"
    )
    output_epub = Path(f"books/out/[FR] {source_epub.name}")

    # Créer instance LLM
    llm = LLM(
        model_name="deepseek-chat",
        reasoning_name="deepseek-reasoner",
        url="https://api.deepseek.com",
        temperature=0.5,  # Cohérence optimale
    )

    # Créer pipeline avec phases et transitions
    pipeline = Pipeline(
        llm=llm,
        epub_path=source_epub,
        cache_dir=Path("cache"),
        phases=[InitialTranslationPhase(), RefinementPhase()],
        transitions={
            (
                "initial",
                "refined",
            ): GlossaryValidationTransition,  # Validation glossaire entre phases
        },
        num_validation_workers=2,  # Nombre de workers pour validation
    )

    # Lancer traduction
    try:
        stats = pipeline.run(
            target_language="français",
            output_epub=output_epub,
            max_retries=1,
        )

        # Afficher résultats
        print("\n" + "=" * 60)
        print("✅ TRADUCTION TERMINÉE")
        print("=" * 60)

        for phase_name, phase_stats in stats.items():
            print(f"\n{phase_name.upper()}:")
            print(
                f"  • Chunks: {phase_stats.chunks_processed}/{phase_stats.chunks_total}"
            )
            print(f"  • Cache hits: {phase_stats.chunks_from_cache}")
            print(f"  • Traduits: {phase_stats.chunks_translated}")
            print(f"  • Validés: {phase_stats.chunks_validated}")
            print(f"  • Rejetés: {phase_stats.chunks_rejected}")
            print(f"  • Durée: {phase_stats.duration_seconds:.1f}s")

        print(f"\nEPUB final: {output_epub}")

    except RuntimeError as e:
        print(f"\n❌ ERREUR: {e}")

    except KeyboardInterrupt:
        print("\n\n❌ Traduction annulée par l'utilisateur")


def example_clear_caches():
    """
    Exemple de nettoyage des caches pour recommencer une traduction.
    """

    epub_path = Path("input/book.epub")
    cache_dir = Path("cache")

    llm = LLM(
        model_name="deepseek-chat",
        reasoning_name="deepseek-reasoner",
        url="https://api.deepseek.com",
    )

    pipeline = Pipeline(
        llm=llm,
        epub_path=epub_path,
        cache_dir=cache_dir,
        phases=[InitialTranslationPhase(), RefinementPhase()],
    )

    # Supprimer tous les caches (initial, refined, glossaire)
    pipeline.clear_caches()
    print("✅ Caches supprimés")


def example_three_phases():
    """
    Exemple avec 3 phases (démo de l'extensibilité).

    Note: QualityReviewPhase n'existe pas encore, cet exemple
    montre simplement comment ajouter une 3ème phase facilement.
    """

    # Pour ajouter une 3ème phase, il suffit de:
    # 1. Créer une classe QualityReviewPhase héritant de PhaseBase
    # 2. L'ajouter à la liste des phases
    # 3. Optionnellement ajouter une transition

    print(
        """
Pour ajouter une 3ème phase (ex: QualityReview), créer:

# pipeline/phases/quality_review.py
class QualityReviewPhase(PhaseBase):
    name = "quality"
    max_tokens = 500
    overlap_ratio = 0.5
    execution_mode = ExecutionMode.SEQUENTIAL
    template_name = TemplateNames.Quality_Review
    depends_on = [InitialTranslationPhase, RefinementPhase]
    checks = [QualityScoreCheck()]

    @classmethod
    def render_prompt(cls, chunk, context):
        initial = context.get_previous_translation(chunk, "initial")
        refined = context.get_previous_translation(chunk, "refined")
        return context.llm.renderer.render_quality_review(
            chunk, initial, refined, context.target_language
        )

# Puis utiliser:
pipeline = Pipeline(
    llm=llm,
    epub_path=source_epub,
    cache_dir=Path("cache"),
    phases=[
        InitialTranslationPhase,
        RefinementPhase,
        QualityReviewPhase,  # ← Nouvelle phase ajoutée!
    ],
    transitions={
        ("initial", "refined"): GlossaryValidationTransition,
        ("refined", "quality"): QualityThresholdTransition,
    },
)

Total: ~50-80 lignes de code pour ajouter une phase complète!
    """
    )


if __name__ == "__main__":
    # Décommenter l'exemple souhaité

    # Exemple standard avec validation interactive
    main()

    # Exemple de nettoyage des caches
    # example_clear_caches()

    # Exemple d'extensibilité (3 phases)
    # example_three_phases()
