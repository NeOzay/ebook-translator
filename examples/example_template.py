#!/usr/bin/env python3
"""
Script de test manuel pour visualiser le rendu de chaque template.
Usage: python test_template_manual.py [template_name]
"""

import io
import sys
from enum import Enum
from pathlib import Path

from ebooklib import epub

from ebook_translator.config import PhaseTemplate, RetryTemplate
from ebook_translator.glossary import Glossary
from ebook_translator.llm.template_renderers import TemplateRenderer
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

segmentator = Segmentator(source_book, 500)

chunk = next(segmentator.get_all_segments())
chapter_chunk = next(
    segmentator.get_all_chapters_by_spine()
)  # Premier chapitre pour test

glossary = Glossary()

renderer = TemplateRenderer()

# Templates disponibles avec leurs paramètres par défaut
# === TRANSLATE Templates ===

analyze_first_chunk = renderer.render_analyze_chapter(
    target_language="français", chunk=next(chapter_chunk.split_chunk(100000, 0))
)

analyze_next_chunk = renderer.render_analyze_chapter(
    target_language="français",
    chunk=next(chapter_chunk.split_chunk(100000, 0)),
    partial_analysis_json='{"chapitre": "Chapitre 1: Introduction", "analyse": {"resume_narratif": "Ceci est un résumé narratif du chapitre.", "genre": "fantasy", "pistes_traduction": ["Piste 1: Traduire \'Sakamoto\' par \'Sakamoto\' (nom propre)", "Piste 2: \'Matrice\' peut être traduit par \'Matrix\' ou \'Matrice\', selon le contexte."], "glossaire": [{"terme": "Sakamoto", "type": "personnage", "sexe": "m", "proposition_traduction": "Sakamoto"}, {"terme": "Matrice", "type": "objet", "sexe": "nc", "proposition_traduction": "Matrix ou Matrice"}]}}',
)

translate_base = renderer.render_translate(
    target_language="français",
    source_text="Je suis un texte à traduire.",
    glossary=glossary,
    literary_context=None,
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
    mode="strict",
    original_text="Text with </>separator</>",
    incorrect_translation="Texte </>avec </>séparateur</>",
)

retry_correct_fragments_flexible = renderer.render_retry_fragments(
    target_language="français",
    actual_separators=0,
    expected_separators=2,
    mode="flexible",
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
    chapter_text="Je suis un texte de chapitre à analyser pour en extraire le genre et faire un résumé narratif.",
    incomplete_response='{"analyse": {}, "glossaire": [{"terme": "Sakamoto", "definition": "Un personnage important."}]}',
)

TEMPLATES: list[tuple[Enum | str, str | tuple[str, str]]] = [
    (PhaseTemplate.First_Pass_Template, translate_base),
    (PhaseTemplate.Refine_Template, translate_refine),
    (RetryTemplate.Retry_Missing_Lines_Targeted_Template, retry_translate_missing),
    (RetryTemplate.Retry_Sentence_Template, retry_translate_sentence),
    (RetryTemplate.Retry_Fragments_Template, retry_correct_fragments),
    ("Retry_Fragments_Flexible_Template", retry_correct_fragments_flexible),
    (RetryTemplate.Retry_Punctuation_Template, retry_correct_punctuation),
    (PhaseTemplate.Analyze_Chapter, analyze_first_chunk),
    ("Analyze_Chapter_With_Partial_JSON", analyze_next_chunk),
    (RetryTemplate.Retry_Analysis_Invalid_Json_Template, retry_analysis_invalid_json),
    (
        RetryTemplate.Retry_Analysis_Missing_Sections_Template,
        retry_analysis_missing_sections,
    ),
]


def save_template_output(
    template: tuple[Enum | str, str | tuple[str, str]], output_dir: Path
):
    """Rend un template et sauvegarde la sortie dans un fichier."""

    template_name, prompt = template

    try:
        # Sauvegarder dans un fichier
        output_dir.mkdir(parents=True, exist_ok=True)
        name = template_name.name if isinstance(template_name, Enum) else template_name
        output_file = output_dir / f"{name}_output.txt"
        print(output_file.name)
        with output_file.open("w", encoding="utf-8") as f:
            if isinstance(prompt, tuple):
                f.write("--- SYSTEM ---\n")
                f.write("\n\n--- USER ---\n".join(prompt))
            else:
                f.write(prompt)

        # print(f"✅ Sortie sauvegardée dans: {output_file}")

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
