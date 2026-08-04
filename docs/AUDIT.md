# Audit d'une phase contre son cahier des charges

Vérifier qu'une phase du pipeline fait **son** travail, indépendamment de toute autre
configuration.

```bash
uv run ebook-audit "bench/runs/20260803_210405/work/t05/cache"
# puis, dans Claude Code :
/phase-audit
```

## Utilisation

Un seul argument obligatoire, le **répertoire de cache** ; `--phase` vaut `glossary`
par défaut, seule phase auditée à ce jour.

```bash
uv run ebook-audit <cache_dir> [--phase glossary] [--epub F] [--out D]
```

`ebook-audit` est déclaré en `[project.scripts]`. La forme longue reste équivalente et
fonctionne sans installation du paquet :

```bash
uv run python -m ebook_translator.audit <cache_dir>
```

L'aide (`--help`) se nomme d'après la forme réellement appelée.

### Où est le cache

| Origine du run | Chemin |
| --- | --- |
| Traduction ordinaire | `<dossier de l'EPUB>/.<stem>_cache/` |
| Variante de banc | `bench/runs/<run_id>/work/<variant_id>/cache/` |

### Options

- `--epub <fichier>` — force l'EPUB source. Par défaut il est déduit du répertoire
  parent du cache, les fichiers portant `[traduit]` étant écartés (ce sont des
  sorties). Sans EPUB résolu, tout ce qui se mesure contre le texte est **omis** —
  voir plus bas.
- `--out <répertoire>` — déplace la sortie. Par défaut
  `audit/runs/<horodatage>-<phase>/`, ignoré par git comme `bench/runs/`.
- `--phase <nom>` — refuse toute valeur hors de la liste, avec les valeurs acceptées.

### Lire la sortie console

```
Audit « glossary » écrit dans audit/runs/20260804_184913-glossary
  17 métrique(s) — voir audit/runs/20260804_184913-glossary/metrics.md
  7 catégorie(s) d'écart :
       28  nom-commun-article
       25  ancrage-faible
        0  redondance
  ! Livre trop court pour la convergence : 4 chunks pour un poids de convergence de 5. …
Verdict : /phase-audit sur audit/runs/20260804_184913-glossary
```

Trois lectures à ne pas confondre :

| Ce qu'on voit | Ce que ça veut dire |
| --- | --- |
| Un effectif `> 0` | Des cas relevés, à trier — les heuristiques ont des faux positifs |
| Un effectif `0` | Le signal a été **cherché et non trouvé** |
| Une catégorie **absente** de la liste | Elle n'était **pas mesurable** ; la raison est dans une ligne `!` |

Les lignes `!` sont les limites de mesure, reprises telles quelles du rapport.

Codes de sortie : `0` si l'audit aboutit, `1` si le cache est introuvable ou si la
phase n'a rien écrit — le message part alors sur `stderr`, et la commande liste les
phases effectivement présentes dans ce cache.

### Puis le verdict

La commande mesure, elle ne juge pas. L'interprétation revient à l'agent :

```
/phase-audit                                   # dernier run de banc, variante demandée s'il y en a plusieurs
/phase-audit bench/runs/<id>/work/<v>/cache    # cache précis
```

Le skill enchaîne les deux étapes et l'agent `phase-auditor` écrit `verdict.md` dans le
même répertoire. Comme l'audit ne coûte rien, le rejouer après un changement de prompt
est la boucle de travail normale.

## Pourquoi pas le banc d'essais

[docs/BENCH.md](BENCH.md) compare N variantes sur un même livre et les classe. C'est
la bonne question quand on choisit une température ou un modèle. Ce n'en est pas une
quand on veut savoir si une phase remplit son rôle : deux variantes également
mauvaises se départagent quand même sur un banc comparatif.

| | Banc d'essais | Audit |
| --- | --- | --- |
| Question | Laquelle est la meilleure ? | Est-ce que ça fait le travail ? |
| Référence | Les autres variantes | Le cahier des charges de la phase |
| Entrée | Un run de banc complet | N'importe quel cache de pipeline |
| Appels LLM | Un run par variante | Aucun |
| Sortie | Classement argumenté | Écarts instruits, ajustements de prompt |

## Ce que produit un audit

```
audit/runs/<horodatage>-<phase>/
  report.md      # chiffres + catalogue d'erreurs classé par effectif décroissant
  metrics.md     # les mêmes chiffres, seuls
  spec.md        # cahier des charges de la phase, recopié
  manifest.json  # cache audité, EPUB, horodatage, compteurs
  verdict.md     # écrit par l'agent phase-auditor
```

La spec est **recopiée**, pas référencée : l'agent démarre à contexte vide et ne doit
rien avoir à chercher.

## Aucun seuil, et c'est délibéré

Les métriques ne portent pas de GO/NO-GO. « 48 termes de glossaire » n'est ni bon ni
mauvais dans l'absolu — cela dépend du livre. En revanche « 28 de ces termes s'ouvrent
par un article sans jamais porter de capitale en milieu de phrase » est un fait, et la
liste des 28 permet de juger sur pièces.

Un seuil chiffré aurait exigé d'être recalibré à chaque livre ; un jeu d'entités
annoté à la main n'aurait servi qu'un seul texte. La référence est donc en prose, dans
`src/ebook_translator/audit/specs/<phase>.md`, et le jugement revient à l'agent.

Corollaire : **les catégories heuristiques contiennent des faux positifs par
construction**. `the Thames` porte un article et reste une entité nommée. Chaque
catégorie du rapport le dit dans sa description, et l'agent doit annoncer combien il
écarte.

## L'auditeur du glossaire

Rôle attendu de la phase : fournir un **nom stable pour les éléments importants** du
texte — personnages, lieux nommés, objets récurrents — et non une traduction pour
chaque terme rencontré.

Matière lue : les charges du store v2 (`cache/glossary/_v2/glossary_*.json`, une liste
de termes par chunk), avec repli sur les tables de revue `chunk N.md`, plus l'EPUB
source déduit du répertoire parent du cache.

| Catégorie | Ce qu'elle relève |
| --- | --- |
| `nom-commun-article` | Article de tête et aucune capitale en milieu de phrase dans la source |
| `sans-marque-nom-propre` | Jamais capitalisé ailleurs qu'en tête de phrase |
| `ancrage-faible` | Moins de deux occurrences dans le livre entier |
| `redondance` | Terme réémis **après** avoir atteint la confiance haute, donc listé au prompt sous « NE PAS inclure » |
| `traduction-instable` | Plusieurs propositions pour un même terme source |
| `classement-instable` | `type` ou `sexe` divergents — le sexe porte les accords en français |
| `candidat-manque` | Entité capitalisée récurrente qu'aucun terme ne couvre |

Le décompte d'occurrences porte sur le terme **privé de son article** : `the cellar`
n'apparaît nulle part dans *The Yellow Wallpaper*, mais `cellar` y figure une fois.
Compter la forme complète aurait produit des zéros trompeurs.

Sans EPUB source résolu, les quatre premières catégories et la densité sont **omises**
plutôt que calculées sur une base fausse ; les mesures de cohérence interne restent.

Une catégorie **mesurée mais sans cas** figure au catalogue avec un effectif de `0` :
c'est un résultat, et la faire disparaître la rendrait indiscernable d'une catégorie
non mesurable. Les catégories réellement omises sont, elles, listées en « Limites de
mesure ».

Les catégories **ne sont pas disjointes** : un terme peut être compté par trois d'entre
elles. Sommer les effectifs surestime donc l'écart ; la métrique « Termes touchés par au
moins une observation » donne l'ampleur réelle. Chaque catégorie nomme aussi ses cas
au-delà des exemples détaillés, pour que les faux positifs se trient sans retourner au
cache.

### Convergence du glossaire

La confiance d'un terme vaut `dominance × masse`, avec `masse = w / (w + 2)`
([glossary.py](../src/ebook_translator/glossary.py)). Deux seuils en découlent, tous deux
exposés en métrique :

- **poids de réinjection** (3) — en deçà, le terme n'est pas montré au LLM au chunk
  suivant ;
- **poids de convergence** (5, unanimité parfaite) — au-delà, le terme passe en
  « Termes validés — NE PAS inclure ».

Un terme n'étant émis qu'une fois par chunk, **un livre de moins de 5 chunks de
glossaire ne fait converger aucun terme** : tout y est réémis à chaque chunk, sur
demande explicite du prompt. Le rapport le signale alors en « Limites de mesure », et
`redondance` reste à zéro — c'est le bon résultat, pas un angle mort.

## Ajouter l'auditeur d'une phase

1. Écrire une classe conforme au protocole `PhaseAuditor`
   ([audit/auditor.py](../src/ebook_translator/audit/auditor.py)) : `phase`,
   `spec_name`, `run(source) -> AuditFindings`.
2. Rendre des `Metric` et des `Observation`
   ([audit/findings.py](../src/ebook_translator/audit/findings.py)). Une observation
   porte son effectif **et** ses exemples : le chiffre seul ne se juge pas.
3. Écrire `audit/specs/<phase>.md` — rôle, ce qui a sa place et ce qui n'en a pas,
   erreurs typiques, et la section « Ce que les métriques ne tranchent pas ».
4. Enregistrer la classe dans `get_auditor()` et `audited_phases()`.

Le socle — résolution de source, rapport, CLI, agent — ne change pas.

## Notes d'architecture

- **Aucun appel LLM.** `AuditSource`
  ([audit/source.py](../src/ebook_translator/audit/source.py)) ne lit que le disque.
  Un audit se rejoue autant de fois que voulu sans coût.
- **Deux couches de store.** Chaque dossier de phase porte le `Store` legacy à la
  racine et le `FileByteStore` v2 dans `_v2/` ; le v2 fait foi, comme dans
  `bench.collect.read_translations`.
- **EPUB déduit.** Le pipeline et le banc posent tous deux l'EPUB source dans le
  répertoire parent du cache. Les fichiers portant `[traduit]` sont écartés : ce sont
  des sorties.
- **Portée d'un run.** Le catalogue d'erreurs décrit un cache, sans cumul inter-runs.

## Limites connues

- Un seul auditeur écrit : la phase glossaire.
- Les lignes malformées rejetées au parsing par `LLMGlossaryModel` n'atteignent jamais
  le cache : leur nombre n'est pas mesurable ici, seuls les logs du run les portent.
- La détection de nom propre est lexicale et calibrée sur l'anglais : elle repose sur
  la capitalisation en milieu de phrase.
- `candidat-manque` remonte des mots capitalisés ; les titres et les débuts de
  dialogue y font du bruit.
