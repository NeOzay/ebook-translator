"""
Script de test pour valider le support de overlap_ratio > 1.0 dans Segmentator.

Ce script teste différents ratios d'overlap pour vérifier que :
1. Le système gère correctement overlap_ratio < 1.0 (cas standard)
2. Le système gère correctement overlap_ratio >= 1.0 (contexte étendu)
3. Les chunks sont bien yielded dans l'ordre correct
4. Le contexte se propage correctement sur plusieurs chunks
"""

from ebooklib import epub
from src.ebook_translator.segment import Segmentator
from src.ebook_translator.htmlpage import HtmlPage


def create_mock_epub_html(content: str, file_name: str) -> epub.EpubHtml:
    """Crée un fichier EPUB HTML mock pour les tests."""
    item = epub.EpubHtml(
        title=file_name,
        file_name=file_name,
        lang='en',
    )
    item.content = content.encode('utf-8')
    return item


def test_overlap_ratio(overlap_ratio: float, max_tokens: int = 100):
    """
    Teste le Segmentator avec un ratio d'overlap donné.

    Args:
        overlap_ratio: Le ratio d'overlap à tester
        max_tokens: Limite de tokens par chunk
    """
    print(f"\n{'='*80}")
    print(f"TEST: overlap_ratio={overlap_ratio:.1f}, max_tokens={max_tokens}")
    print(f"{'='*80}")

    # Créer un contenu HTML mock avec plusieurs paragraphes
    # Chaque paragraphe fait environ 20-25 tokens
    html_content = """
    <html>
    <body>
        <p>First paragraph with some text to make it longer for proper chunking and testing purposes.</p>
        <p>Second paragraph with more text to fill the chunk and ensure we have multiple chunks for testing.</p>
        <p>Third paragraph to test chunking behavior with different overlap ratios and validate the queue system.</p>
        <p>Fourth paragraph for overlap testing with extended context to see how head and tail are managed.</p>
        <p>Fifth paragraph to see context propagation across multiple chunks in the queue system implementation.</p>
        <p>Sixth paragraph for extended overlap testing with very large ratios greater than one point zero.</p>
        <p>Seventh paragraph to validate queue system behavior when overlap budget exceeds the max tokens limit.</p>
        <p>Eighth paragraph for final testing of the segmentation algorithm with various overlap configurations.</p>
        <p>Ninth paragraph to ensure proper yielding order and prevent duplicate chunk generation in edge cases.</p>
        <p>Tenth paragraph for comprehensive validation of the entire segmentation pipeline and overlap mechanism.</p>
    </body>
    </html>
    """

    epub_html = create_mock_epub_html(html_content, "test.xhtml")

    # Créer le segmentator
    segmentator = Segmentator(
        epub_htmls=[epub_html],
        max_tokens=max_tokens,
        overlap_ratio=overlap_ratio,
    )

    print(f"\n{segmentator}")
    print(f"\nOverlap tokens: {segmentator._calculate_overlap_tokens()}")
    print(f"\n{'-'*80}")

    # Générer les chunks
    chunks = list(segmentator.get_all_segments())

    print(f"\nNombre total de chunks: {len(chunks)}")
    print(f"\n{'-'*80}")

    # Afficher les détails de chaque chunk
    for chunk in chunks:
        print(f"\nChunk {chunk.index}:")
        print(f"   - Body items: {len(chunk.body)}")
        print(f"   - Head items: {len(chunk.head)}")
        print(f"   - Tail items: {len(chunk.tail)}")

        # Calculer les tokens approximatifs
        body_tokens = sum(segmentator.count_tokens(text) for text in chunk.body.values())
        head_tokens = sum(segmentator.count_tokens(text) for text in chunk.head)
        tail_tokens = sum(segmentator.count_tokens(text) for text in chunk.tail)

        print(f"   - Body tokens: ~{body_tokens}")
        print(f"   - Head tokens: ~{head_tokens}")
        print(f"   - Tail tokens: ~{tail_tokens}")

        # Afficher le contenu (tronqué)
        if chunk.head:
            print(f"   - Head preview: {chunk.head[0][:50]}...")
        if chunk.body:
            first_body = list(chunk.body.values())[0]
            print(f"   - Body preview: {first_body[:50]}...")
        if chunk.tail:
            print(f"   - Tail preview: {chunk.tail[0][:50]}...")


def main():
    """Fonction principale pour lancer tous les tests."""
    print("\n" + "="*80)
    print("TESTS DE VALIDATION DU SYSTÈME D'OVERLAP")
    print("="*80)

    # Test 1 : Overlap standard (15%)
    test_overlap_ratio(overlap_ratio=0.15, max_tokens=100)

    # Test 2 : Overlap modéré (50%)
    test_overlap_ratio(overlap_ratio=0.5, max_tokens=100)

    # Test 3 : Overlap à 100% (contexte = body)
    test_overlap_ratio(overlap_ratio=1.0, max_tokens=100)

    # Test 4 : Overlap étendu (150%)
    test_overlap_ratio(overlap_ratio=1.5, max_tokens=100)

    # Test 5 : Overlap très étendu (200%)
    test_overlap_ratio(overlap_ratio=2.0, max_tokens=100)

    # Test 6 : Overlap extrême (300%)
    test_overlap_ratio(overlap_ratio=3.0, max_tokens=100)

    print("\n" + "="*80)
    print("TOUS LES TESTS TERMINES")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
