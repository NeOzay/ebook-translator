# Cahier des charges — phase glossaire

Référence de l'audit. Ce document dit ce que la phase **doit** produire ; le rapport
d'audit dit ce qu'elle **a** produit. L'écart entre les deux est le sujet.

## Rôle

Fournir un **nom stable pour les éléments importants du texte**, de sorte que la
traduction les désigne de la même façon d'un bout à l'autre du livre.

Ce n'est pas un dictionnaire. La phase n'a pas à proposer une traduction pour chaque
terme rencontré : les phases de traduction savent traduire. Elle intervient là où
elles ne peuvent pas trancher seules — quand deux chunks traduits indépendamment
risquent de nommer différemment la même chose.

## Ce qui a sa place au glossaire

- **Personnages** — noms, surnoms, titres attachés à une personne (`weir mitchell`,
  `cousin henry`). Le champ `sexe` compte : il porte les accords en français.
- **Lieux nommés** — toponymes, bâtiments identifiés par un nom propre.
- **Objets récurrents** identifiés comme tels par le texte, quand leur désignation
  fait motif (`the yellow wallpaper` dans la nouvelle du même nom).
- **Références culturelles** que le lecteur cible ne reconnaîtrait pas d'office.

Trois conditions cumulatives : l'élément **revient** dans le livre, sa désignation est
**stable dans la source**, et une traduction naïve **pourrait varier** d'un chunk à
l'autre.

## Ce qui n'y a pas sa place

- **Noms communs génériques**, avec ou sans article : `the bay`, `the cellar`,
  `the garden`, `the lane`, `the village`, `the wharf`, `the estate`. « La cave » ne
  demande pas d'accord préalable entre deux chunks.
- **Termes vus une seule fois** : il n'y a pas de cohérence à préserver.
- **Descriptions** plutôt que désignations (`debased romanesque` décrit un style ; ce
  n'est pas un nom).
- **Termes déjà stabilisés** : un terme en confiance haute est présenté au prompt sous
  « Termes validés — NE PAS inclure ». Le réémettre coûte des tokens sans rien
  stabiliser. Attention : cela ne vaut **que** pour les termes convergés — voir ci-dessous.

## Comment un terme converge

Un terme n'a pas une traduction, il a une **distribution** de propositions, alimentée
une émission à la fois. La confiance vaut `dominance × masse`, où `masse = w / (w + 2)`
plafonne les faibles volumes : même sans le moindre désaccord, il faut **5 émissions**
pour atteindre la confiance haute, et **3** pour que le terme soit seulement réinjecté
dans le prompt du chunk suivant.

Conséquence directe : **réémettre un terme non convergé n'est pas une faute, c'est le
mécanisme**. `glossary_existing_block.jinja` le demande explicitement, sous « Termes à
arbitrer — À inclure dans la sortie ». Un terme ne peut être émis qu'une fois par chunk,
donc un livre de moins de 5 chunks de glossaire ne fait converger **aucun** terme : tout
y est réémis à chaque fois, par construction. Sur un tel run, la stabilisation n'est pas
mesurable — le rapport le signale en « Limites de mesure », et l'audit doit alors se
prononcer sur la sur-extraction seule.

## Contrat de sortie

Une ligne par terme, quatre colonnes séparées par `|`, close par `[=[END]=]` — voir
`LLMGlossaryModel` ([template/phase/glossary_models.py](../../../template/phase/glossary_models.py)).
Les lignes malformées sont écartées au parsing, sans nouvel appel : une ligne perdue
coûte moins qu'un aller-retour de correction.

Cohérence attendue d'un chunk à l'autre : un terme conserve son `type`, son `sexe` et
sa `proposition_traduction`.

## Erreurs typiques

| Erreur | Signe dans le rapport |
| --- | --- |
| Sur-extraction de noms communs | `nom-commun-article`, `sans-marque-nom-propre` |
| Extraction de termes non récurrents | `ancrage-faible` |
| Glossaire qui ne stabilise pas | `traduction-instable` |
| Accords compromis en français | `classement-instable` (sexes divergents) |
| Réémission d'un terme déjà stabilisé | `redondance` |
| Entité importante oubliée | `candidat-manque` |

Une catégorie d'effectif **0** figure au rapport comme les autres : elle dit que le
signal a été cherché et non trouvé. Les catégories réellement non mesurables sur un run
donné (faute de texte source, par exemple) sont absentes du catalogue et signalées en
« Limites de mesure » — ne pas confondre les deux.

Les catégories **ne sont pas disjointes** : un même terme peut être compté par trois
d'entre elles. Sommer les effectifs surestime donc l'écart ; la métrique « Termes touchés
par au moins une observation » donne l'ampleur réelle.

## Ce que les métriques ne tranchent pas

L'audit mesure des signaux, pas de la pertinence. Ces questions restent à l'agent :

1. **Ce terme méritait-il d'être au glossaire ?** Un lieu nommé peut porter un article
   (`the Thames`) ; un objet-motif peut n'être jamais capitalisé. Les catégories
   `nom-commun-article` et `sans-marque-nom-propre` contiennent des faux positifs par
   construction — les trier à la lecture des exemples.
2. **La proposition de traduction est-elle bonne ?** Aucune métrique ne le dit. Une
   traduction stable mais fausse passe tous les tests.
3. **Les oublis signalés sont-ils réels ?** `candidat-manque` remonte des mots
   capitalisés ; les titres et les débuts de dialogue y font du bruit.
4. **Quelle instruction du prompt a produit l'écart dominant ?** C'est la conclusion
   attendue : un ou deux ajustements de `src/template/phase/glossary_system.jinja`,
   pas une liste de souhaits.
