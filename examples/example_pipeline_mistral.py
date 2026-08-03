"""
Exemple d'utilisation du pipeline avec le provider Mistral.

Identique à `example_pipeline.py`, au client près : `Mistral` s'appuie sur le
package officiel `mistralai` et cible `mistral-large-latest`.

La clé API est lue dans `MISTRAL_API_KEY`, avec repli sur `API_KEY`.
"""

from pathlib import Path

from ebook_translator import (
    BilingualFormat,
    Language,
    LLMBuilder,
    PhasesBuilder,
    PipelineBuilder,
)
from ebook_translator.glossary import Glossary
from ebook_translator.llm.clients.mistral import Mistral, MistralModels


def main():
    """Exemple complet d'utilisation du pipeline via builder, sur Mistral Large."""

    source_epub = Path("./books/The Yellow Wallpaper.epub")
    output_epub = Path(f"books/out/[FR] {source_epub.name}")
    glossary = Glossary()

    try:
        stats = (
            PipelineBuilder()
            .epub(source_epub)
            .output(output_epub)
            .language(Language.FRENCH)
            .llm(
                LLMBuilder()
                .default_client(
                    Mistral(
                        MistralModels.LARGE,
                        config={"temperature": 0.5, "max_tokens": 15000},
                    )
                )
                .glossary_max_terms(25)
            )
            .phases(
                PhasesBuilder()
                .add_literary_analysis(max_tokens=5000)
                .add_glossary_generation()
                .add_initial_translation(max_workers=1)
                # Phase 2 désactivée : elle ne s'exécute jamais réellement
                # (cf. docs/TECHNICAL_DEBT.md §8) et n'a donc pas pu être
                # validée avec Mistral.
                # .add_refinement()
            )
            .workers(2)
            .glossary(glossary)
            .bilingual_format(BilingualFormat.SEPARATE_TAG)
            .run()
        )

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


if __name__ == "__main__":
    main()
