"""Fabrique l'EPUB d'extrait que consomme `bench/config_glossaire_smoke.py`.

`books/` est ignoré par git : l'extrait n'est donc pas versionné, et c'est
précisément ce qui a fait perdre le corpus de la session précédente. Ce script
le régénère depuis le tome complet, pour que la fumée reste reproductible tant
que ce tome est disponible.

Le spine est réduit à un seul chapitre — un chunk de glossaire, donc un appel
LLM par variante — et les illustrations sont retirées : elles ne pèsent sur
rien d'autre que la copie du fichier dans chaque workspace de variante.

Lancement :

    uv run python bench/make_extrait_smoke.py
"""

import re
import zipfile
from pathlib import Path

SERIE = "Chillin' in Another World With Level 2 Super Cheat Powers"
SOURCE = Path(f"books/{SERIE} - Volume 01 [J-Novel Club][Premium].epub")
CIBLE = Path("books/Chillin Vol 01 - extrait chapitre 3_1.epub")

CHAPITRE = "Text/chapter3_1.xhtml"
"""Chapitre retenu.

Choisi pour sa densité terminologique — Flio, Uliminas, Gholl, Balirossa, Rys,
Blossom — qui permet de placer les quatre canaux de réinjection de
`bench/seeds/smoke.toml` sur des termes réellement présents dans le texte.
"""

NAV = "Text/toc.xhtml"
COUVERTURE = "Images/Cover.jpg"


def _reduire_spine(opf: str) -> str:
    """Ne garde dans le spine que le chapitre retenu.

    Args:
        opf: Contenu du manifeste OPF.

    Returns:
        Le manifeste dont le spine ne référence plus qu'un item.

    Raises:
        LookupError: Si le chapitre retenu n'est pas dans le spine.
    """
    href_par_id = dict(re.findall(r'<item id="([^"]+)" href="([^"]+)"', opf))
    idrefs = re.findall(r'<itemref[^>]*idref="([^"]+)"[^>]*/>', opf)
    garde = next((i for i in idrefs if href_par_id.get(i) == CHAPITRE), None)
    if garde is None:
        raise LookupError(f"{CHAPITRE} absent du spine de {SOURCE}")

    return re.sub(
        r"<spine[^>]*>.*?</spine>",
        lambda m: f'{m.group(0).split(">")[0]}><itemref idref="{garde}"/></spine>',
        opf,
        flags=re.DOTALL,
    )


def _elaguer_manifest(opf: str) -> str:
    """Retire du manifeste les documents et images non conservés.

    Args:
        opf: Contenu du manifeste OPF.

    Returns:
        Le manifeste réduit aux ressources effectivement présentes.
    """

    def garder(m: re.Match[str]) -> str:
        ligne, href = m.group(0), m.group(1)
        if href.startswith("Text/"):
            return ligne if href in (CHAPITRE, NAV) else ""
        return ligne if href == COUVERTURE else ""

    return re.sub(
        r'<item id="[^"]+" href="((?:Text|Images)/[^"]+)"[^>]*/>\s*', garder, opf
    )


def construire() -> Path:
    """Écrit l'EPUB d'extrait.

    Returns:
        Le chemin de l'EPUB produit.

    Raises:
        FileNotFoundError: Si le tome source est absent.
    """
    if not SOURCE.exists():
        raise FileNotFoundError(f"tome source introuvable : {SOURCE}")

    with zipfile.ZipFile(SOURCE) as source:
        opf = _elaguer_manifest(
            _reduire_spine(source.read("OEBPS/content.opf").decode("utf8"))
        ).replace("Volume 1</dc:title>", "Volume 1 (extrait)</dc:title>")

        gardes = {f"OEBPS/{CHAPITRE}", f"OEBPS/{NAV}", f"OEBPS/{COUVERTURE}"}
        with zipfile.ZipFile(CIBLE, "w", zipfile.ZIP_DEFLATED) as cible:
            # `mimetype` doit rester le premier membre et non compressé.
            cible.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                zipfile.ZIP_STORED,
            )
            for info in source.infolist():
                nom = info.filename
                if nom == "mimetype" or nom.endswith("/"):
                    continue
                if nom == "OEBPS/content.opf":
                    cible.writestr(info, opf)
                # Les ressources hors texte et images (styles, ncx) suivent
                # sans condition ; le reste passe par la liste des gardes.
                elif not nom.startswith(("OEBPS/Text/", "OEBPS/Images/")) or (
                    nom in gardes
                ):
                    cible.writestr(info, source.read(nom))

    return CIBLE


if __name__ == "__main__":
    cible = construire()
    print(f"écrit : {cible} ({cible.stat().st_size // 1024} Ko)")
