"""
Exemple d'utilisation de la Phase 0: Analyse littéraire pré-traduction (version simplifiée).

Ce script montre comment analyser un EPUB avant de le traduire
pour extraire:
- Analyse littéraire (ton, style, thèmes, pistes de traduction)
- Glossaire avec propositions de traduction

Le nouveau format ContexteTraduction réduit de ~67% les tokens LLM
par rapport à l'ancien ChapterAnalysis.

Workflow complet:
  1. Charger EPUB
  2. Exécuter Phase 0 (analyse littéraire simplifiée)
  3. Glossaire peuplé automatiquement depuis l'analyse
  4. (Optionnel) Continuer avec Phase 1 (traduction)

Requirements:
  - DEEPSEEK_API_KEY dans .env
  - Fichier EPUB dans input/
"""

from pathlib import Path

from ebook_translator import LLM, Language, LiteraryAnalysisPhase, Pipeline


def main() -> None:
    """Exécute l'analyse littéraire simplifiée d'un EPUB."""
    # === Configuration ===
    epub_path = Path(
        "books/The Genius Prince's Guide to Raising a Nation Out of Debt - Volume 01 [Yen Press][Kobo].epub"
    )  # Remplacer par votre fichier
    output_epub = Path(f"books/out/[FR] {epub_path.name} test")
    target_language = Language.FRENCH  # Pour propositions de traduction

    # === 1. Initialiser LLM ===
    llm = LLM(
        url="https://api.deepseek.com",
        model_name="deepseek-chat",  # Utilisé pour l'analyse
        reasoning_name="deepseek-reasoner",
        temperature=0.3,  # Analyse structurée (moins de créativité)
    )

    # === 2. Charger EPUB ===
    pipeline = Pipeline(
        llm=llm,
        epub_path=epub_path,
        phases=[LiteraryAnalysisPhase()],
    )  # Pour accéder à PipelineExecutor

    pipeline.run(target_language=target_language, output_epub=output_epub)


if __name__ == "__main__":
    main()
