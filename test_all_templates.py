#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test tous les templates rapidement."""
import subprocess
import sys
import io

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

TEMPLATES = [
    "translate_base",
    "translate_refine",
    "retry_translate_missing",
    "retry_translate_sentence",
    "retry_correct_fragments",
    "retry_correct_fragments_flexible",
    "retry_correct_punctuation",
]

def test_all():
    """Teste tous les templates et affiche un résumé."""
    print("\n🧪 TEST DE TOUS LES TEMPLATES\n")
    print("="*80)

    results = []

    for template in TEMPLATES:
        print(f"\n📝 Test: {template}...")
        try:
            result = subprocess.run(
                [sys.executable, "test_template_manual.py", template],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                # Extraire les stats
                output = result.stdout
                length = output.split("Longueur: ")[1].split(" ")[0] if "Longueur:" in output else "?"
                has_common = "✅ Oui" in output

                results.append({
                    "name": template,
                    "status": "✅",
                    "length": length,
                    "has_common": has_common
                })
                print(f"   ✅ OK ({length} chars)")
            else:
                results.append({
                    "name": template,
                    "status": "❌",
                    "error": result.stderr[:100]
                })
                print(f"   ❌ ERREUR")

        except Exception as e:
            results.append({
                "name": template,
                "status": "❌",
                "error": str(e)
            })
            print(f"   ❌ EXCEPTION: {e}")

    # Afficher le résumé
    print("\n" + "="*80)
    print("📊 RÉSUMÉ DES TESTS")
    print("="*80 + "\n")

    success = sum(1 for r in results if r["status"] == "✅")
    total = len(results)

    for result in results:
        name = result["name"]
        status = result["status"]
        if status == "✅":
            length = result["length"]
            common = "✅" if result["has_common"] else "⚠️ "
            print(f"{status} {name:<35} {length:>6} chars  [Common: {common}]")
        else:
            print(f"{status} {name:<35} ERREUR")

    print(f"\n{'='*80}")
    print(f"Résultat: {success}/{total} templates OK")
    print(f"{'='*80}\n")

    return success == total

if __name__ == "__main__":
    success = test_all()
    sys.exit(0 if success else 1)
