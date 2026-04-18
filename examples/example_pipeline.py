"""
Exemple d'utilisation du pipeline de traduction modulaire.

Ce script démontre comment utiliser le nouveau Pipeline modulaire pour traduire
un EPUB avec des phases configurables et des transitions entre phases.
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


def main():
    """Exemple complet d'utilisation du pipeline via builder."""

    # source_epub = Path("books/pg1952-images-3.epub")
    source_epub = Path(
        "books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 02 [J-Novel Club][Premium].epub"
    )

    output_epub = Path(f"books/out/[FR] {source_epub.name}")
    glossary = Glossary()
    # Lancer traduction
    try:
        stats = (
            PipelineBuilder()
            .epub(source_epub)
            .output(output_epub)
            .language(Language.FRENCH)
            .llm(
                LLMBuilder()
                .model("deepseek-chat")
                .reasoning("deepseek-reasoner")
                .url("https://api.deepseek.com")
                .temperature(0.5)
                .glossary_max_terms(25)
            )
            .phases(
                PhasesBuilder()
                # .add_literary_analysis(max_tokens=5000)
                .add_glossary_generation()
                # .add_initial_translation()
                # .add_refinement()
            )
            .workers(2)
            .glossary(glossary)
            # .cache_dir(Path("cache"))
            .max_retries(1)
            .bilingual_format(BilingualFormat.SEPARATE_TAG)
            .run()
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


if __name__ == "__main__":
    main()
