"""
Auditeur de la phase glossaire.

Le cahier des charges tient en une phrase : fournir un **nom stable pour les
éléments importants** du texte — personnages, lieux nommés, objets récurrents —
et non une traduction pour chaque terme rencontré. L'auditeur ne juge pas cette
importance : il mesure ce qui la contredit mécaniquement.

Sur *The Yellow Wallpaper*, un glossaire de 48 termes contenait `the bay`,
`the cellar`, `the garden`, `the lane`, `the village`, `the wharf`,
`the estate` — des noms communs génériques qu'aucune traduction n'a besoin de
stabiliser. Trois signaux les distinguent d'un `weir mitchell` : l'article de
tête, l'absence de capitale en milieu de phrase dans la source, et un ancrage
faible (une ou deux occurrences dans tout le livre).

Aucun de ces signaux n'est une preuve — un lieu nommé peut porter un article
(`the Thames`). Ils sont donc rendus comme observations avec leurs exemples, à
charge pour l'agent auditeur de trancher sur pièces.

Matière lue : les charges brutes du store v2 (`_v2/glossary_*.json`, une liste de
termes par chunk), avec repli sur les tables Markdown de revue
(`chunk N.md`) quand le v2 est absent.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from ebook_translator.audit.findings import (
    AuditFindings,
    Metric,
    Observation,
    Sample,
    top_samples,
)
from ebook_translator.audit.source import AuditSource
from ebook_translator.glossary import (
    DEFAULT_MIN_REINJECTION_WEIGHT,
    confidence_level,
    converged_weight,
)
from ebook_translator.logger import get_logger
from ebook_translator.pipeline.base import PhaseName
from template.phase.glossary_models import LLMTermeGlossary

logger = get_logger(__name__)

SPEC_NAME = "glossary"
"""Cahier des charges remis à l'agent (`audit/specs/glossary.md`)."""

MAX_SAMPLES = 12
"""Exemples retenus par observation.

Assez pour juger d'une tendance, assez peu pour que le rapport reste lisible et
que le contexte de l'agent ne soit pas noyé par une liste exhaustive.
"""

WEAK_ANCHOR_THRESHOLD = 2
"""Occurrences source en deçà desquelles un terme n'est pas « récurrent »."""

MISSED_CANDIDATE_THRESHOLD = 3
"""Occurrences d'un candidat capitalisé pour qu'un oubli soit signalé."""

LEADING_ARTICLES = ("the ", "a ", "an ")
"""Articles anglais de tête — signal de nom commun générique."""

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
"""Mot alphabétique, apostrophes internes comprises (`don't`, `l'allée`)."""

_SENTENCE_BREAK_RE = re.compile(r"[.!?:;]\s*[\"'“”‘’(\[]*\s*$")
"""Fin de phrase juste avant la position courante."""

_ALWAYS_CAPITAL = frozenset({"i", "i'd", "i'll", "i'm", "i've"})
"""Mots anglais toujours capitalisés : sans valeur de nom propre."""

_APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'"})
"""Apostrophes typographiques ramenées à l'apostrophe droite.

Sans quoi `I\u2019ve` du texte source ne correspond à aucune entrée de
`_ALWAYS_CAPITAL` et remonte comme entité nommée oubliée.
"""


def _normalize(text: str) -> str:
    """Ramène un texte à une forme comparable.

    Args:
        text: Texte brut.

    Returns:
        Le texte en minuscules, apostrophes normalisées.
    """
    return text.translate(_APOSTROPHES).lower()


@dataclass(frozen=True)
class _TermUsage:
    """Ce que le glossaire a produit pour un terme source donné.

    Attributes:
        term: Terme source, normalisé en minuscules par la phase.
        chunks: Index de chunk où le terme a été émis, avec leur effectif.
        translations: Propositions de traduction observées, avec leur effectif.
        types: Classements `type` observés, avec leur effectif.
        sexes: Classements `sexe` observés, avec leur effectif.
    """

    term: str
    chunks: Counter[str]
    translations: Counter[str]
    types: Counter[str]
    sexes: Counter[str]

    @property
    def emissions(self) -> int:
        """Nombre total de lignes émises pour ce terme, tous chunks confondus."""
        return sum(self.chunks.values())


class GlossaryAuditor:
    """Mesure la sortie de la phase glossaire dans un cache."""

    phase: PhaseName = PhaseName.GLOSSARY
    spec_name: str = SPEC_NAME

    def run(self, source: AuditSource) -> AuditFindings:
        """Audite le glossaire produit dans un cache.

        Args:
            source: Cache à auditer.

        Returns:
            Métriques, catalogue d'erreurs et limites de mesure.
        """
        par_chunk = _read_terms_by_chunk(source)
        usages = _aggregate(par_chunk)
        texte = source.source_text
        index_source = _SourceIndex.build(texte)

        observations = _observations(usages, par_chunk, index_source)
        findings = AuditFindings(
            phase=self.phase,
            spec_name=self.spec_name,
            metrics=_metrics(usages, par_chunk, index_source),
            observations=observations,
            notes=_notes(source, par_chunk, usages),
        )
        # L'union se calcule sur les observations : elle ferme la table des
        # chiffres, où la somme des effectifs est trompeuse.
        return replace(
            findings, metrics=findings.metrics + _union_metrics(findings, usages)
        )


# ---------------------------------------------------------------------------
# Lecture de la matière
# ---------------------------------------------------------------------------


def _read_terms_by_chunk(source: AuditSource) -> dict[str, list[LLMTermeGlossary]]:
    """Termes émis, groupés par chunk.

    Le store v2 fait foi ; les tables Markdown ne servent que de repli, car
    elles ont perdu le code de sexe brut au profit d'un libellé.

    Args:
        source: Cache à lire.

    Returns:
        Mapping `clé de chunk → termes émis`, dans l'ordre de lecture du livre.
    """
    charges = source.byte_store_payloads(PhaseName.GLOSSARY)
    if charges:
        return {
            cle: _parse_payload(cle, charge)
            for cle, charge in sorted(charges.items(), key=lambda p: _chunk_order(p[0]))
        }

    logger.warning("Store v2 absent, repli sur les tables Markdown de revue.")
    return {
        label: _parse_markdown_table(contenu)
        for label, contenu in sorted(
            source.markdown_documents(PhaseName.GLOSSARY).items(),
            key=lambda p: _chunk_order(p[0]),
        )
    }


_CHUNK_INDEX_RE = re.compile(r"\d+")
"""Premier entier d'une clé de chunk (`12_a1b2c3d4`, `chunk 12`)."""


def _chunk_order(key: str) -> tuple[int, str]:
    """Rang d'un chunk dans le livre.

    L'ordre importe : la convergence d'un terme se simule chunk après chunk, et
    un tri lexicographique placerait `10_…` avant `2_…`.

    Args:
        key: Clé du chunk.

    Returns:
        Un couple `(index, clé)`, l'index valant `-1` s'il est illisible.
    """
    correspondance = _CHUNK_INDEX_RE.search(key)
    return (int(correspondance.group(0)) if correspondance else -1, key)


def _parse_payload(key: str, payload: str) -> list[LLMTermeGlossary]:
    """Décode la charge d'un chunk du store v2.

    Args:
        key: Clé du chunk, pour le journal en cas d'échec.
        payload: Charge sérialisée, une liste JSON d'entrées.

    Returns:
        Les entrées bien formées ; une charge illisible rend une liste vide.
    """
    try:
        contenu: object = json.loads(payload)
    except json.JSONDecodeError as erreur:
        logger.warning(f"Charge illisible pour le chunk {key} : {erreur}")
        return []

    if not isinstance(contenu, list):
        logger.warning(f"Charge de forme inattendue pour le chunk {key}")
        return []

    entrees: list[LLMTermeGlossary] = []
    for element in cast(list[object], contenu):
        if not isinstance(element, dict):
            continue
        brut = cast(dict[str, object], element)
        terme = brut.get("terme")
        if not isinstance(terme, str) or not terme.strip():
            continue
        entrees.append(
            LLMTermeGlossary(
                terme=terme.strip().lower(),
                type=cast(str, brut.get("type", "")),  # pyright: ignore[reportArgumentType]
                sexe=cast(str, brut.get("sexe", "")),  # pyright: ignore[reportArgumentType]
                proposition_traduction=str(
                    brut.get("proposition_traduction", "")
                ).strip(),
            )
        )
    return entrees


_TABLE_ROW_RE = re.compile(r"^\|(?P<cells>.+)\|\s*$")
_SEXE_CODES = {"masculin": "m", "féminin": "f"}


def _parse_markdown_table(content: str) -> list[LLMTermeGlossary]:
    """Relit une table de revue `chunk N.md`.

    Args:
        content: Markdown de la table.

    Returns:
        Les entrées lues, en-tête et séparateur écartés.
    """
    entrees: list[LLMTermeGlossary] = []
    for ligne in content.splitlines():
        correspondance = _TABLE_ROW_RE.match(ligne.strip())
        if correspondance is None:
            continue
        cellules = [c.strip() for c in correspondance.group("cells").split("|")]
        if len(cellules) != 4 or cellules[0].lower() in {"terme", "---"}:
            continue
        terme, type_, sexe, proposition = cellules
        if set(terme) <= {"-"}:
            continue
        entrees.append(
            LLMTermeGlossary(
                terme=terme.lower(),
                type=cast(str, type_),  # pyright: ignore[reportArgumentType]
                sexe=_SEXE_CODES.get(sexe.lower(), "nc"),  # pyright: ignore[reportArgumentType]
                proposition_traduction=proposition.strip("*"),
            )
        )
    return entrees


def _aggregate(
    par_chunk: Mapping[str, Sequence[LLMTermeGlossary]],
) -> dict[str, _TermUsage]:
    """Regroupe les émissions par terme source.

    Args:
        par_chunk: Termes émis, par chunk.

    Returns:
        Mapping `terme → usage`, trié par terme.
    """
    accumule: dict[str, _TermUsage] = {}

    for cle_chunk, termes in par_chunk.items():
        for entree in termes:
            terme = entree["terme"]
            usage = accumule.get(terme)
            if usage is None:
                usage = _TermUsage(
                    term=terme,
                    chunks=Counter(),
                    translations=Counter(),
                    types=Counter(),
                    sexes=Counter(),
                )
                accumule[terme] = usage
            usage.chunks[cle_chunk] += 1
            usage.translations[entree["proposition_traduction"].lower()] += 1
            usage.types[entree["type"]] += 1
            usage.sexes[entree["sexe"]] += 1

    return dict(sorted(accumule.items()))


# ---------------------------------------------------------------------------
# Index du texte source
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SourceIndex:
    """Ce que le texte source dit des mots qu'il emploie.

    Attributes:
        word_count: Nombre de mots du livre.
        lowered: Texte en minuscules, pour compter les occurrences d'un terme.
        mid_sentence_capitalized: Mots vus capitalisés ailleurs qu'en tête de
            phrase, avec leur effectif — le signal de nom propre.
        available: Faux quand aucun EPUB source n'a pu être lu ; les métriques
            qui en dépendent sont alors omises.
    """

    word_count: int
    lowered: str
    mid_sentence_capitalized: Counter[str]
    available: bool

    @classmethod
    def build(cls, text: str) -> _SourceIndex:
        """Indexe un texte source.

        Un mot compte comme capitalisé « en milieu de phrase » s'il porte une
        majuscule sans être précédé d'une ponctuation forte. C'est ce qui
        sépare `Jennie` d'un `The` de début de phrase.

        Args:
            text: Texte source concaténé.

        Returns:
            L'index, marqué indisponible si le texte est vide.
        """
        if not text.strip():
            return cls(
                word_count=0,
                lowered="",
                mid_sentence_capitalized=Counter(),
                available=False,
            )

        capitalises: Counter[str] = Counter()
        for correspondance in _WORD_RE.finditer(text):
            mot = correspondance.group(0)
            if not mot[0].isupper():
                continue
            minuscule = _normalize(mot)
            if minuscule in _ALWAYS_CAPITAL or len(minuscule) < 2:
                continue
            amont = text[max(0, correspondance.start() - 40) : correspondance.start()]
            if not amont.strip() or _SENTENCE_BREAK_RE.search(amont):
                continue
            capitalises[minuscule] += 1

        return cls(
            word_count=len(_WORD_RE.findall(text)),
            lowered=_normalize(text),
            mid_sentence_capitalized=capitalises,
            available=True,
        )

    def occurrences(self, term: str) -> int:
        """Occurrences d'un terme dans la source.

        Args:
            term: Terme source, en minuscules.

        Returns:
            Le nombre d'occurrences, 0 si l'index est indisponible.
        """
        noyau = _strip_article(_normalize(term))
        if not self.available or not noyau:
            return 0
        return self.lowered.count(noyau)

    def looks_like_proper_noun(self, term: str) -> bool:
        """Indique si un terme porte la marque d'un nom propre.

        Args:
            term: Terme source, en minuscules.

        Returns:
            True si l'un de ses mots est vu capitalisé en milieu de phrase.
        """
        if not self.available:
            return True
        return any(
            self.mid_sentence_capitalized.get(mot, 0) > 0
            for mot in _WORD_RE.findall(_strip_article(_normalize(term)))
        )


def _strip_article(term: str) -> str:
    """Retire l'article de tête d'un terme.

    Args:
        term: Terme source, en minuscules.

    Returns:
        Le terme sans son article, inchangé s'il n'en porte pas.
    """
    for article in LEADING_ARTICLES:
        if term.startswith(article):
            return term[len(article) :]
    return term


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------


def _metrics(
    usages: Mapping[str, _TermUsage],
    par_chunk: Mapping[str, Sequence[LLMTermeGlossary]],
    index: _SourceIndex,
) -> tuple[Metric, ...]:
    """Chiffres mesurés sur le glossaire.

    Args:
        usages: Usage par terme.
        par_chunk: Termes émis, par chunk.
        index: Index du texte source.

    Returns:
        Les métriques, dans l'ordre de lecture du rapport.
    """
    lignes_totales = sum(len(termes) for termes in par_chunk.values())
    seuil = converged_weight()
    converges = [u for u in usages.values() if _has_converged(u)]
    metrics: list[Metric] = [
        Metric("Chunks glossaire", len(par_chunk), "chunks"),
        Metric("Lignes émises", lignes_totales, "lignes"),
        Metric("Termes uniques", len(usages), "termes"),
        Metric(
            "Réémissions",
            lignes_totales - len(usages),
            "lignes",
            detail=(
                "Émissions au-delà de la première pour un même terme. C'est le "
                "mécanisme de convergence, pas un gaspillage : un terme gagne du "
                "poids en étant réémis."
            ),
        ),
        Metric(
            "Poids de convergence",
            seuil,
            "émissions",
            detail=(
                "Émissions unanimes nécessaires pour qu'un terme passe en "
                "confiance haute et sorte de la sortie attendue."
            ),
        ),
        Metric(
            "Poids de réinjection",
            DEFAULT_MIN_REINJECTION_WEIGHT,
            "émissions",
            detail="En deçà, le terme n'est pas montré au LLM au chunk suivant.",
        ),
        Metric(
            "Termes convergés",
            len(converges),
            "termes",
            detail="Termes en confiance haute au terme du run.",
        ),
    ]

    if index.available:
        pour_mille = (
            (len(usages) / index.word_count * 1000) if index.word_count else 0.0
        )
        metrics.extend(
            [
                Metric("Mots dans la source", index.word_count, "mots"),
                Metric(
                    "Densité",
                    pour_mille,
                    "termes / 1000 mots",
                    detail="Aucun seuil de référence : à juger au regard du livre.",
                ),
            ]
        )

    par_type = Counter(
        type_ for usage in usages.values() for type_ in usage.types.elements()
    )
    metrics.extend(
        Metric(f"Type « {type_} »", effectif, "lignes")
        for type_, effectif in sorted(par_type.items(), key=lambda p: (-p[1], p[0]))
    )

    return tuple(metrics)


def _has_converged(usage: _TermUsage) -> bool:
    """Indique si un terme a atteint la confiance haute.

    Args:
        usage: Usage du terme.

    Returns:
        True si la distribution de ses traductions est classée `high`.
    """
    return confidence_level(list(usage.translations.values())) == "high"


def _union_metrics(
    findings: AuditFindings, usages: Mapping[str, _TermUsage]
) -> tuple[Metric, ...]:
    """Ampleur réelle des écarts, catégories confondues.

    Args:
        findings: Constats déjà rassemblés.
        usages: Usage par terme.

    Returns:
        La métrique d'union, vide s'il n'y a aucun terme.
    """
    if not usages:
        return ()
    touches = findings.affected_subjects()
    part = len(touches) / len(usages) * 100
    return (
        Metric(
            "Termes touchés par au moins une observation",
            len(touches),
            f"termes sur {len(usages)} ({part:.0f} %)",
            detail=(
                "Les catégories ne sont pas disjointes : sommer leurs effectifs "
                "compte plusieurs fois le même terme. C'est cette union qui donne "
                "l'ampleur de l'écart."
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Catalogue d'erreurs
# ---------------------------------------------------------------------------


def _observations(
    usages: Mapping[str, _TermUsage],
    par_chunk: Mapping[str, Sequence[LLMTermeGlossary]],
    index: _SourceIndex,
) -> tuple[Observation, ...]:
    """Écarts relevés sur le glossaire, avec leurs exemples.

    Les catégories d'effectif nul sont conservées : elles disent que le signal a
    été cherché et non trouvé, ce qu'une absence ne dit pas. Seules les
    catégories réellement non mesurables — celles qui exigent le texte source —
    sont omises, et les notes du rapport les listent alors.

    Args:
        usages: Usage par terme.
        par_chunk: Termes émis, par chunk, dans l'ordre du livre.
        index: Index du texte source.

    Returns:
        Le catalogue d'erreurs, non trié.
    """
    observations: list[Observation] = [
        _unstable_translation(usages),
        _unstable_classification(usages),
        _premature_reemissions(par_chunk),
    ]

    if index.available:
        observations.extend(
            [
                _leading_article(usages, index),
                _no_proper_noun_evidence(usages, index),
                _weak_anchor(usages, index),
                _missed_candidates(usages, index),
            ]
        )

    return tuple(observations)


def _unstable_translation(usages: Mapping[str, _TermUsage]) -> Observation:
    """Termes rendus par plusieurs propositions différentes.

    C'est l'échec direct du rôle de la phase : un glossaire qui hésite ne
    stabilise rien.

    Args:
        usages: Usage par terme.

    Returns:
        L'observation correspondante.
    """
    concernes = sorted(
        (u for u in usages.values() if len(u.translations) > 1),
        key=lambda u: (-len(u.translations), u.term),
    )
    echantillons = [
        Sample(
            subject=usage.term,
            evidence=" / ".join(
                f"« {trad} » ×{n}" for trad, n in usage.translations.most_common()
            ),
            context=f"{len(usage.chunks)} chunk(s)",
        )
        for usage in concernes
    ]
    return Observation(
        category="traduction-instable",
        title="Propositions de traduction divergentes",
        description=(
            "Le même terme source reçoit plusieurs traductions selon le chunk. "
            "Le glossaire contredit alors sa raison d'être."
        ),
        count=len(concernes),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(usage.term for usage in concernes),
    )


def _unstable_classification(usages: Mapping[str, _TermUsage]) -> Observation:
    """Termes classés sous plusieurs `type` ou `sexe`.

    Args:
        usages: Usage par terme.

    Returns:
        L'observation correspondante.
    """
    concernes = sorted(
        (u for u in usages.values() if len(u.types) > 1 or len(u.sexes) > 1),
        key=lambda u: u.term,
    )
    echantillons = [
        Sample(
            subject=usage.term,
            evidence=(
                f"types : {_format_counter(usage.types)} · "
                f"sexes : {_format_counter(usage.sexes)}"
            ),
        )
        for usage in concernes
    ]
    return Observation(
        category="classement-instable",
        title="Classement contradictoire d'un chunk à l'autre",
        description=(
            "Un même terme change de `type` ou de `sexe`. Le sexe alimente les "
            "accords en français : une hésitation se propage à la traduction."
        ),
        count=len(concernes),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(usage.term for usage in concernes),
    )


def _premature_reemissions(
    par_chunk: Mapping[str, Sequence[LLMTermeGlossary]],
) -> Observation:
    """Termes réémis alors qu'ils étaient déjà stabilisés.

    Réémettre n'est pas fautif en soi : c'est ainsi qu'un terme prend du poids,
    et `glossary_existing_block.jinja` *demande* explicitement de réémettre les
    termes qui ne sont pas encore en confiance haute. La faute commence quand un
    terme déjà converti en « terme validé » — donc listé au prompt sous « NE PAS
    inclure » — revient quand même dans la sortie.

    Le poids vu par le prompt d'un chunk est celui accumulé sur les chunks
    précédents ; c'est cet état qui est rejoué ici.

    Args:
        par_chunk: Termes émis, par chunk, dans l'ordre du livre.

    Returns:
        L'observation correspondante.
    """
    cumul: dict[str, Counter[str]] = {}
    fautives: Counter[str] = Counter()

    for termes in par_chunk.values():
        deja_stables = {
            terme
            for terme, poids in cumul.items()
            if confidence_level(list(poids.values())) == "high"
        }
        for entree in termes:
            if entree["terme"] in deja_stables:
                fautives[entree["terme"]] += 1
        for entree in termes:
            cumul.setdefault(entree["terme"], Counter())[
                entree["proposition_traduction"].lower()
            ] += 1

    ordonnes = sorted(fautives.items(), key=lambda p: (-p[1], p[0]))
    echantillons = [
        Sample(
            subject=terme,
            evidence=f"{compte} réémission(s) après stabilisation",
        )
        for terme, compte in ordonnes
    ]
    return Observation(
        category="redondance",
        title="Terme réémis alors qu'il était déjà stabilisé",
        description=(
            "Un terme en confiance haute est présenté au LLM sous « Termes "
            "validés — NE PAS inclure ». Le réémettre coûte des tokens de sortie "
            "sans rien stabiliser. Les réémissions d'un terme non encore "
            "convergé ne sont pas comptées ici : le prompt les réclame."
        ),
        count=len(ordonnes),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(terme for terme, _ in ordonnes),
    )


def _leading_article(
    usages: Mapping[str, _TermUsage], index: _SourceIndex
) -> Observation:
    """Termes ouverts par un article et sans marque de nom propre.

    Args:
        usages: Usage par terme.
        index: Index du texte source.

    Returns:
        L'observation correspondante.
    """
    concernes = sorted(
        (
            u
            for u in usages.values()
            if u.term.startswith(LEADING_ARTICLES)
            and not index.looks_like_proper_noun(u.term)
        ),
        key=lambda u: u.term,
    )
    echantillons = [
        Sample(
            subject=usage.term,
            evidence=f"proposé : « {_dominant(usage.translations)} »",
            context=f"{index.occurrences(usage.term)} occurrence(s) dans la source",
        )
        for usage in concernes
    ]
    return Observation(
        category="nom-commun-article",
        title="Nom commun générique introduit par un article",
        description=(
            "`the bay`, `the cellar`, `the garden` : un article de tête sans "
            "aucune capitale en milieu de phrase désigne presque toujours un nom "
            "commun, qu'aucune traduction n'a besoin de stabiliser. Un lieu nommé "
            "peut faire exception (`the Thames`) — vérifier sur pièces."
        ),
        count=len(concernes),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(usage.term for usage in concernes),
    )


def _no_proper_noun_evidence(
    usages: Mapping[str, _TermUsage], index: _SourceIndex
) -> Observation:
    """Termes jamais capitalisés en milieu de phrase dans la source.

    Args:
        usages: Usage par terme.
        index: Index du texte source.

    Returns:
        L'observation correspondante.
    """
    concernes = sorted(
        (
            u
            for u in usages.values()
            if not index.looks_like_proper_noun(u.term)
            and not u.term.startswith(LEADING_ARTICLES)
        ),
        key=lambda u: u.term,
    )
    echantillons = [
        Sample(
            subject=usage.term,
            evidence=f"type déclaré : {_dominant(usage.types)}",
            context=f"{index.occurrences(usage.term)} occurrence(s) dans la source",
        )
        for usage in concernes
    ]
    return Observation(
        category="sans-marque-nom-propre",
        title="Aucune capitale en milieu de phrase dans la source",
        description=(
            "Le terme n'est jamais écrit avec une majuscule ailleurs qu'en tête "
            "de phrase : rien dans la source n'en fait une entité nommée. "
            "Certains objets récurrents légitimes tombent ici — à arbitrer."
        ),
        count=len(concernes),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(usage.term for usage in concernes),
    )


def _weak_anchor(usages: Mapping[str, _TermUsage], index: _SourceIndex) -> Observation:
    """Termes trop rares dans la source pour être dits récurrents.

    Args:
        usages: Usage par terme.
        index: Index du texte source.

    Returns:
        L'observation correspondante.
    """
    concernes = sorted(
        (
            (u, index.occurrences(u.term))
            for u in usages.values()
            if index.occurrences(u.term) < WEAK_ANCHOR_THRESHOLD
        ),
        key=lambda p: (p[1], p[0].term),
    )
    echantillons = [
        Sample(
            subject=usage.term,
            evidence=f"{compte} occurrence(s) dans tout le livre",
            context=f"proposé : « {_dominant(usage.translations)} »",
        )
        for usage, compte in concernes
    ]
    return Observation(
        category="ancrage-faible",
        title="Terme non récurrent dans la source",
        description=(
            f"Moins de {WEAK_ANCHOR_THRESHOLD} occurrences dans le livre entier. "
            "Un terme vu une seule fois n'a pas de cohérence à préserver. "
            "Le décompte est textuel : une entité désignée par des formes "
            "variables est sous-comptée."
        ),
        count=len(concernes),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(usage.term for usage, _ in concernes),
    )


def _missed_candidates(
    usages: Mapping[str, _TermUsage], index: _SourceIndex
) -> Observation:
    """Entités nommées récurrentes absentes du glossaire.

    Args:
        usages: Usage par terme.
        index: Index du texte source.

    Returns:
        L'observation correspondante.
    """
    couverts = {mot for terme in usages for mot in _WORD_RE.findall(_normalize(terme))}
    manques = sorted(
        (
            (mot, effectif)
            for mot, effectif in index.mid_sentence_capitalized.items()
            if effectif >= MISSED_CANDIDATE_THRESHOLD and mot not in couverts
        ),
        key=lambda p: (-p[1], p[0]),
    )
    echantillons = [
        Sample(
            subject=mot,
            evidence=f"{effectif} occurrence(s) capitalisée(s) en milieu de phrase",
        )
        for mot, effectif in manques
    ]
    return Observation(
        category="candidat-manque",
        title="Entité nommée récurrente absente du glossaire",
        description=(
            "Mot capitalisé en milieu de phrase au moins "
            f"{MISSED_CANDIDATE_THRESHOLD} fois, qu'aucun terme du glossaire ne "
            "couvre. Le rappel est le pendant de la sur-extraction : un "
            "glossaire peut être à la fois trop gros et incomplet. Bruit "
            "attendu sur les titres et les débuts de dialogue."
        ),
        count=len(manques),
        samples=top_samples(echantillons, MAX_SAMPLES),
        subjects=tuple(mot for mot, _ in manques),
        counts_terms=False,
    )


# ---------------------------------------------------------------------------
# Rendu d'appoint
# ---------------------------------------------------------------------------


def _dominant(counter: Counter[str]) -> str:
    """Valeur la plus fréquente d'un compteur.

    Args:
        counter: Compteur à réduire.

    Returns:
        La valeur dominante, `—` si le compteur est vide.
    """
    if not counter:
        return "—"
    return counter.most_common(1)[0][0] or "—"


def _format_counter(counter: Counter[str]) -> str:
    """Rend un compteur en une ligne lisible.

    Args:
        counter: Compteur à rendre.

    Returns:
        Les valeurs et effectifs, du plus fréquent au moins fréquent.
    """
    return ", ".join(f"{valeur or '—'} ×{n}" for valeur, n in counter.most_common())


def _notes(
    source: AuditSource,
    par_chunk: Mapping[str, Sequence[LLMTermeGlossary]],
    usages: Mapping[str, _TermUsage],
) -> tuple[str, ...]:
    """Limites de mesure à afficher en fin de rapport.

    Args:
        source: Cache audité.
        par_chunk: Termes émis, par chunk.
        usages: Usage par terme.

    Returns:
        Les notes applicables.
    """
    notes: list[str] = [
        "Les lignes malformées rejetées au parsing par `LLMGlossaryModel` "
        "n'apparaissent pas dans le cache : leur nombre n'est pas mesurable ici, "
        "seuls les logs du run les portent.",
    ]

    seuil = converged_weight()
    if par_chunk and len(par_chunk) < seuil:
        notes.append(
            f"**Livre trop court pour la convergence** : {len(par_chunk)} chunks "
            f"pour un poids de convergence de {seuil}. Un terme ne pouvant être "
            "émis qu'une fois par chunk, aucun ne peut atteindre la confiance "
            "haute sur ce run. Tous restent donc « à arbitrer », et le prompt "
            "leur demande d'être réémis à chaque chunk : la réémission observée "
            "ici est prescrite, pas fautive. Les tendances de sur-extraction "
            "restent lisibles ; la stabilisation, non."
        )
    elif usages and not any(_has_converged(u) for u in usages.values()):
        notes.append(
            f"Aucun terme n'atteint le poids de convergence ({seuil}) : la sortie "
            "attendue n'a jamais eu de « termes validés » à exclure."
        )
    if source.epub_path is None:
        notes.append(
            "Aucun EPUB source résolu : densité, ancrage, détection de nom propre "
            "et candidats manqués ont été omis."
        )
    if not par_chunk:
        notes.append("Aucun chunk de glossaire trouvé dans ce cache.")
    return tuple(notes)
