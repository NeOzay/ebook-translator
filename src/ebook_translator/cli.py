"""Appoints communs aux lignes de commande du paquet.

Chaque commande a deux points d'entrée : un script déclaré en
`[project.scripts]` (`ebook-audit`, `ebook-bench`) et l'invocation par module
(`python -m ebook_translator.audit`). L'aide doit nommer celui que l'utilisateur
a réellement tapé, sinon elle documente une commande qu'il n'a pas lancée — et
sous `-m`, `sys.argv[0]` vaut `__main__.py`, qui n'est le nom d'aucune commande.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ANONYMOUS_ENTRY_POINTS = frozenset({"__main__.py", "-c", ""})
"""Valeurs de `sys.argv[0]` qui ne nomment aucune commande appelable."""


def program_name(module_invocation: str) -> str:
    """Nom sous lequel la commande courante a été appelée.

    Args:
        module_invocation: Forme longue à afficher sous invocation par module,
            par exemple `python -m ebook_translator.audit`.

    Returns:
        Le nom du script appelé, ou `module_invocation` à défaut.

    Example:
        >>> program_name("python -m ebook_translator.audit")  # via ebook-audit
        'ebook-audit'
    """
    invoque = Path(sys.argv[0]).name if sys.argv else ""
    if invoque in _ANONYMOUS_ENTRY_POINTS:
        return module_invocation
    return invoque
