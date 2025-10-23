"""
Test du nouveau template retry_missing_lines_targeted.jinja
"""

from jinja2 import Environment, FileSystemLoader
from pathlib import Path

# Simuler le cas du log fourni
missing_indices = [27]
error_message = """❌ Nombre de lignes incorrect dans la traduction:
  • Attendu: 28 lignes
  • Reçu: 27 lignes
  • Lignes manquantes: <27/>"""

source_content = """<27/>◇ ◇ ◇

Their protector—the Wolf of Justice."""

target_language = "Francais"

# Charger le template
template_dir = Path(__file__).parent / "template"
env = Environment(loader=FileSystemLoader(template_dir))
template = env.get_template("retry_missing_lines_targeted.jinja")

# Render
prompt = template.render(
    error_message=error_message,
    missing_indices=missing_indices,
    source_content=source_content,
    target_language=target_language,
)

# Sauvegarder dans un fichier au lieu d'afficher (problème encodage Windows)
output_path = Path(__file__).parent / "test_targeted_retry_output.txt"
with open(output_path, "w", encoding="utf-8") as f:
    f.write("=" * 60 + "\n")
    f.write("PROMPT GÉNÉRÉ (NOUVEAU TEMPLATE CIBLÉ)\n")
    f.write("=" * 60 + "\n")
    f.write(prompt + "\n")
    f.write("=" * 60 + "\n\n")
    f.write("✅ Le prompt demande maintenant SEULEMENT de traduire la ligne 27\n")
    f.write("✅ Le LLM devrait répondre : '<27/>◇ ◇ ◇\\n\\nLeur protecteur—le Loup de la Justice.'\n")
    f.write("✅ Au lieu de re-traduire toutes les 28 lignes\n")

print(f"Prompt sauvegarde dans: {output_path}")
print("Verification des elements cles du template...")

# Vérifications
checks = [
    ("Demande seulement lignes manquantes", "UNIQUEMENT les lignes manquantes" in prompt),
    ("Nombre correct (1 ligne)", "Nombre de lignes à traduire** : 1" in prompt),
    ("Conserve l'indice 27", "<27/>" in prompt),
    ("Format de sortie avec indice", "<27/>Texte traduit de la ligne 27" in prompt),
    ("Pas de mention de 28 lignes", "28 lignes" not in prompt.replace("Attendu: 28 lignes", "")),  # Sauf dans error_message
]

all_ok = True
for check_name, result in checks:
    status = "✅" if result else "❌"
    print(f"{status} {check_name}")
    if not result:
        all_ok = False

if all_ok:
    print("\n✅ Tous les checks passent ! Le template est correct.")
else:
    print("\n❌ Certains checks échouent. Vérifier le fichier de sortie.")
