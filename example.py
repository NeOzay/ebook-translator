"""
Script de configuration pour la traduction d'ebooks.

Ce script est un exemple de configuration personnalisée.
Vous pouvez le copier et modifier les paramètres selon vos besoins :
- Fichier EPUB source et destination
- Langue cible
- Format bilingue
- Niveau de concurrence
- Modèle LLM

Pour utiliser :
1. Copiez ce fichier : cp start.py my_translation.py
2. Modifiez les paramètres dans my_translation.py
3. Exécutez : python my_translation.py
"""

from pathlib import Path
from ebook_translator import Language
from ebook_translator import LLM, BilingualFormat, EpubTranslator


def main() -> None:
    """
    Configure et lance la traduction d'un EPUB.

    Les paramètres sont définis directement dans ce script.
    Modifiez-les selon vos besoins.
    """
    # ============================================================
    # CONFIGURATION - Modifiez ces valeurs selon vos besoins
    # ============================================================

    # Fichiers EPUB
    source_epub = Path(
        "books/Chillin' in Another World With Level 2 Super Cheat Powers - Volume 01 [J-Novel Club][Premium].epub"
    )
    output_epub = Path(f"books/out/[FR] {source_epub.name}")

    # Langue cible
    target_language = Language.FRENCH

    # Format de sortie
    # - BilingualFormat.INLINE : Original et traduction dans le même paragraphe
    # - BilingualFormat.SEPARATE_TAG : Original et traduction en paragraphes séparés
    # - BilingualFormat.DISABLE : Remplace complètement l'original
    bilingual_format = BilingualFormat.SEPARATE_TAG

    # Nombre de traductions parallèles (1 = séquentiel, >1 = parallèle)
    max_concurrent = 1

    # Modèle LLM (compatible OpenAI)
    model_name = "deepseek-chat"
    api_url = "https://api.deepseek.com"
    api_key = None  # Utilise la clé de .env si None
    max_tokens = 1300

    # ============================================================
    # INITIALISATION DU LLM
    # ============================================================
    llm = LLM(
        model_name=model_name,
        url=api_url,
        api_key=api_key,
        temperature=0.85,
    )

    # ============================================================
    # TRADUCTION
    # ============================================================
    print(f"\n📚 Source : {source_epub}")
    print(f"🎯 Langue : {target_language.value}")
    print(f"💾 Sortie : {output_epub}")
    print(f"🤖 Modèle : {model_name}")
    print(f"⚡ Concurrence : {max_concurrent}\n")

    translator = EpubTranslator(llm, epub_path=source_epub)
    translator.translate(
        target_language=target_language,
        output_epub=output_epub,
        max_concurrent=max_concurrent,
        bilingual_format=bilingual_format,
        user_prompt=None,
        max_correction_retries=1,
        max_tokens=max_tokens,
    )


if __name__ == "__main__":
    main()
