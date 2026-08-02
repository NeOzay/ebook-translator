"""
Détection de chapitres par parcours séquentiel de la spine EPUB.

Amélioration majeure vs chapter_detector.py (607 lignes, 4 passes) :
- 1 seule passe séquentielle (O(n) vs O(4n))
- Décisions basées sur CONTEXTE (fichiers précédents)
- Résout l'ambiguïté chapter11 : après chapter10 → 11, après chapter1 → 1.1
- ~50% moins de code (300 vs 607 lignes)
- Patterns flexibles (chapter_1, chapter-01, ch_001)

Architecture:
  Machine à états finie (FSM) avec contexte maintenu pendant parcours.
  Chaque fichier est analysé EN TENANT COMPTE des fichiers précédents.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from ebooklib import epub

from ebook_translator.constants import (
    BACK_MATTER_KEYWORDS,
    FRONT_MATTER_KEYWORDS,
    SKIP_KEYWORDS,
)

from ..logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class _FileType(Enum):
    """Types de fichiers détectés pendant le parcours."""

    MAIN_CHAPTER = auto()  # Chapitre principal (chapter1, chapter2, ...)
    SUBPART = auto()  # Sous-partie (chapter11 après chapter1)
    INSERT = auto()  # Insert/interlude entre chapitres
    FRONT_MATTER = auto()  # Front matter (preface, dedication, ...)
    BACK_MATTER = auto()  # Back matter (afterword, appendix, ...)
    SKIP = auto()  # À ignorer (cover, toc, copyright, ...)


@dataclass
class _ChapterContext:
    """
    Contexte maintenu pendant le parcours séquentiel de la spine.

    Ce contexte permet de prendre des décisions basées sur l'HISTORIQUE
    au lieu de règles regex rigides.

    Utilise un système de tracking générique par nom pour supporter
    des types de chapitres découverts dynamiquement (chapter, intermission,
    interlude, prologue, epilogue, etc.) avec numérotation indépendante.
    """

    current_chapter_num: int | None = None
    """Numéro du chapitre actuel"""

    current_chapter_name: str = ""
    """Nom du chapitre actuel (ex: 'Chapter 1', 'Prologue')"""

    current_files: list[epub.EpubHtml] = field(default_factory=list[epub.EpubHtml])
    """Fichiers HTML du chapitre actuel"""

    index_by_name: dict[str, int] = field(default_factory=dict[str, int])
    """
    Tracking générique du dernier numéro vu par type de nom.

    Exemples:
      {"chapter": 5, "intermission": 2, "interlude": 1, "prologue": 1}

    Permet numérotation indépendante: chapter5, intermission2, chapter6, intermission3
    """

    chapter_index: int = 0
    """Index global du chapitre (0, 1, 2, ...)"""


@dataclass
class _FileAnalysis:
    """
    Résultat de l'analyse d'un fichier.

    Contient la décision prise (type, nouveau chapitre ou non)
    et la justification pour debugging.
    """

    file_type: _FileType
    """Type de fichier détecté"""

    name: str

    chapter_num: int | None = None
    """Numéro de chapitre extrait (si applicable)"""

    is_new_chapter: bool = False
    """True si ce fichier démarre un NOUVEAU chapitre"""

    toc_title: str | None = None
    """Titre issu du TOC EPUB (si disponible)"""

    reason: str = ""
    """Justification de la décision (pour debugging/logging)"""


@dataclass(kw_only=True)
class ChapterInfo:
    """
    Représente un groupe de fichiers HTML formant un chapitre.
    """

    index: int
    name: str
    files: list[epub.EpubHtml]

    @property
    def file_names(self) -> list[str]:
        """Retourne la liste des noms de fichiers."""
        return [html.get_name() for html in self.files]


@dataclass(kw_only=True)
class SequentialDetectorConfig:
    """Configuration pour le détecteur séquentiel."""

    include_front_matter: bool = False
    """Inclure front matter (preface, dedication, etc.) comme chapitres"""

    include_back_matter: bool = False
    """Inclure back matter (afterword, appendix, bonus) comme chapitres"""

    subpart_threshold: int = 5
    """Seuil pour détecter subparts : num > last + threshold → probablement subpart"""


def extract_toc_map(toc: list[Any]) -> dict[str, str]:
    """Extrait un mapping {normalized_filename: chapter_title} depuis book.toc.

    Normalisation : basename lowercase sans extension ni ancre (#s1).
    Supporte epub.Link et (epub.Section, children) récursivement.

    Args:
        toc: Table des matières EPUB (book.toc)

    Returns:
        Mapping {normalized_filename: title}
    """
    result: dict[str, str] = {}
    for entry in toc:
        if isinstance(entry, epub.Link):
            href = entry.href.split("#")[0].split("/")[-1]
            for ext in (".html", ".xhtml"):
                href = href.replace(ext, "")
            result[href.lower()] = entry.title
        elif isinstance(entry, tuple):  # (epub.Section, children)
            section, children = entry  # pyright: ignore[reportUnknownVariableType]
            if isinstance(section, epub.Link):
                href = section.href.split("#")[0].split("/")[-1]  # pyright: ignore[reportUnknownMemberType]
                for ext in (".html", ".xhtml"):
                    href = href.replace(ext, "")
                result[href.lower()] = section.title  # pyright: ignore[reportUnknownMemberType]
            ch: list[Any] = list(children)  # pyright: ignore[reportUnknownArgumentType]
            result.update(extract_toc_map(ch))
    return result


class SequentialChapterDetector:
    """
    Détecteur de chapitres par parcours séquentiel de la spine.

    Algorithme en 1 passe :
    1. Parcourt la spine dans l'ordre
    2. Pour chaque fichier : analyse avec CONTEXTE (fichiers précédents)
    3. Décide : nouveau chapitre / subpart / insert
    4. Yield les chapitres au fur et à mesure

    Avantages:
    - **Robustesse** : Résout chapter11 contextuellement (après 10 → 11, après 1 → 1.1)
    - **Performance** : 1 passe vs 4 (4× plus rapide théoriquement)
    - **Simplicité** : ~300 lignes vs 607, logique centralisée
    - **Flexibilité** : Patterns génériques (chapter_1, chapter-01, ch_001)

    Example:
        >>> detector = SequentialChapterDetector(epub.items)
        >>> for chapter_info in detector.detect_chapters():
        ...     print(f"{chapter_info.name}: {len(chapter_info.files)} fichiers")
    """

    def __init__(
        self,
        epub_htmls: list[epub.EpubHtml],
        config: SequentialDetectorConfig | None = None,
        toc_map: dict[str, str] | None = None,
    ):
        """
        Initialise le détecteur séquentiel.

        Args:
            epub_htmls: Liste des fichiers HTML de l'EPUB (dans l'ordre de la spine)
            config: Configuration optionnelle
            toc_map: Mapping {normalized_filename: title} issu du TOC EPUB.
                     Si fourni, utilisé comme source authoritative de chapitrage.
        """
        self.epub_htmls = epub_htmls
        self.config = config or SequentialDetectorConfig()
        self.toc_map = toc_map
        self.context = _ChapterContext()
        self.empty_name_index = 0

    def detect_chapters(self) -> Iterator[ChapterInfo]:
        """
        Parcours séquentiel de la spine avec décisions contextuelles.

        Yields:
            ChapterInfo pour chaque chapitre détecté
        """
        logger.info(
            f"🔍 Détection séquentielle pour {len(self.epub_htmls)} fichiers HTML"
        )

        for spine_index, html in enumerate(self.epub_htmls):
            filename = self._normalize_filename(html.get_name())

            # Analyser AVEC contexte (clé de la robustesse)
            analysis = self._analyze_with_context(filename, spine_index)

            # Décider action
            if analysis.is_new_chapter:
                # Yield chapitre précédent si existant
                if self.context.current_files:
                    yield self._create_chapter_info()

                # Démarrer nouveau chapitre
                self.context.current_chapter_num = analysis.chapter_num
                self.context.current_chapter_name = self._make_chapter_name(analysis)
                self.context.current_files = [html]

                logger.debug(
                    f"Nouveau chapitre : {self.context.current_chapter_name} "
                    f"({filename}) - {analysis.reason}"
                )

            elif analysis.file_type in [_FileType.SUBPART, _FileType.INSERT]:
                # Ajouter au chapitre courant
                if self.context.current_files:
                    self.context.current_files.append(html)
                    logger.debug(
                        f"  → Ajout à {self.context.current_chapter_name} : "
                        f"{filename} - {analysis.reason}"
                    )
                else:
                    # Cas rare : subpart/insert sans chapitre parent
                    logger.warning(
                        f"SUBPART/INSERT sans chapitre parent : {filename}, "
                        f"traité comme nouveau chapitre"
                    )
                    self.context.current_chapter_num = analysis.chapter_num
                    self.context.current_chapter_name = self._make_chapter_name(
                        analysis
                    )
                    self.context.current_files = [html]

            elif analysis.file_type == _FileType.SKIP:
                # Ignorer
                logger.debug(f"Ignoré : {filename} - {analysis.reason}")

        # Yield dernier chapitre
        if self.context.current_files:
            yield self._create_chapter_info()

        logger.info(f"✅ {self.context.chapter_index} chapitres détectés")

    def _analyze_with_context(self, filename: str, spine_index: int) -> _FileAnalysis:
        """
        Analyse un fichier EN TENANT COMPTE DU CONTEXTE.

        C'est ici que se trouve la logique clé qui résout les ambiguïtés
        comme chapter11 (chapitre 11 vs chapitre 1 partie 1).

        Args:
            filename: Nom de fichier normalisé
            spine_index: Position dans la spine (pour logging)

        Returns:
            FileAnalysis avec décision et justification
        """
        name, chapter_num = self._extract_filename_and_chapter_number(filename)

        # Priorité 1 : SKIP (cover, toc, copyright)
        if re.search(SKIP_KEYWORDS, name):
            return _FileAnalysis(
                _FileType.SKIP, name=filename, reason="Fichier système"
            )

        # Priorité 2 : FRONT_MATTER
        if re.search(FRONT_MATTER_KEYWORDS, name):
            if self.config.include_front_matter:
                return _FileAnalysis(
                    _FileType.FRONT_MATTER,
                    name=name,
                    chapter_num=0,
                    is_new_chapter=True,
                    reason="Front matter",
                )
            else:
                return _FileAnalysis(
                    _FileType.SKIP, name=filename, reason="Front matter (ignoré)"
                )

        # Priorité 3 : BACK_MATTER
        if re.search(BACK_MATTER_KEYWORDS, name):
            if self.config.include_back_matter:
                return _FileAnalysis(
                    _FileType.BACK_MATTER,
                    name=name,
                    chapter_num=999,
                    is_new_chapter=True,
                    reason="Back matter",
                )
            else:
                return _FileAnalysis(
                    _FileType.SKIP, name=name, reason="Back matter (ignoré)"
                )

        # Priorité 4 : TOC (source authoritative quand disponible)
        # `filename` est le basename normalisé (pas de chemin, pas d'ext, minuscule)
        if self.toc_map is not None:
            toc_title = self.toc_map.get(filename)
            if toc_title is not None:
                return _FileAnalysis(
                    _FileType.MAIN_CHAPTER,
                    name=filename,
                    toc_title=toc_title,
                    is_new_chapter=True,
                    reason=f"TOC: {toc_title!r}",
                )
            return _FileAnalysis(
                _FileType.SUBPART,
                name=filename,
                is_new_chapter=False,
                reason="Non répertorié dans le TOC",
            )

        # Priorité 5 : INSERT (insert)
        if re.search(r"(insert)", name):
            return _FileAnalysis(
                _FileType.INSERT,
                name=name,
                is_new_chapter=False,
                reason="Insert/interlude détecté",
            )

        # Priorité 6 : CHAPITRE numéroté (décision contextuelle)
        return self._decide_with_context(name, chapter_num)

    def _decide_with_context(self, name: str, num: int | None) -> _FileAnalysis:
        """
        Décide si un fichier démarre un nouveau chapitre ou est une subpart.

        UTILISE LE CONTEXTE (chapters_by_name) pour résoudre les ambiguïtés
        avec tracking générique par nom (chapter, intermission, interlude, etc.).

        Exemples :
        - chapter11 après chapter10 → CHAPITRE 11 (séquence naturelle)
        - chapter11 après chapter1  → CHAPITRE 1 PARTIE 1 (subpart)
        - chapter1_a après chapter1 → SUBPART (même numéro)
        - intermission2 après intermission1 → INTERMISSION 2 (séquence indépendante)
        - interlude1 après chapter5 → INTERLUDE 1 (nouveau type, numérotation indépendante)

        Args:
            name: Nom de base extrait (ex: "chapter", "intermission", "interlude")
            num: Numéro extrait ou None si absent

        Returns:
            FileAnalysis avec décision contextuelle
        """
        last_index = self.context.index_by_name.get(name)
        last_name = self.context.current_chapter_name

        # Cas spécial : Pas de numéro détecté (ex: "intermission" sans numéro)
        if num is None:
            return _FileAnalysis(
                _FileType.MAIN_CHAPTER,
                name=name,
                is_new_chapter=True,
                reason=f"Nouveau chapitre '{name}' sans numéro",
            )

        # Cas où le même nom de chapitre sans numéro est répété
        if last_name == name and not last_index:
            return _FileAnalysis(
                _FileType.SUBPART,
                name=name,
                chapter_num=None,
                is_new_chapter=False,
                reason=f"Sous-partie répétée '{name}' sans numéro",
            )

        # Cas 1 : Premier chapitre de ce type (ex: premier "intermission1")
        if last_index is None:
            self.context.index_by_name[name] = num
            return _FileAnalysis(
                _FileType.MAIN_CHAPTER,
                name=name,
                chapter_num=num,
                is_new_chapter=True,
                reason=f"Premier '{name}' (numérotation indépendante)",
            )

        # Cas 2 : Séquence naturelle (last=10, num=11)
        if num == last_index + 1:
            self.context.index_by_name[name] = num
            return _FileAnalysis(
                _FileType.MAIN_CHAPTER,
                name=name,
                chapter_num=num,
                is_new_chapter=True,
                reason=f"Séquence naturelle '{name}' ({last_index} → {num})",
            )

        # Cas 3 : Même numéro (last=1, num=1) → SUBPART
        if num == last_index:
            return _FileAnalysis(
                _FileType.SUBPART,
                name=name,
                chapter_num=last_index,
                is_new_chapter=False,
                reason=f"Sous-partie '{name} {num}'",
            )

        # Cas 4 : Numéro commence par last (last=1, num=11/12/13)
        # → Potentiellement subpart si num est "trop loin" de last+1
        if (
            str(num).startswith(str(last_index))
            and len(str(num)) > len(str(last_index))
            and num > last_index + self.config.subpart_threshold
        ):
            # Heuristique : Si num > last + threshold, c'est probablement une subpart
            # Ex: last=1, num=11 → 11 > 1+5 → subpart probable
            subpart_num = int(str(num)[len(str(last_index)) :])
            return _FileAnalysis(
                _FileType.SUBPART,
                name=name,
                chapter_num=last_index,
                is_new_chapter=False,
                reason=f"Subpart détectée '{name}' ({last_index} partie {subpart_num})",
            )

        # Cas 5 : Saut dans numérotation (last=1, num=5)
        # → Nouveau chapitre (numérotation non séquentielle)
        if num > last_index + 1:
            logger.warning(
                f"⚠️  Saut dans numérotation '{name}' : {last_index} → {num} "
                f"(éléments intermédiaires manquants ?)"
            )
            self.context.index_by_name[name] = num
            return _FileAnalysis(
                _FileType.MAIN_CHAPTER,
                name=name,
                chapter_num=num,
                is_new_chapter=True,
                reason=f"Saut numérotation '{name}' ({last_index} → {num})",
            )

        # Cas 6 : Retour en arrière (last=5, num=1)
        # → Probablement erreur, mais traiter comme nouveau chapitre
        logger.warning(
            f"⚠️  Retour arrière dans numérotation '{name}' : {last_index} → {num}"
        )
        self.context.index_by_name[name] = num
        return _FileAnalysis(
            _FileType.MAIN_CHAPTER,
            name=name,
            chapter_num=num,
            is_new_chapter=True,
            reason=f"Retour arrière '{name}' ({last_index} → {num})",
        )

    def _extract_filename_and_chapter_number(
        self, filename: str
    ) -> tuple[str, int | None]:
        """
        Extrait le numéro de chapitre d'un nom de fichier.

        Supporte patterns flexibles avec séparateurs variables:
        - chapter1, chap1, ch1, part1, section1
        - chapter_1, chapter-01, ch_001 (séparateurs : espace, _, -)
        - 001, 002 (numéros purs ≥2 chiffres)

        Args:
            filename: Nom de fichier normalisé

        Returns:
            Numéro de chapitre ou None si pas détecté
        """
        # Pattern 1 : Mot-clé + séparateur optionnel + numéro
        # Ex: chapter1, chapter_1, chapter-01, ch_001
        # Supporte aussi : intermission, interlude, prologue, epilogue (découverte dynamique)
        pattern1 = r"([a-zA-Z]+)[\s_-]*(\d*)"
        match = re.search(pattern1, filename, re.IGNORECASE)
        if match:
            base_name = match.group(1)
            number_str = match.group(2)
            return (
                base_name,
                int(number_str) if number_str.isdigit() else None,
            )

        # Pattern 2 : Numéros purs (≥2 chiffres pour éviter faux positifs)
        # Ex: 001.html, 002.html
        pattern2 = r"(\d{2,})"
        match = re.search(pattern2, filename)
        if match:
            empty_name = f"empty_chapter_{self.empty_name_index}"
            self.empty_name_index += 1
            return (empty_name, int(match.group(1)))

        return filename, None

    def _normalize_filename(self, filename: str) -> str:
        """
        Normalise un nom de fichier pour analyse.

        - Extrait le basename (sans chemin)
        - Supprime extension (.html, .xhtml)
        - Convertit en minuscules

        Args:
            filename: Nom de fichier brut (ex: "Text/chapter1.xhtml")

        Returns:
            Nom normalisé (ex: "chapter1")
        """
        basename = filename.split("/")[-1].lower()
        basename = basename.replace(".html", "").replace(".xhtml", "")
        return basename

    def _make_chapter_name(self, analysis: _FileAnalysis) -> str:
        """
        Génère un nom de chapitre depuis une analyse.

        Args:
            analysis: Analyse du fichier

        Returns:
            Nom de chapitre formaté (ex: "Chapter 1", "Prologue")
        """
        if analysis.toc_title is not None:
            return analysis.toc_title
        if analysis.file_type == _FileType.FRONT_MATTER:
            return "Front Matter"
        elif analysis.file_type == _FileType.BACK_MATTER:
            return "Back Matter"
        else:
            return f"{analysis.name} {analysis.chapter_num if analysis.chapter_num is not None else ''}".strip()

    def _create_chapter_info(self) -> ChapterInfo:
        """
        Crée un ChapterInfo depuis le contexte actuel.

        Returns:
            ChapterInfo avec fichiers du chapitre courant
        """
        info = ChapterInfo(
            index=self.context.chapter_index,
            name=self.context.current_chapter_name,
            files=self.context.current_files.copy(),
        )

        self.context.chapter_index += 1
        return info
