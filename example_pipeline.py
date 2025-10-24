"""
Exemple d'utilisation du pipeline de traduction en 2 phases.

Ce script démontre comment utiliser le TwoPhasePipeline pour traduire
un EPUB avec validation du glossaire entre Phase 1 et Phase 2.
"""

from pathlib import Path
from ebook_translator.llm import LLM
from ebook_translator.pipeline.two_phase_pipeline import TwoPhasePipeline
from ebook_translator.translation.language import Language


def main():
    """Exemple complet d'utilisation du pipeline."""

    # Fichiers EPUB
    source_epub = Path(
        "books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 02 [J-Novel Club][Premium].epub"
    )
    output_epub = Path(f"books/out/[FR] {source_epub.name}")

    # Créer instance LLM
    llm = LLM(
        model_name="deepseek-chat",
        url="https://api.deepseek.com",
        temperature=0.5,  # Cohérence optimale
    )

    # Créer pipeline
    pipeline = TwoPhasePipeline(
        llm=llm,
        epub_path=source_epub,
    )

    # Lancer traduction
    try:
        stats = pipeline.run(
            target_language=Language.FRENCH,
            output_epub=output_epub,
            phase1_workers=1,  # 4 threads parallèles en Phase 1
            phase1_max_tokens=1500,  # Gros blocs pour apprentissage
            phase2_max_tokens=300,  # Petits blocs pour affinage
            validation_timeout=60.0,  # Timeout pour corrections
            auto_validate_glossary=False,  # Validation interactive (défaut)
        )

        # Afficher résultats
        print("\n" + "=" * 60)
        print("✅ TRADUCTION TERMINÉE")
        print("=" * 60)
        print(
            f"Phase 1: {stats['phase1']['translated']}/{stats['phase1']['total_chunks']} chunks"
        )
        print(
            f"Phase 2: {stats['phase2']['refined']}/{stats['phase2']['total_chunks']} chunks"
        )
        print(
            f"Validation: {stats['validation']['validated']} validés, "
            f"{stats['validation']['rejected']} rejetés"
        )
        print(f"Glossaire: {stats['glossary']['total_terms']} termes appris")
        print(f"Durée: {stats['total_duration']:.1f}s")
        print(f"EPUB final: {output_epub}")

    except RuntimeError as e:
        print(f"\n❌ ERREUR: {e}")

        # Afficher statistiques de validation si disponibles
        validation_stats = pipeline.get_validation_stats()
        if validation_stats and validation_stats.get("rejected", 0) > 0:
            print(
                f"\n⚠️  {validation_stats['rejected']} chunk(s) rejeté(s) "
                f"après validation (voir logs pour détails)"
            )

    except KeyboardInterrupt:
        print("\n\n❌ Traduction annulée par l'utilisateur")


def example_auto_validation():
    """
    Exemple avec validation automatique du glossaire.

    Utile pour les tests ou workflows automatisés où l'interaction
    utilisateur n'est pas possible.
    """

    epub_path = Path("input/book.epub")
    output_path = Path("output/book_fr.epub")
    cache_dir = Path("cache")

    llm = LLM(
        model_name="deepseek-chat",
        url="https://api.deepseek.com",
    )

    pipeline = TwoPhasePipeline(
        llm=llm,
        epub_path=epub_path,
        cache_dir=cache_dir,
    )

    # Validation automatique : résout les conflits automatiquement
    stats = pipeline.run(
        target_language=Language.FRENCH,
        output_epub=output_path,
        auto_validate_glossary=True,  # Pas de prompt utilisateur
    )

    print(f"✅ Traduction terminée en {stats['total_duration']:.1f}s")


def example_clear_caches():
    """
    Exemple de nettoyage des caches pour recommencer une traduction.
    """

    epub_path = Path("input/book.epub")
    cache_dir = Path("cache")

    llm = LLM(model_name="deepseek-chat", url="https://api.deepseek.com")
    pipeline = TwoPhasePipeline(llm, epub_path, cache_dir)

    # Supprimer tous les caches (initial, refined, glossaire)
    pipeline.clear_caches()
    print("✅ Caches supprimés")


if __name__ == "__main__":
    # Décommenter l'exemple souhaité

    # Exemple standard avec validation interactive
    main()

    # Exemple avec validation automatique
    # example_auto_validation()

    # Exemple de nettoyage des caches
    # example_clear_caches()
