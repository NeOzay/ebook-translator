"""
Test du systeme de validation de fragments.

Ce script teste validate_fragment_count() et verifie que les workers
detectent correctement les erreurs de fragment mismatch.
"""

from src.ebook_translator.translation.parser import validate_fragment_count


def test_validate_fragment_count_valid():
    """Test avec fragment count correct."""
    original = "Hello</>world"
    translated = "Bonjour</>monde"

    is_valid, error = validate_fragment_count(original, translated)

    assert is_valid, f"Devrait etre valide mais erreur: {error}"
    assert error is None
    print("[OK] Test 1: Fragment count valide")


def test_validate_fragment_count_missing_separator():
    """Test avec separateur manquant."""
    original = "Hello</>world"
    translated = "Bonjour monde"  # Manque le separateur

    is_valid, error = validate_fragment_count(original, translated)

    assert not is_valid, "Devrait etre invalide"
    assert error is not None
    assert "2 fragment(s)" in error  # Expected
    assert "1 fragment(s)" in error  # Actual
    print("[OK] Test 2: Separateur manquant detecte")


def test_validate_fragment_count_extra_separator():
    """Test avec separateur en trop."""
    original = "Hello world"
    translated = "Bonjour</>monde"  # Separateur en trop

    is_valid, error = validate_fragment_count(original, translated)

    assert not is_valid, "Devrait etre invalide"
    assert error is not None
    assert "1 fragment(s)" in error  # Expected
    assert "2 fragment(s)" in error  # Actual
    print("[OK] Test 3: Separateur en trop detecte")


def test_validate_fragment_count_no_separator():
    """Test sans separateur (cas simple)."""
    original = "Hello world"
    translated = "Bonjour monde"

    is_valid, error = validate_fragment_count(original, translated)

    assert is_valid, f"Devrait etre valide mais erreur: {error}"
    assert error is None
    print("[OK] Test 4: Pas de separateur (simple)")


def test_validate_fragment_count_multiple_separators():
    """Test avec plusieurs separateurs."""
    original = "A</>B</>C</>D"
    translated = "W</>X</>Y</>Z"

    is_valid, error = validate_fragment_count(original, translated)

    assert is_valid, f"Devrait etre valide mais erreur: {error}"
    assert error is None
    print("[OK] Test 5: Plusieurs separateurs valides")


def test_validate_fragment_count_one_missing_in_many():
    """Test avec un separateur manquant parmi plusieurs."""
    original = "A</>B</>C</>D"
    translated = "W</>X Y</>Z"  # Manque un separateur

    is_valid, error = validate_fragment_count(original, translated)

    assert not is_valid, "Devrait etre invalide"
    assert error is not None
    assert "4 fragment(s)" in error  # Expected
    assert "3 fragment(s)" in error  # Actual
    print("[OK] Test 6: Un separateur manquant parmi plusieurs detecte")


def test_error_message_format():
    """Test le format du message d'erreur."""
    original = "Fragment 1</>Fragment 2</>Fragment 3"
    translated = "Frag 1 Frag 2"  # Fusion de tous les fragments

    is_valid, error = validate_fragment_count(original, translated)

    assert not is_valid
    assert error is not None

    # Verifier que le message contient les sections attendues
    assert "Nombre de fragments incorrect" in error
    assert "fragments originaux:" in error
    assert "fragments traduits:" in error
    assert "Causes possibles:" in error
    assert "Solutions:" in error
    assert "Fragment 1" in error

    print("[OK] Test 7: Format du message d'erreur complet")

    # Sauvegarder le message dans un fichier pour eviter probleme encodage console
    with open("test_fragment_error_message.txt", "w", encoding="utf-8") as f:
        f.write("Exemple de message d'erreur:\n")
        f.write(error)
    print("Message d'erreur sauvegarde dans test_fragment_error_message.txt")


def main():
    """Lance tous les tests."""
    print("=" * 60)
    print("TEST DU SYSTEME DE VALIDATION DE FRAGMENTS")
    print("=" * 60)
    print()

    try:
        test_validate_fragment_count_valid()
        test_validate_fragment_count_missing_separator()
        test_validate_fragment_count_extra_separator()
        test_validate_fragment_count_no_separator()
        test_validate_fragment_count_multiple_separators()
        test_validate_fragment_count_one_missing_in_many()
        test_error_message_format()

        print()
        print("=" * 60)
        print("TOUS LES TESTS SONT PASSES")
        print("=" * 60)

    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"TEST ECHOUE: {e}")
        print("=" * 60)
        raise


if __name__ == "__main__":
    main()
