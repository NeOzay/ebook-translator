"""
Point d'entrée principal pour le traducteur d'ebooks.

Ce module orchestre le processus complet de traduction d'un EPUB :
1. Charge l'EPUB source
2. Extrait et segmente le contenu
3. Traduit via LLM
4. Reconstruit l'EPUB traduit
"""

import os

from ebook_translator.translation.translator import Language

from .llm import LLM
from .htmlpage import BilingualFormat
from .translation import EpubTranslator


def main() -> None:
    """
    Point d'entrée principal du programme.

    Configure et lance la traduction d'un EPUB.
    Les paramètres peuvent être modifiés via des variables d'environnement :
    - DEEPSEEK_API_KEY : Clé API pour DeepSeek
    - DEEPSEEK_URL : URL de l'API DeepSeek (défaut: https://api.deepseek.com)
    """
    # Configuration du LLM
    api_key = os.getenv("DEEPSEEK_API_KEY", "sk-2500d6f358314b3a8b56478f334ccfc9")
    api_url = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")

    llm = LLM(
        model_name="deepseek-chat",
        log_dir="logs",
        url=api_url,
        api_key=api_key,
        max_tokens=1300,
    )

    # Configuration de la traduction
    source_epub = "Seirei Gensouki - Volume 21 [J-Novel Club][Premium].epub"
    output_epub = "mon_livre_traduit.epub"
    target_language = Language.FRENCH

    # Lancer la traduction
    translator = EpubTranslator(llm, epub_path=source_epub)
    translator.translate(
        target_language=target_language,
        output_epub=output_epub,
        max_concurrent=1,
        bilingual_format=BilingualFormat.INLINE,  # Format bilingue par défaut
    )


if __name__ == "__main__":
    main()
