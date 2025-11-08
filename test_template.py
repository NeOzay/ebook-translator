#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de test manuel pour visualiser le rendu de chaque template.
Usage: python test_template_manual.py [template_name]
"""

import sys
import io
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from typing import Any, TypeVar, TypeAliasType, TypedDict
from src.ebook_translator.llm.template_params import (
    TranslateParams,
    RefineParams,
    MissingLinesParams,
    RetryFragmentsParams,
    RetrySentenceParams,
    RetryPunctuationParams,
    RetryFragmentsFlexibleParams,
)

from src.ebook_translator.config import TemplateNames

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

T = TypeVar("T")
TemplatePair = tuple[TemplateNames, T]

# Templates disponibles avec leurs paramètres par défaut
# === TRANSLATE Templates ===
translate_base: TranslateParams = {"target_language": "français"}


translate_refine: RefineParams = {
    "target_language": "français",
    "glossaire": "- Sakamoto: Sakamoto\n- Matrix: Matrice",
    "original_text": "<0/>Test original text",
    "initial_translation": "<0/>Texte de test traduit",
    "expected_count": 1,
}


retry_translate_missing: MissingLinesParams = {
    "target_language": "français",
    "error_message": "❌ Lignes manquantes: <5/>, <6/>",
    "missing_indices": [5, 6],
    "source_content": "Line 1\nLine 2\nLine 3\nLine 4\n<5/>Line 5\n<6/>Line 6",
}


retry_translate_sentence: RetrySentenceParams = {
    "target_language": "français",
    "missing_indices": "<3/>, <4/>",
    "original_text": "Line 1\nLine 2\n<3/>Original line 3\n<4/>Original line 4",
    "previous_translation": "Line 1\nLine 2\n<3/>Traduction ligne 3\n<4/>Traduction ligne 4",
    "num_lines": 2,
}

# === CORRECT Templates ===
retry_correct_fragments: RetryFragmentsParams = {
    "target_language": "français",
    "original_text": "Text with </>separator</>",
    "incorrect_translation": "Texte avec séparateur",
    "expected_separators": 2,
    "actual_separators": 0,
}

retry_correct_fragments_flexible: RetryFragmentsFlexibleParams = {
    "target_language": "français",
    "original_text": "Text with </>separator</>",
    "incorrect_translation": "Texte avec séparateur",
    "expected_separators": 2,
    "actual_separators": 0,
}

retry_correct_punctuation: RetryPunctuationParams = {
    "target_language": "français",
    "original_text": '"Hello," she said, "world"',
    "incorrect_translation": "« Bonjour, dit-elle, monde »",
    "expected_pairs": 2,
    "actual_pairs": 1,
}


TEMPLATES: dict[TemplateNames, Any] = {
    TemplateNames.First_Pass_Template: translate_base,
    TemplateNames.Refine_Template: translate_refine,
    TemplateNames.Retry_Missing_Lines_Targeted_Template: retry_translate_missing,
    TemplateNames.Retry_Sentence_Template: retry_translate_sentence,
    TemplateNames.Retry_Fragments_Template: retry_correct_fragments,
    TemplateNames.Retry_Fragments_Flexible_Template: retry_correct_fragments_flexible,
    TemplateNames.Retry_Punctuation_Template: retry_correct_punctuation,
}


def list_templates():
    """Affiche la liste des templates disponibles."""
    print("\n📋 Templates disponibles:\n")
    print("TRANSLATE Templates:")
    for name, info in TEMPLATES.items():
        if "translate" in name:
            print(f"  - {name.name:<30} ({name.value})")

    print("\nCORRECT Templates:")
    for name, info in TEMPLATES.items():
        if "correct" in name:
            print(f"  - {name.name:<30} ({name.value})")
    print()


def render_template(template_name: TemplateNames):
    """Rend un template avec ses paramètres par défaut."""
    if template_name not in TEMPLATES:
        print(f"❌ Template '{template_name}' inconnu.")
        list_templates()
        return

    params = TEMPLATES[template_name]
    template_file = template_name.value

    # Charger le template
    template_dir = Path(__file__).parent / "template"
    env = Environment(loader=FileSystemLoader(template_dir))

    try:
        template = env.get_template(template_file)
        rendered = template.render(**params)

        # Afficher les informations
        print(f"\n{'='*80}")
        print(f"📝 Template: {template_name}")
        print(f"📄 Fichier: {template_file}")
        print(f"{'='*80}\n")

        print(f"🔧 Paramètres utilisés:")
        for key, value in params.items():
            value_preview = (
                str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
            )
            print(f"  - {key}: {value_preview}")

        print(f"\n📊 Statistiques:")
        print(f"  - Longueur: {len(rendered)} caractères")
        print(f"  - Lignes: {rendered.count(chr(10)) + 1}")

        # Vérifier que le template commun est inclus
        has_common = "Règles de traduction" in rendered or "Correction" in rendered
        print(f"  - Inclut règles communes: {'✅ Oui' if has_common else '⚠️  Non'}")

        print(f"\n{'='*80}")
        print("📄 RENDU DU PROMPT:")
        print(f"{'='*80}\n")
        print(rendered)
        print(f"\n{'='*80}")
        print(f"✅ Template rendu avec succès!")
        print(f"{'='*80}\n")

    except Exception as e:
        print(f"\n❌ ERREUR lors du rendu:")
        print(f"   {type(e).__name__}: {e}\n")
        import traceback

        traceback.print_exc()


def save_template_output(template_name: TemplateNames, output_dir: Path):
    """Rend un template et sauvegarde la sortie dans un fichier."""
    if template_name not in TEMPLATES:
        print(f"❌ Template '{template_name}' inconnu.")
        list_templates()
        return

    params = TEMPLATES[template_name]
    template_file = template_name.value

    # Charger le template
    template_dir = Path(__file__).parent / "template"
    env = Environment(loader=FileSystemLoader(template_dir))

    try:
        template = env.get_template(template_file)
        rendered = template.render(**params)

        # Sauvegarder dans un fichier
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{template_name.name}_output.txt"
        with output_file.open("w", encoding="utf-8") as f:
            f.write(rendered)

        print(f"✅ Sortie sauvegardée dans: {output_file}")

    except Exception as e:
        print(f"\n❌ ERREUR lors du rendu:")
        print(f"   {type(e).__name__}: {e}\n")
        import traceback

        traceback.print_exc()


def main():
    for name, value in TEMPLATES.items():
        # render_template(name)
        save_template_output(name, Path("./template_outputs"))


if __name__ == "__main__":
    main()
