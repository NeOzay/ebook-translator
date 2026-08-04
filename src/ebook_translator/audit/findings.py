"""
Types de sortie communs à tous les auditeurs de phase.

Un auditeur ne rend pas un verdict : il rend des **constats**. Une `Metric` porte
un chiffre, une `Observation` porte une catégorie d'écart et ses exemples. Aucun
seuil GO/NO-GO n'est appliqué ici — la référence d'une phase est son cahier des
charges en prose (`audit/specs/<phase>.md`), et c'est l'agent auditeur qui
tranche, pas un nombre codé en dur.

La raison est empirique : « 48 termes de glossaire » n'est ni bon ni mauvais dans
l'absolu, cela dépend du livre. En revanche « 24 de ces termes s'ouvrent par un
article » est un fait, et la liste des 24 permet de juger sur pièces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ebook_translator.pipeline.base import PhaseName


@dataclass(frozen=True)
class Metric:
    """Un chiffre mesuré sur la sortie d'une phase.

    Attributes:
        label: Libellé humain, affiché tel quel dans le rapport.
        value: Valeur mesurée.
        unit: Unité facultative (`termes`, `%`, `pour 1000 mots`).
        detail: Précision facultative sur le mode de calcul ou ses limites.
    """

    label: str
    value: float | int
    unit: str = ""
    detail: str = ""

    def rendered_value(self) -> str:
        """Valeur formatée pour le rapport.

        Returns:
            Les entiers sans décimale, les flottants à deux décimales, suivis de
            l'unité quand elle est renseignée.
        """
        nombre = (
            f"{self.value:.2f}" if isinstance(self.value, float) else str(self.value)
        )
        return f"{nombre} {self.unit}".strip()


@dataclass(frozen=True)
class Sample:
    """Un cas concret illustrant une observation.

    Attributes:
        subject: Ce sur quoi porte le cas (un terme, un index de fragment).
        evidence: Ce qui a été observé, en une ligne.
        context: Contexte facultatif (extrait source, chunks concernés).
    """

    subject: str
    evidence: str
    context: str = ""


@dataclass(frozen=True)
class Observation:
    """Une catégorie d'écart relevée, avec ses exemples.

    C'est l'unité du catalogue d'erreurs : le rapport regroupe les observations
    par effectif décroissant, ce qui fait remonter les erreurs les plus
    fréquentes de la phase — celles qui valent un ajustement de prompt.

    Une observation d'effectif nul est conservée : « zéro cas » est un résultat,
    et la faire disparaître du rapport la rend indiscernable d'une catégorie
    non mesurée.

    Attributes:
        category: Identifiant court et stable de la catégorie.
        title: Libellé humain.
        description: Ce que la catégorie sanctionne, et sa part d'incertitude.
        count: Effectif total, qui peut dépasser le nombre d'échantillons retenus.
        samples: Exemples retenus, bornés par l'auditeur.
        subjects: Tous les sujets concernés, y compris ceux qu'aucun échantillon
            ne détaille. Sans cette liste, un lecteur du rapport ne peut ni trier
            les faux positifs au-delà des exemples, ni recouper deux catégories.
        counts_terms: Vrai quand les sujets sont des termes du glossaire. Faux
            pour les catégories qui portent sur autre chose (`candidat-manque`
            désigne des mots de la source, absents du glossaire par définition).
    """

    category: str
    title: str
    description: str
    count: int
    samples: tuple[Sample, ...] = ()
    subjects: tuple[str, ...] = ()
    counts_terms: bool = True

    def undetailed_subjects(self) -> tuple[str, ...]:
        """Sujets concernés qu'aucun échantillon ne détaille.

        Returns:
            Les sujets absents des échantillons retenus, dans l'ordre d'origine.
        """
        detailles = {sample.subject for sample in self.samples}
        return tuple(sujet for sujet in self.subjects if sujet not in detailles)


@dataclass(frozen=True)
class AuditFindings:
    """Résultat complet de l'audit d'une phase.

    Attributes:
        phase: Phase auditée.
        spec_name: Nom du cahier des charges à remettre à l'agent, sans extension.
        metrics: Chiffres mesurés, dans l'ordre de lecture voulu.
        observations: Catalogue d'erreurs, ordre libre — le rapport le trie.
        notes: Limites de mesure et remarques, affichées en fin de rapport.
    """

    phase: PhaseName
    spec_name: str
    metrics: tuple[Metric, ...] = ()
    observations: tuple[Observation, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def ranked_observations(self) -> tuple[Observation, ...]:
        """Observations classées par effectif décroissant.

        Les ex æquo sont départagés par catégorie, pour que deux exécutions sur
        le même cache produisent le même rapport.

        Returns:
            Les observations triées.
        """
        return tuple(sorted(self.observations, key=lambda o: (-o.count, o.category)))

    def affected_subjects(self) -> frozenset[str]:
        """Union des sujets relevés par les catégories portant sur des termes.

        Les catégories ne sont pas disjointes : un même terme peut être compté
        par trois d'entre elles. Sommer les effectifs surestime donc l'ampleur
        de l'écart ; c'est cette union qui la donne.

        Returns:
            Les sujets touchés par au moins une observation `counts_terms`.
        """
        return frozenset(
            sujet
            for observation in self.observations
            if observation.counts_terms
            for sujet in observation.subjects
        )


def top_samples(samples: Sequence[Sample], limit: int) -> tuple[Sample, ...]:
    """Retient les premiers échantillons d'une liste.

    Args:
        samples: Échantillons candidats, déjà ordonnés par pertinence.
        limit: Nombre maximum à conserver.

    Returns:
        Les `limit` premiers échantillons.
    """
    return tuple(samples[:limit])
