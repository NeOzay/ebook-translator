"""
Test du cas réel rapporté par l'utilisateur.

Ce test vérifie que le résultat final contient bien les espaces manquants
autour des balises imbriquées.
"""

import pytest
from bs4 import BeautifulSoup
from ebook_translator.htmlpage.replacement import TextReplacer
from ebook_translator.htmlpage.bilingual import BilingualFormat


def test_user_reported_case():
    """
    Test du cas exact rapporté :
    HTML original : <p>first balise<b>Restructure Clothing Spell <em>can be used</em> to redesign this outfit.</b></p>

    Résultat attendu :
    - Balise originale stylée en gris
    - Balise traduite avec espaces corrects : "Sort de Restructuration Vestimentaire <em>peut être utilisé</em> pour redessiner cette tenue."
    """
    html = """
    <html>
    <body>
        <p class="noindent">first balise<b>Restructure Clothing Spell <em>can be used</em> to redesign this outfit.</b></p>
    </body>
    </html>
    """

    soup = BeautifulSoup(html, "html.parser")
    replacer = TextReplacer(soup)

    # Trouver la balise <b>
    original_b_tag = soup.find("b")
    assert original_b_tag is not None

    # Styler la balise originale
    replacer.style_original_tag(original_b_tag)

    # Créer une nouvelle balise de traduction
    # Texte traduit avec les 3 fragments :
    # 1. "Restructure Clothing Spell " -> "Sort de Restructuration Vestimentaire "
    # 2. "can be used" -> "peut être utilisé"
    # 3. " to redesign this outfit." -> " pour redessiner cette tenue."
    translated_text = "Sort de Restructuration Vestimentaire</>peut être utilisé</>pour redessiner cette tenue."

    replacer.create_translation_tag_after(original_b_tag, translated_text)

    # Récupérer le résultat final
    result_html = str(soup)

    # Vérifications

    # 1. La balise originale <b> doit avoir la classe "original" et le style gris
    original_tag = soup.find("b", class_="original")
    assert original_tag is not None
    assert original_tag.get("style") == "color: #9ca3af;"

    # 2. La balise de traduction doit exister avec la classe "translation"
    translation_tag = soup.find("b", class_="translation")
    assert translation_tag is not None

    # 3. CRITQUE : Vérifier que les espaces sont présents autour de <em>
    translation_text = str(translation_tag)

    # Doit contenir "Vestimentaire <em>" (espace avant <em>)
    assert "Vestimentaire <em>" in translation_text, f"Espace manquant avant <em>. Got: {translation_text}"

    # Doit contenir "</em> pour" (espace après </em>)
    assert "</em> pour" in translation_text, f"Espace manquant après </em>. Got: {translation_text}"

    # 4. Vérifier le texte complet reconstitué
    expected_translation = "Sort de Restructuration Vestimentaire <em>peut être utilisé</em> pour redessiner cette tenue."

    # Extraire le texte complet de la balise traduite (sans les tags HTML internes)
    full_text = translation_tag.get_text()
    assert full_text == "Sort de Restructuration Vestimentaire peut être utilisé pour redessiner cette tenue."

    # Vérifier la structure HTML complète
    assert "<em>peut être utilisé</em>" in translation_text

    print(f"\nTest reussi !")
    print(f"HTML final :\n{result_html}")


def test_multiple_nested_levels():
    """Test avec plusieurs niveaux d'imbrication."""
    html = """
    <html>
    <body>
        <p><b>Text with <em>emphasis and <strong>strong</strong> text</em> here</b></p>
    </body>
    </html>
    """

    soup = BeautifulSoup(html, "html.parser")
    replacer = TextReplacer(soup)

    original_b_tag = soup.find("b")

    # 4 fragments :
    # "Text with ", "emphasis and ", "strong", " text", " here"
    translated_text = "Texte avec</>emphase et</>fort</>texte</>ici"

    new_tag = soup.new_tag("b")
    replacer.reconstruct_tag_content(new_tag, original_b_tag, translated_text)

    result = str(new_tag)

    # Vérifier les espaces critiques
    assert "avec <em>" in result or "avec<em>" not in result
    assert "et <strong>" in result or "et<strong>" not in result
    assert "</strong> texte" in result or "</strong>texte" not in result
    assert "</em> ici" in result or "</em>ici" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
