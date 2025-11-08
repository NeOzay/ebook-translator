"""
Exemple d'utilisation de la Phase 0: Analyse littéraire pré-traduction.

Ce script montre comment analyser un EPUB avant de le traduire
pour extraire:
- Personnages, lieux, intrigue
- Thèmes, style, tonalité
- Terminologie spécialisée
- Considérations pour la traduction

Workflow complet:
  1. Charger EPUB
  2. Exécuter Phase 0 (analyse littéraire)
  3. Peupler glossaire automatiquement
  4. Exporter analyses JSON + Markdown
  5. (Optionnel) Continuer avec Phase 1 (traduction)

Requirements:
  - DEEPSEEK_API_KEY dans .env
  - Fichier EPUB dans input/
"""

import logging
from pathlib import Path
from ebooklib import epub

from src.ebook_translator.llm import LLM
from src.ebook_translator.analysis import (
    LiteraryAnalysisPhase,
    GlossaryPopulator,
)
from src.ebook_translator.glossary import Glossary

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    """Exécute l'analyse littéraire d'un EPUB."""
    # === Configuration ===
    epub_path = Path("input/book.epub")  # Remplacer par votre fichier
    output_dir = Path("cache/analysis")
    glossary_path = Path("cache/glossary_phase0.json")

    # Vérifier que le fichier existe
    if not epub_path.exists():
        logger.error(f"Fichier EPUB introuvable: {epub_path}")
        logger.info(
            "Placez votre EPUB dans input/book.epub ou modifiez epub_path dans le script"
        )
        return

    # === 1. Charger EPUB ===
    logger.info(f"Chargement EPUB: {epub_path}")
    book = epub.read_epub(str(epub_path))

    # Extraire les items HTML
    html_items = [item for item in book.get_items() if isinstance(item, epub.EpubHtml)]
    logger.info(f"Trouvé {len(html_items)} fichiers HTML dans l'EPUB")

    # === 2. Initialiser LLM ===
    logger.info("Initialisation du LLM (DeepSeek)...")
    llm = LLM(
        model_name="deepseek-chat",  # Utilisé pour l'analyse
        max_tokens=8000,  # Augmenté pour blocs d'analyse (4000 tokens)
        temperature=0.3,  # Analyse structurée (moins de créativité)
    )

    # === 3. Exécuter Phase 0: Analyse littéraire ===
    logger.info("=" * 80)
    logger.info("Phase 0: Analyse littéraire pré-traduction")
    logger.info("=" * 80)

    phase = LiteraryAnalysisPhase(
        llm=llm,
        html_items=html_items,
        output_dir=output_dir,
        block_tokens=4000,  # Taille des blocs d'analyse
        genre="fiction",  # Adapter selon le genre du livre
    )

    # Exécuter l'analyse (génère JSON + Markdown automatiquement)
    analyses = phase.run()

    logger.info(f"\nAnalyse terminée: {len(analyses)} chapitres analysés")
    logger.info(f"Fichiers générés dans: {output_dir}")

    # === 4. Peupler le glossaire automatiquement ===
    logger.info("\n" + "=" * 80)
    logger.info("Population automatique du glossaire")
    logger.info("=" * 80)

    glossary = Glossary(cache_path=glossary_path)
    populator = GlossaryPopulator(glossary)

    # Extraire termes depuis toutes les analyses
    populator.populate_from_analyses(analyses)

    # Forcer la validation (pour noms propres identiques)
    populator.validate_all_terms()

    # Sauvegarder le glossaire
    glossary.save()

    # Afficher statistiques
    stats = populator.get_stats()
    logger.info(f"\nTermes extraits:")
    logger.info(f"  - Personnages: {stats['characters']}")
    logger.info(f"  - Lieux: {stats['locations']}")
    logger.info(f"  - Noms propres: {stats['proper_nouns']}")
    logger.info(f"  - Termes techniques: {stats['specialized_terms']}")
    logger.info(f"  - Total: {sum(stats.values())} termes")

    logger.info(f"\nGlossaire sauvegardé: {glossary_path}")

    # === 5. Résumé ===
    logger.info("\n" + "=" * 80)
    logger.info("RÉSUMÉ")
    logger.info("=" * 80)

    for chapter_name, analysis in analyses.items():
        logger.info(f"\n{chapter_name}:")
        logger.info(f"  - Status: {analysis['status']}")
        logger.info(
            f"  - Blocs: {analysis['blocks_analyzed']}/{analysis['total_blocks']}"
        )

        # Compter éléments
        num_characters = len(analysis.get("characters", {}).get("present", []))
        num_themes = len(analysis.get("themes", {}).get("identified", []))
        num_specialized = len(
            analysis.get("terminology", {}).get("specialized_terms", [])
        )

        logger.info(f"  - Personnages: {num_characters}")
        logger.info(f"  - Thèmes: {num_themes}")
        logger.info(f"  - Termes spécialisés: {num_specialized}")

    logger.info("\n" + "=" * 80)
    logger.info("Phase 0 terminée avec succès!")
    logger.info("=" * 80)

    logger.info(f"\nProchaines étapes:")
    logger.info(f"  1. Revue manuelle des analyses dans: {output_dir}")
    logger.info(f"  2. Ajustement du glossaire si nécessaire: {glossary_path}")
    logger.info(f"  3. Exécution Phase 1 (traduction) avec example_pipeline.py")


if __name__ == "__main__":
    main()
