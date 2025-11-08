"""
Détection de chapitres basée sur la spine EPUB.

Plus robuste que la détection par balises h1 car :
- Analyse la structure EPUB (spine + noms de fichiers)
- Supporte les chapitres multi-fichiers (chapter1.html + chapter1_a.html)
- Gère les inserts (insert1.xhtml entre chapitres)
- Fallback LLM pour cas ambigus
"""

from dataclasses import dataclass
from typing import Iterator, Optional
import re
from ebooklib import epub

from ebook_translator.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ChapterGroup:
    """
    Représente un groupe de fichiers HTML formant un chapitre.

    Un chapitre peut être composé de :
    - 1 fichier principal (ex: chapter1.html)
    - Plusieurs sous-parties (ex: chapter11.html, chapter12.html)
    - Des inserts intercalés (ex: insert1.xhtml)
    """

    chapter_index: int
    """Index du chapitre (0, 1, 2, ...)"""

    chapter_name: str
    """Nom du chapitre (ex: 'Chapter 1', 'Prologue')"""

    html_files: list[epub.EpubHtml]
    """Liste des fichiers HTML composant ce chapitre (dans l'ordre de la spine)"""

    is_multi_file: bool
    """True si le chapitre est composé de plusieurs fichiers"""

    def get_file_names(self) -> list[str]:
        """Retourne la liste des noms de fichiers."""
        return [html.get_name() for html in self.html_files]


@dataclass
class ChapterDetectorConfig:
    """Configuration pour la détection de chapitres."""

    include_front_matter: bool = False
    """Inclure front matter (preface, dedication, etc.) comme chapitres"""

    include_back_matter: bool = False
    """Inclure back matter (afterword, appendix, bonus) comme chapitres"""

    llm_validation_threshold: float = 0.3
    """Seuil d'ambiguïté déclenchant validation LLM (0-1)"""

    max_files_per_chapter: int = 15
    """Nombre max de fichiers par chapitre avant alerte"""


class ChapterDetector:
    """
    Détecte et groupe les fichiers HTML par chapitre logique.

    Algorithme en 4 passes :
    1. CLASSIFICATION : Détecte le type de chaque fichier (MAIN_CHAPTER, SUBPART, INSERT, etc.)
    2. REGROUPEMENT : Groupe les fichiers par numéro de chapitre principal
    3. RATTACHEMENT : Attache les sous-parties et inserts aux chapitres parents
    4. VALIDATION LLM : Optionnel, pour résoudre les cas ambigus

    Patterns supportés :
    - Chapitres principaux : chapter1, chapter2, chapter001, chap1, ch1, part1
    - Sous-parties : chapter11 (→ chapter 1 part 1), chapter1_a, chapter1_1
    - Inserts : insert1, insert2, interlude1
    - Spéciaux : prologue, epilogue, epilogue1
    """

    # Patterns regex pour détection de numéros de chapitre
    CHAPTER_PATTERNS = [
        r'chapter(\d+)(_[a-z0-9]+)?',  # chapter1, chapter1_a, chapter001
        r'chap(\d+)(_[a-z0-9]+)?',     # chap1, chap1_a
        r'ch(\d+)(_[a-z0-9]+)?',       # ch1, ch1_a
        r'part(\d+)(_[a-z0-9]+)?',     # part1, part1_a
        r'section(\d+)(_[a-z0-9]+)?',  # section1
        r'(\d{3,})(_[a-z0-9]+)?',      # 001, 001_a (numéros seuls >= 3 chiffres)
    ]

    # Patterns à ignorer (SKIP)
    SKIP_PATTERNS = [
        r'^cover',
        r'^toc',
        r'^copyright',
        r'^signup',
        r'^colophon',
        r'^titlepage',
    ]

    # Front matter patterns
    FRONT_MATTER_PATTERNS = [
        r'^frontmatter',
        r'^preface',
        r'^foreword',
        r'^acknowledgments?',
        r'^dedication',
        r'^introduction',
    ]

    # Back matter patterns
    BACK_MATTER_PATTERNS = [
        r'^afterword',
        r'^bonus',
        r'^appendix',
        r'^about',
        r'^also_by',
        r'^newsletter',
    ]

    def __init__(
        self,
        epub_htmls: list[epub.EpubHtml],
        llm=None,
        config: Optional[ChapterDetectorConfig] = None,
    ):
        """
        Initialise le détecteur de chapitres.

        Args:
            epub_htmls: Liste des fichiers HTML de l'EPUB (dans l'ordre de la spine)
            llm: Instance LLM optionnelle pour résolution cas ambigus
            config: Configuration optionnelle
        """
        self.epub_htmls = epub_htmls
        self.llm = llm
        self.config = config or ChapterDetectorConfig()
        self._classified: list[dict] = []

    def detect_chapters(self) -> Iterator[ChapterGroup]:
        """
        Détecte et groupe les fichiers HTML par chapitre.

        Yields:
            ChapterGroup pour chaque chapitre détecté
        """
        logger.info(f"🔍 Détection de chapitres pour {len(self.epub_htmls)} fichiers HTML")

        # PASSE 1 : Classification des fichiers
        self._classified = self._classify_files()

        # PASSE 2 : Regroupement par chapitre principal
        grouped = self._group_by_main_chapter(self._classified)

        # PASSE 3 : Rattachement des sous-parties et inserts
        grouped = self._attach_subparts_and_inserts(grouped, self._classified)

        # PASSE 4 : Validation LLM si nécessaire
        if self._needs_llm_validation(grouped):
            if self.llm:
                logger.warning("⚠️  Cas ambigus détectés, validation LLM activée...")
                grouped = self._llm_validate(grouped)
            else:
                logger.warning("⚠️  Cas ambigus détectés mais pas de LLM fourni, regroupement automatique")

        # Générer ChapterGroup
        chapter_index = 0
        for group in grouped:
            yield ChapterGroup(
                chapter_index=chapter_index,
                chapter_name=group['chapter_name'],
                html_files=group['files'],
                is_multi_file=len(group['files']) > 1,
            )
            chapter_index += 1

        logger.info(f"✅ {chapter_index} chapitres détectés")

    def _classify_files(self) -> list[dict]:
        """
        PASSE 1 : Classifie chaque fichier selon son rôle.

        Types détectés :
        - SKIP : cover, toc, copyright (à ignorer)
        - FRONT_MATTER : preface, dedication, etc.
        - BACK_MATTER : afterword, appendix, etc.
        - PROLOGUE : prologue
        - EPILOGUE : epilogue (+ variantes epilogue1)
        - MAIN_CHAPTER : chapter1, chapter2, etc.
        - SUBPART : chapter11 (→ chapter 1 part 1), chapter21, etc.
        - INSERT : insert1, insert2, interlude, etc.

        Returns:
            Liste de dicts avec classification
        """
        classified = []

        for spine_index, html in enumerate(self.epub_htmls):
            filename = self._normalize_filename(html.get_name())

            file_type = None
            chapter_num = None
            subpart = None

            # Détection SKIP
            if any(re.match(p, filename) for p in self.SKIP_PATTERNS):
                file_type = 'SKIP'

            # Détection FRONT_MATTER
            elif any(re.match(p, filename) for p in self.FRONT_MATTER_PATTERNS):
                file_type = 'FRONT_MATTER'

            # Détection BACK_MATTER
            elif any(re.match(p, filename) for p in self.BACK_MATTER_PATTERNS):
                file_type = 'BACK_MATTER'

            # Détection PROLOGUE
            elif re.match(r'^prologue', filename):
                file_type = 'PROLOGUE'
                chapter_num = 0

            # Détection EPILOGUE
            elif re.match(r'^epilogue', filename):
                file_type = 'EPILOGUE'
                match = re.match(r'^epilogue(\d+)?', filename)
                if match and match.group(1):
                    subpart = int(match.group(1))

            # Détection INSERT
            elif re.match(r'^(insert|interlude)\d+', filename):
                file_type = 'INSERT'

            # Détection CHAPTER (MAIN vs SUBPART)
            else:
                chapter_info = self._extract_chapter_number(filename)
                if chapter_info:
                    chapter_num, subpart = chapter_info
                    # Distinguer MAIN_CHAPTER de SUBPART
                    if subpart is None:
                        file_type = 'MAIN_CHAPTER'
                    else:
                        file_type = 'SUBPART'

            classified.append({
                'html': html,
                'filename': filename,
                'file_type': file_type,
                'chapter_num': chapter_num,
                'subpart': subpart,
                'spine_index': spine_index,
            })

        logger.debug(f"Classification : {len([c for c in classified if c['file_type'] == 'MAIN_CHAPTER'])} chapitres principaux")
        return classified

    def _extract_chapter_number(self, filename: str) -> Optional[tuple[int, Optional[int]]]:
        """
        Extrait numéro de chapitre et sous-partie depuis nom de fichier.

        Exemples :
            "chapter1.html" → (1, None)
            "chapter11.html" → (1, 1)  # chapter 1 part 1
            "chapter001.html" → (1, None)
            "chapter1_a.html" → (1, None)  # variante, pas sous-partie numérique

        Returns:
            (chapter_number, subpart) ou None si pas de pattern détecté
        """
        for pattern in self.CHAPTER_PATTERNS:
            match = re.search(pattern, filename)
            if match:
                num_str = match.group(1)

                # Cas 1 : Numéro simple (1 chiffre) → MAIN_CHAPTER
                if len(num_str) == 1:
                    return (int(num_str), None)

                # Cas 2 : Numéro double (2 chiffres) → Possiblement SUBPART
                elif len(num_str) == 2:
                    # Ex: "11" peut être chapter 11 OU chapter 1 part 1
                    # Heuristique : si premier chiffre répété (11, 22, 33) → MAIN_CHAPTER
                    # Sinon (12, 21, 34) → SUBPART
                    first_digit = int(num_str[0])
                    second_digit = int(num_str[1])

                    if first_digit == second_digit:
                        # 11, 22, 33 → MAIN_CHAPTER
                        return (int(num_str), None)
                    else:
                        # 12, 21, 34 → SUBPART (chapter X part Y)
                        return (first_digit, second_digit)

                # Cas 3 : Numéro long (3+ chiffres) → Traiter comme numéro complet
                else:
                    # Ex: "001" → chapter 1
                    return (int(num_str), None)

        return None

    def _normalize_filename(self, filename: str) -> str:
        """
        Normalise un nom de fichier pour analyse.

        - Extrait le basename (sans chemin)
        - Supprime extension (.html, .xhtml)
        - Convertit en minuscules
        """
        basename = filename.split('/')[-1].lower()
        basename = basename.replace('.html', '').replace('.xhtml', '')
        return basename

    def _group_by_main_chapter(self, classified: list[dict]) -> list[dict]:
        """
        PASSE 2 : Regroupe les fichiers par chapitre principal.

        Returns:
            Liste de dicts : [
                {
                    'chapter_name': 'Chapter 1',
                    'chapter_num': 1,
                    'main_file': {...},
                    'files': [html1, ...],
                    'subparts': [...],
                    'inserts': [],
                },
                ...
            ]
        """
        groups: dict[str, dict] = {}

        for item in classified:
            file_type = item['file_type']

            # Ignorer SKIP
            if file_type == 'SKIP':
                continue

            # Ignorer FRONT_MATTER si config
            if file_type == 'FRONT_MATTER' and not self.config.include_front_matter:
                continue

            # Ignorer BACK_MATTER si config
            if file_type == 'BACK_MATTER' and not self.config.include_back_matter:
                continue

            # Traiter PROLOGUE
            if file_type == 'PROLOGUE':
                key = 'prologue'
                if key not in groups:
                    groups[key] = {
                        'chapter_name': 'Prologue',
                        'chapter_num': 0,
                        'main_file': item,
                        'files': [item['html']],
                        'subparts': [],
                        'inserts': [],
                    }

            # Traiter EPILOGUE
            elif file_type == 'EPILOGUE':
                key = 'epilogue'
                if key not in groups:
                    groups[key] = {
                        'chapter_name': 'Epilogue',
                        'chapter_num': 999,  # Grand nombre pour tri final
                        'main_file': item if item['subpart'] is None else None,
                        'files': [],
                        'subparts': [],
                        'inserts': [],
                    }
                if item['subpart'] is None:
                    groups[key]['main_file'] = item
                    groups[key]['files'].append(item['html'])
                else:
                    groups[key]['subparts'].append(item)

            # Traiter MAIN_CHAPTER
            elif file_type == 'MAIN_CHAPTER':
                key = f"chapter_{item['chapter_num']}"
                if key not in groups:
                    groups[key] = {
                        'chapter_name': f"Chapter {item['chapter_num']}",
                        'chapter_num': item['chapter_num'],
                        'main_file': item,
                        'files': [item['html']],
                        'subparts': [],
                        'inserts': [],
                    }

            # SUBPART et INSERT seront traités dans PASSE 3

        return list(groups.values())

    def _attach_subparts_and_inserts(
        self,
        groups: list[dict],
        classified: list[dict]
    ) -> list[dict]:
        """
        PASSE 3 : Attache les SUBPARTs et INSERTs aux chapitres principaux.

        Logique :
        - SUBPART chapter11 → rattaché à chapter 1
        - INSERT entre chapter1 et chapter2 → rattaché à chapter 1 (chapitre précédent)
        """
        # Trier groupes par chapter_num
        groups_sorted = sorted(groups, key=lambda g: g['chapter_num'])

        for item in classified:
            file_type = item['file_type']

            # Traiter SUBPART
            if file_type == 'SUBPART':
                parent_chapter_num = item['chapter_num']
                # Trouver le groupe parent
                parent_group = next(
                    (g for g in groups_sorted if g['chapter_num'] == parent_chapter_num),
                    None
                )
                if parent_group:
                    parent_group['subparts'].append(item)
                    parent_group['files'].append(item['html'])
                else:
                    logger.warning(
                        f"SUBPART {item['filename']} sans chapitre parent {parent_chapter_num}"
                    )

            # Traiter INSERT
            elif file_type == 'INSERT':
                # Rattacher au dernier chapitre commencé avant cet insert
                spine_index = item['spine_index']
                parent_group = None

                for group in reversed(groups_sorted):
                    main_file = group.get('main_file')
                    if main_file and main_file['spine_index'] < spine_index:
                        parent_group = group
                        break

                if parent_group:
                    parent_group['inserts'].append(item)
                    parent_group['files'].append(item['html'])
                else:
                    logger.warning(
                        f"INSERT {item['filename']} sans chapitre parent, ignoré"
                    )

        # Trier les fichiers de chaque groupe par spine_index (ordre de lecture)
        for group in groups:
            # Reconstruire files dans l'ordre
            all_items = []
            if group['main_file']:
                all_items.append(group['main_file'])
            all_items.extend(group['subparts'])
            all_items.extend(group['inserts'])
            all_items.sort(key=lambda x: x['spine_index'])
            group['files'] = [item['html'] for item in all_items]

        return groups_sorted

    def _needs_llm_validation(self, groups: list[dict]) -> bool:
        """
        Détermine si le regroupement nécessite validation LLM.

        Critères déclenchant LLM :
        - Trop de fichiers sans classification claire
        - Chapitres avec trop de fichiers (>max_files_per_chapter)
        - Numérotation non séquentielle
        """
        if not self.llm:
            return False

        # Compter fichiers non classés (None)
        unclassified_count = sum(
            1 for item in self._classified
            if item['file_type'] is None
        )

        total_files = len(self._classified)
        if total_files > 0:
            unclassified_ratio = unclassified_count / total_files
            if unclassified_ratio > self.config.llm_validation_threshold:
                logger.debug(f"Taux fichiers non classés : {unclassified_ratio:.1%} > seuil {self.config.llm_validation_threshold:.1%}")
                return True

        # Vérifier taille des groupes
        for group in groups:
            if len(group['files']) > self.config.max_files_per_chapter:
                logger.debug(
                    f"Chapitre '{group['chapter_name']}' a {len(group['files'])} fichiers "
                    f"(> max {self.config.max_files_per_chapter})"
                )
                return True

        # Vérifier séquentialité des numéros de chapitre
        chapter_nums = [
            g['chapter_num'] for g in groups
            if g['chapter_num'] is not None and g['chapter_num'] < 999
        ]
        if chapter_nums:
            expected = list(range(1, max(chapter_nums) + 1))
            missing = set(expected) - set(chapter_nums)
            if len(missing) > 2:  # Tolérer 2 chapitres manquants
                logger.debug(f"Chapitres manquants : {sorted(missing)}")
                return True

        return False

    def _llm_validate(self, groups: list[dict]) -> list[dict]:
        """
        PASSE 4 : Utilise LLM pour valider/corriger le regroupement.

        Construit un prompt avec :
        - Liste des fichiers dans l'ordre de la spine
        - Groupement actuel détecté
        - Demande de validation ou correction
        """
        # Construire liste des fichiers
        filenames = [item['filename'] for item in self._classified]

        # Construire résumé du groupement actuel
        grouping_summary = []
        for group in groups:
            files_str = ', '.join([item['filename'] for item in self._classified if item['html'] in group['files']])
            grouping_summary.append(
                f"{group['chapter_name']} ({len(group['files'])} fichiers) : {files_str}"
            )

        prompt = f"""You are validating an EPUB chapter detection.

**Detected grouping:**
{chr(10).join(f"{i+1}. {line}" for i, line in enumerate(grouping_summary))}

**Original spine order (all files):**
{chr(10).join(f"{i+1}. {fn}" for i, fn in enumerate(filenames))}

**Task:** Validate this chapter grouping.

**Rules:**
1. Files like chapter1, chapter11, chapter12 → chapter 1 with subparts
2. Files like chapter1, insert1, chapter11 → all belong to chapter 1
3. Files like chapter1, chapter2 → separate chapters
4. Prologue, Epilogue are separate chapters

**Output JSON:**
```json
{{
  "is_valid": true/false,
  "corrections": [
    {{"action": "move", "file": "filename", "from": "chapter_X", "to": "chapter_Y", "reason": "..."}},
    ...
  ]
}}
```

If grouping is correct, return: {{"is_valid": true, "corrections": []}}
"""

        try:
            response = self.llm.query(
                system_prompt="You are an EPUB structure validator.",
                content=prompt,
                use_json_mode=True,
                context="chapter_grouping_validation",
            )

            import json
            data = json.loads(response)

            if not data.get('is_valid', True):
                logger.warning(f"LLM a détecté {len(data.get('corrections', []))} corrections nécessaires")
                # TODO: Implémenter application des corrections
                # Pour l'instant, on garde le regroupement automatique

        except Exception as e:
            logger.error(f"Erreur validation LLM : {e}")

        return groups
