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

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Iterator, Optional
import re
from ebooklib import epub

from ..logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class FileType(Enum):
    """Types de fichiers détectés pendant le parcours."""
    MAIN_CHAPTER = auto()       # Chapitre principal (chapter1, chapter2, ...)
    SUBPART = auto()            # Sous-partie (chapter11 après chapter1)
    INSERT = auto()             # Insert/interlude entre chapitres
    PROLOGUE = auto()           # Prologue
    EPILOGUE = auto()           # Epilogue
    FRONT_MATTER = auto()       # Front matter (preface, dedication, ...)
    BACK_MATTER = auto()        # Back matter (afterword, appendix, ...)
    SKIP = auto()               # À ignorer (cover, toc, copyright, ...)


@dataclass
class ChapterContext:
    """
    Contexte maintenu pendant le parcours séquentiel de la spine.

    Ce contexte permet de prendre des décisions basées sur l'HISTORIQUE
    au lieu de règles regex rigides.
    """
    current_chapter_num: int | None = None
    """Numéro du chapitre actuel"""

    current_chapter_name: str = ""
    """Nom du chapitre actuel (ex: 'Chapter 1', 'Prologue')"""

    current_files: list[epub.EpubHtml] = field(default_factory=list)
    """Fichiers HTML du chapitre actuel"""

    last_main_chapter_num: int | None = None
    """Dernier numéro de chapitre PRINCIPAL vu (clé pour résoudre ambiguïtés)"""

    chapter_index: int = 0
    """Index global du chapitre (0, 1, 2, ...)"""


@dataclass
class FileAnalysis:
    """
    Résultat de l'analyse d'un fichier.

    Contient la décision prise (type, nouveau chapitre ou non)
    et la justification pour debugging.
    """
    file_type: FileType
    """Type de fichier détecté"""

    chapter_num: int | None = None
    """Numéro de chapitre extrait (si applicable)"""

    is_new_chapter: bool = False
    """True si ce fichier démarre un NOUVEAU chapitre"""

    reason: str = ""
    """Justification de la décision (pour debugging/logging)"""


@dataclass
class ChapterGroup:
    """
    Représente un groupe de fichiers HTML formant un chapitre.

    Compatible avec l'ancien ChapterGroup de chapter_detector.py
    pour assurer rétrocompatibilité.
    """
    chapter_index: int
    chapter_name: str
    html_files: list[epub.EpubHtml]
    is_multi_file: bool

    def get_file_names(self) -> list[str]:
        """Retourne la liste des noms de fichiers."""
        return [html.get_name() for html in self.html_files]


@dataclass
class SequentialDetectorConfig:
    """Configuration pour le détecteur séquentiel."""

    include_front_matter: bool = False
    """Inclure front matter (preface, dedication, etc.) comme chapitres"""

    include_back_matter: bool = False
    """Inclure back matter (afterword, appendix, bonus) comme chapitres"""

    subpart_threshold: int = 5
    """Seuil pour détecter subparts : num > last + threshold → probablement subpart"""


class SequentialChapterDetector:
    """
    Détecteur de chapitres par parcours séquentiel de la spine.

    Algorithme en 1 passe :
    1. Parcourt la spine dans l'ordre
    2. Pour chaque fichier : analyse avec CONTEXTE (fichiers précédents)
    3. Décide : nouveau chapitre / subpart / insert
    4. Yield les chapitres au fur et à mesure

    Avantages vs chapter_detector.py :
    - **Robustesse** : Résout chapter11 contextuellement (après 10 → 11, après 1 → 1.1)
    - **Performance** : 1 passe vs 4 (4× plus rapide théoriquement)
    - **Simplicité** : ~300 lignes vs 607, logique centralisée
    - **Flexibilité** : Patterns génériques (chapter_1, chapter-01, ch_001)

    Example:
        >>> detector = SequentialChapterDetector(epub.items)
        >>> for chapter_group in detector.detect_chapters():
        ...     print(f"{chapter_group.chapter_name}: {len(chapter_group.html_files)} fichiers")
    """

    # Patterns flexibles (support séparateurs _ - espace)
    CHAPTER_KEYWORDS = r'(chapter|chap|ch|part|section)'
    SKIP_KEYWORDS = r'^(cover|toc|copyright|signup|colophon|titlepage)'
    FRONT_MATTER_KEYWORDS = r'^(frontmatter|preface|foreword|acknowledgments?|dedication|introduction)'
    BACK_MATTER_KEYWORDS = r'^(afterword|bonus|appendix|about|also_by|newsletter)'

    def __init__(
        self,
        epub_htmls: list[epub.EpubHtml],
        config: Optional[SequentialDetectorConfig] = None,
    ):
        """
        Initialise le détecteur séquentiel.

        Args:
            epub_htmls: Liste des fichiers HTML de l'EPUB (dans l'ordre de la spine)
            config: Configuration optionnelle
        """
        self.epub_htmls = epub_htmls
        self.config = config or SequentialDetectorConfig()
        self.context = ChapterContext()

    def detect_chapters(self) -> Iterator[ChapterGroup]:
        """
        Parcours séquentiel de la spine avec décisions contextuelles.

        Yields:
            ChapterGroup pour chaque chapitre détecté
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
                    yield self._create_chapter_group()

                # Démarrer nouveau chapitre
                self.context.current_chapter_num = analysis.chapter_num
                self.context.current_chapter_name = self._make_chapter_name(analysis)
                self.context.current_files = [html]

                # Mettre à jour last_main_chapter_num si c'est un MAIN_CHAPTER
                if analysis.file_type == FileType.MAIN_CHAPTER:
                    self.context.last_main_chapter_num = analysis.chapter_num

                logger.debug(
                    f"Nouveau chapitre : {self.context.current_chapter_name} "
                    f"({filename}) - {analysis.reason}"
                )

            elif analysis.file_type in [FileType.SUBPART, FileType.INSERT]:
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
                    self.context.current_chapter_name = self._make_chapter_name(analysis)
                    self.context.current_files = [html]

            elif analysis.file_type == FileType.SKIP:
                # Ignorer
                logger.debug(f"Ignoré : {filename} - {analysis.reason}")

        # Yield dernier chapitre
        if self.context.current_files:
            yield self._create_chapter_group()

        logger.info(f"✅ {self.context.chapter_index} chapitres détectés")

    def _analyze_with_context(
        self, filename: str, spine_index: int
    ) -> FileAnalysis:
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
        # Priorité 1 : SKIP (cover, toc, copyright)
        if re.search(self.SKIP_KEYWORDS, filename):
            return FileAnalysis(FileType.SKIP, reason="Fichier système")

        # Priorité 2 : FRONT_MATTER
        if re.search(self.FRONT_MATTER_KEYWORDS, filename):
            if self.config.include_front_matter:
                return FileAnalysis(
                    FileType.FRONT_MATTER,
                    chapter_num=0,
                    is_new_chapter=True,
                    reason="Front matter"
                )
            else:
                return FileAnalysis(FileType.SKIP, reason="Front matter (ignoré)")

        # Priorité 3 : BACK_MATTER
        if re.search(self.BACK_MATTER_KEYWORDS, filename):
            if self.config.include_back_matter:
                return FileAnalysis(
                    FileType.BACK_MATTER,
                    chapter_num=999,
                    is_new_chapter=True,
                    reason="Back matter"
                )
            else:
                return FileAnalysis(FileType.SKIP, reason="Back matter (ignoré)")

        # Priorité 4 : PROLOGUE
        if filename.startswith("prologue"):
            return FileAnalysis(
                FileType.PROLOGUE,
                chapter_num=0,
                is_new_chapter=True,
                reason="Prologue détecté"
            )

        # Priorité 5 : EPILOGUE
        if filename.startswith("epilogue"):
            return FileAnalysis(
                FileType.EPILOGUE,
                chapter_num=999,
                is_new_chapter=True,
                reason="Epilogue détecté"
            )

        # Priorité 6 : INSERT (interlude, insert)
        if re.search(r'(insert|interlude)', filename):
            return FileAnalysis(
                FileType.INSERT,
                is_new_chapter=False,
                reason="Insert/interlude détecté"
            )

        # Priorité 7 : CHAPITRE numéroté
        chapter_num = self._extract_chapter_number(filename)
        if chapter_num is None:
            # Pas de numéro détecté
            return FileAnalysis(FileType.SKIP, reason="Pas de numéro de chapitre")

        # DÉCISION CONTEXTUELLE (cœur de l'algorithme)
        return self._decide_with_context(filename, chapter_num)

    def _decide_with_context(self, filename: str, num: int) -> FileAnalysis:
        """
        Décide si un fichier démarre un nouveau chapitre ou est une subpart.

        UTILISE LE CONTEXTE (last_main_chapter_num) pour résoudre les ambiguïtés.

        Exemples :
        - chapter11 après chapter10 → CHAPITRE 11 (séquence naturelle)
        - chapter11 après chapter1  → CHAPITRE 1 PARTIE 1 (subpart)
        - chapter1_a après chapter1 → SUBPART (même numéro)

        Args:
            filename: Nom de fichier normalisé
            num: Numéro de chapitre extrait

        Returns:
            FileAnalysis avec décision contextuelle
        """
        last = self.context.last_main_chapter_num

        # Cas 1 : Premier chapitre rencontré
        if last is None:
            return FileAnalysis(
                FileType.MAIN_CHAPTER,
                chapter_num=num,
                is_new_chapter=True,
                reason="Premier chapitre"
            )

        # Cas 2 : Séquence naturelle (last=10, num=11)
        if num == last + 1:
            return FileAnalysis(
                FileType.MAIN_CHAPTER,
                chapter_num=num,
                is_new_chapter=True,
                reason=f"Séquence naturelle ({last} → {num})"
            )

        # Cas 3 : Même numéro (last=1, num=1) → SUBPART
        if num == last:
            return FileAnalysis(
                FileType.SUBPART,
                chapter_num=last,
                is_new_chapter=False,
                reason=f"Même chapitre ({num})"
            )

        # Cas 4 : Numéro commence par last (last=1, num=11/12/13)
        # → Potentiellement subpart si num est "trop loin" de last+1
        if str(num).startswith(str(last)) and len(str(num)) > len(str(last)):
            # Heuristique : Si num > last + threshold, c'est probablement une subpart
            # Ex: last=1, num=11 → 11 > 1+5 → subpart probable
            if num > last + self.config.subpart_threshold:
                subpart_num = int(str(num)[len(str(last)):])
                return FileAnalysis(
                    FileType.SUBPART,
                    chapter_num=last,
                    is_new_chapter=False,
                    reason=f"Subpart détectée (chapitre {last} partie {subpart_num})"
                )

        # Cas 5 : Saut dans numérotation (last=1, num=5)
        # → Nouveau chapitre (numérotation non séquentielle)
        if num > last + 1:
            logger.warning(
                f"⚠️  Saut dans numérotation : chapter {last} → {num} "
                f"(chapitres intermédiaires manquants ?)"
            )
            return FileAnalysis(
                FileType.MAIN_CHAPTER,
                chapter_num=num,
                is_new_chapter=True,
                reason=f"Saut numérotation ({last} → {num})"
            )

        # Cas 6 : Retour en arrière (last=5, num=1)
        # → Probablement erreur, mais traiter comme nouveau chapitre
        logger.warning(
            f"⚠️  Retour arrière dans numérotation : chapter {last} → {num}"
        )
        return FileAnalysis(
            FileType.MAIN_CHAPTER,
            chapter_num=num,
            is_new_chapter=True,
            reason=f"Retour arrière ({last} → {num})"
        )

    def _extract_chapter_number(self, filename: str) -> Optional[int]:
        """
        Extrait le numéro de chapitre d'un nom de fichier.

        Supporte patterns flexibles avec séparateurs variables :
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
        pattern1 = rf'{self.CHAPTER_KEYWORDS}[\s_-]*(\d+)'
        match = re.search(pattern1, filename, re.IGNORECASE)
        if match:
            return int(match.group(2))

        # Pattern 2 : Numéros purs (≥2 chiffres pour éviter faux positifs)
        # Ex: 001.html, 002.html
        pattern2 = r'(\d{2,})'
        match = re.search(pattern2, filename)
        if match:
            return int(match.group(1))

        return None

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

    def _make_chapter_name(self, analysis: FileAnalysis) -> str:
        """
        Génère un nom de chapitre depuis une analyse.

        Args:
            analysis: Analyse du fichier

        Returns:
            Nom de chapitre formaté (ex: "Chapter 1", "Prologue")
        """
        if analysis.file_type == FileType.PROLOGUE:
            return "Prologue"
        elif analysis.file_type == FileType.EPILOGUE:
            return "Epilogue"
        elif analysis.file_type == FileType.FRONT_MATTER:
            return "Front Matter"
        elif analysis.file_type == FileType.BACK_MATTER:
            return "Back Matter"
        else:
            return f"Chapter {analysis.chapter_num}"

    def _create_chapter_group(self) -> ChapterGroup:
        """
        Crée un ChapterGroup depuis le contexte actuel.

        Returns:
            ChapterGroup avec fichiers du chapitre courant
        """
        group = ChapterGroup(
            chapter_index=self.context.chapter_index,
            chapter_name=self.context.current_chapter_name,
            html_files=self.context.current_files.copy(),
            is_multi_file=len(self.context.current_files) > 1,
        )

        self.context.chapter_index += 1
        return group
