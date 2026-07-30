"""
Exemple d'utilisation de la Phase 0: Analyse littéraire pré-traduction (version simplifiée).

Ce script montre comment analyser un EPUB avant de le traduire
pour extraire:
- Analyse littéraire (ton, style, thèmes, pistes de traduction)
- Glossaire avec propositions de traduction

L'analyse est produite en sortie structurée (Instructor) sur le schéma
`AnalyseChapter`, puis mise en cache par chapitre.

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
from ebook_translator.llm.clients.deepseek import Deepseek, DeepseekModels


def main() -> None:
    """Exécute l'analyse littéraire simplifiée d'un EPUB."""
    # === Configuration ===
    epub_path = Path(
        "books/The Genius Prince's Guide to Raising a Nation Out of Debt - Volume 01 [Yen Press][Kobo].epub"
    )  # Remplacer par votre fichier
    output_epub = Path(f"books/out/[FR] {epub_path.name} test")
    target_language = Language.FRENCH  # Pour propositions de traduction

    # === 1. Initialiser LLM ===
    # Le modèle, le mode thinking et la température sont portés par le client.
    llm = LLM(
        client=Deepseek(
            DeepseekModels.FLASH,
            thinking=False,
            config={"temperature": 0.3},  # Analyse structurée, peu de créativité
        )
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
