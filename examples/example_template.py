#!/usr/bin/env python3
"""
Script de test manuel pour visualiser le rendu de chaque template.
Usage: python test_template_manual.py [template_name]
"""

import io
import sys
from pathlib import Path

from ebooklib import epub
from src.ebook_translator.config import TemplateNames
from src.ebook_translator.llm.template_renderers import TemplateRenderer

from ebook_translator.glossary import Glossary
from ebook_translator.segmentation.segmentator import Segmentator
from ebook_translator.stores.store import Store
from ebook_translator.translation.epub_handler import extract_html_items_in_spine_order

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


source_epub = Path(
    "books/The Genius Prince's Guide to Raising a Nation Out of Debt - Volume 01 [Yen Press][Kobo].epub"
)
source_book = epub.read_epub(source_epub)  # type: ignore
html_items, target_book = extract_html_items_in_spine_order(source_book)

segmentator = Segmentator(html_items, 500)

chunk = next(segmentator.get_all_segments())

glossary = Glossary()

renderer = TemplateRenderer()

# Templates disponibles avec leurs paramètres par défaut
# === TRANSLATE Templates ===

analyze_simplified = renderer.render_analyze_simplified(
    chapter_name="Chapitre 1: Introduction",
    target_language="français",
)


translate_base = renderer.render_translate(
    target_language="français",
)

try:
    translate_refine = renderer.render_refine(
        target_language="français",
        chunk=chunk,
        glossary=glossary,
        store=Store(Path("./store")),
        # original_text="<0/>Test original text",
        # initial_translation="<0/>Texte de test traduit",
        # glossaire="- Sakamoto: Sakamoto\n- Matrix: Matrice",
        # expected_count=1,
    )
except Exception as e:
    print(f"Erreur lors du rendu de translate_refine: {e}")
    translate_refine = "ERREUR DE RENDU"

retry_translate_missing = renderer.render_missing_lines(
    chunk=chunk,
    target_language="français",
    missing_indices=[5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
)


retry_translate_sentence = renderer.render_retry_sentence(
    chunk=chunk,
    target_language="français",
    missing_indices=[3, 4],
)


# === CORRECT Templates ===

retry_correct_fragments = renderer.render_retry_fragments(
    target_language="français",
    actual_separators=3,
    expected_separators=2,
    mode="NORMAL",
    original_text="Text with </>separator</>",
    incorrect_translation="Texte avec séparateur",
)

retry_correct_fragments_flexible = renderer.render_retry_fragments(
    target_language="français",
    actual_separators=0,
    expected_separators=2,
    mode="FLEXIBLE",
    original_text="Text with </>separator</>",
    incorrect_translation="Texte avec séparateur",
)

retry_correct_punctuation = renderer.render_retry_punctuation(
    target_language="français",
    original_text='"Hello," she said, "world"',
    incorrect_translation="« Bonjour, dit-elle, monde »",
    expected_pairs=2,
    actual_pairs=1,
)


retry_analysis_invalid_json = renderer.render_retry_analysis_invalid_json(
    chapter_name="Chapitre 1: Introduction",
    target_language="français",
    json_error_message="Erreur de syntaxe JSON à la ligne 3",
    invalid_response='{"analyse": {"resume_narratif": "Ceci est un résumé"',
)

retry_analysis_missing_sections = renderer.render_retry_analysis_missing_sections(
    chapter_name="Chapitre 1: Introduction",
    target_language="français",
    missing_sections=["analyse.resume_narratif", "glossaire[0].sexe"],
)

TEMPLATES: dict[TemplateNames, str] = {
    TemplateNames.First_Pass_Template: translate_base,
    TemplateNames.Refine_Template: translate_refine,
    TemplateNames.Retry_Missing_Lines_Targeted_Template: retry_translate_missing,
    TemplateNames.Retry_Sentence_Template: retry_translate_sentence,
    TemplateNames.Retry_Fragments_Template: retry_correct_fragments,
    TemplateNames.Retry_Fragments_Flexible_Template: retry_correct_fragments_flexible,
    TemplateNames.Retry_Punctuation_Template: retry_correct_punctuation,
    TemplateNames.Analyze_Simplified_Template: analyze_simplified,
    TemplateNames.Retry_Analysis_Invalid_Json_Template: retry_analysis_invalid_json,
    TemplateNames.Retry_Analysis_Missing_Sections_Template: retry_analysis_missing_sections,
}


def save_template_output(template_name: TemplateNames, output_dir: Path):
    """Rend un template et sauvegarde la sortie dans un fichier."""
    if template_name not in TEMPLATES:
        print(f"❌ Template '{template_name}' inconnu.")
        return

    prompt = TEMPLATES[template_name]

    try:
        # Sauvegarder dans un fichier
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{template_name.name}_output.txt"
        with output_file.open("w", encoding="utf-8") as f:
            f.write(prompt)

        print(f"✅ Sortie sauvegardée dans: {output_file}")

    except Exception as e:
        print("\n❌ ERREUR lors du rendu:")
        print(f"   {type(e).__name__}: {e}\n")
        import traceback

        traceback.print_exc()


def main():
    for name in TEMPLATES:
        # render_template(name)
        save_template_output(name, Path("./template_outputs"))


if __name__ == "__main__":
    main()
