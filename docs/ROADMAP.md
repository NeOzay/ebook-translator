# Roadmap - Améliorations futures

Ce document consolide toutes les améliorations futures planifiées (Phase 2 - non implémentées) issues de l'historique des versions.

Pour la dette **constatée dans le code** — ce qui existe et pose problème, par opposition à ce qui n'existe pas encore — voir [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md).

> **Statut** : Toutes les fonctionnalités listées ci-dessous sont **NON IMPLÉMENTÉES**. Elles représentent des idées d'amélioration envisagées pour les versions futures.

## Par priorité

### Haute priorité

#### 1. Validation post-traduction (v0.4.0)

- [ ] Vérification cohérence terminologique (détection même source → traductions différentes)
- [ ] Détection noms propres non traduits (ex: "Sakamoto" → "Sakamoto" ✅)
- [ ] Détection segments restés en langue source
- [ ] Vérification cohérence stylistique (pas de mélange registres)

**Impact attendu** : +15-25% de qualité globale

#### 2. Contexte avancé (v0.4.0)

- [ ] Système de métadonnées contextuelles (personnages, lieux, relations)
- [ ] Glossaire automatique des noms propres et termes techniques
- [ ] Cache sémantique (détecter phrases similaires → réutiliser traductions)
- [ ] Résumé du chapitre précédent pour continuité narrative

**Impact attendu** : +20-30% de cohérence narrative

#### 3. Optimisation overlap (v0.7.0)

- [ ] Overlap adaptatif (augmenter/réduire selon détection incohérence)
- [ ] Compression du contexte (résumé du head si trop grand)
- [ ] Cache sémantique (éviter de retransmettre contexte similaire)

**Impact attendu** : -30-50% de coût tokens

#### 4. Tests complets (v0.7.0)

- [ ] Tests unitaires complets pour chunk_queue
- [ ] Tests de régression pour overlap < 1.0
- [ ] Tests de performance avec gros EPUBs (10MB+)

**Impact attendu** : +95%+ de couverture de tests

### Moyenne priorité

#### 5. Stratégies de fallback (v0.3.0)

- [ ] Stratégie de fallback configurable (garder l'original, marquer visuellement)
- [ ] Mode de reprise `--resume` pour relancer les chunks échoués
- [ ] Statistiques détaillées en fin de traduction
- [ ] Rapport HTML des zones problématiques

**Impact attendu** : +10-15% de robustesse

#### 6. Gestion avancée des logs (v0.6.0)

- [ ] Rotation automatique (garder N dernières sessions)
- [ ] Compression des anciennes sessions (.tar.gz)
- [ ] Indexation pour recherche rapide (grep optimisé)
- [ ] Dashboard HTML pour visualiser les sessions

**Impact attendu** : +30-50% d'efficacité de déboggage

#### 7. Métriques et monitoring (v0.6.0)

- [ ] Statistiques par session (temps, tokens, erreurs)
- [ ] Graphes de performance (temps par chunk, retry rate)
- [ ] Export vers formats structurés (JSON, SQLite)

**Impact attendu** : +40-60% de traçabilité

#### 8. Tooling templates (v0.9.0)

- [ ] Script de migration automatique pour nouveaux templates
- [ ] Linter pour détecter règles communes hardcodées
- [ ] Générateur de templates à partir de specs

**Impact attendu** : +50-70% de productivité (développement)

#### 9. Documentation templates (v0.9.0)

- [ ] Guide de contribution pour templates
- [ ] Catalogue des règles communes disponibles
- [ ] Exemples de templates personnalisés

**Impact attendu** : +30-50% de facilité d'adoption

### Basse priorité

#### 10. Tuning avancé LLM (v0.4.0)

- [ ] Expérimentation avec `top_p` et `frequency_penalty`
- [ ] Tests avec modèles spécialisés traduction (ex: NLLB, M2M100)
- [ ] A/B testing température (0.3 vs 0.5 vs 0.7)

**Impact attendu** : +5-10% de qualité (selon modèle)

#### 11. Intégration logs (v0.6.0)

- [ ] Logs centralisés (syslog, journald)
- [ ] Webhooks pour alertes en temps réel
- [ ] Intégration avec outils de monitoring (Grafana, Prometheus)

**Impact attendu** : Dépend de l'environnement de production

#### 12. Optimisation templates (v0.9.0)

- [ ] Cache de rendu des templates communs (éviter re-parsing)
- [ ] Validation automatique des includes manquants
- [ ] Détection de duplication dans les templates spécifiques

**Impact attendu** : +10-20% de performance (rendu)

#### 13. Validation automatique overlap (v0.7.0)

- [ ] Détection de l'utilité de l'overlap (mesurer impact sur cohérence)
- [ ] Recommandation automatique du ratio optimal selon le type de texte
- [ ] Plafond configurable pour éviter coûts excessifs

**Impact attendu** : -20-30% de coût tokens (optimisation)

## Par domaine fonctionnel

### Qualité des traductions

**Fonctionnalités** :
- Validation post-traduction (détection incohérences, segments non traduits)
- Contexte avancé (métadonnées, glossaire, cache sémantique)
- Tuning avancé LLM (top_p, frequency_penalty, modèles spécialisés)

**Impact global attendu** : **+30-40% de qualité** | **Priorité HAUTE**

### Performance et coûts

**Fonctionnalités** :
- Optimisation overlap (adaptatif, compression, cache)
- Validation automatique overlap (recommandation ratio optimal)

**Impact global attendu** : **-30-50% de coût tokens** | **Priorité HAUTE**

### Robustesse et fiabilité

**Fonctionnalités** :
- Stratégies de fallback (mode reprise, rapports HTML)
- Tests complets (chunk_queue, régression, performance)

**Impact global attendu** : **+15-25% de robustesse** | **Priorité HAUTE-MOYENNE**

### Observabilité et déboggage

**Fonctionnalités** :
- Gestion avancée des logs (rotation, compression, dashboard HTML)
- Métriques et monitoring (statistiques, graphes, export)
- Intégration logs (syslog, webhooks, Grafana)

**Impact global attendu** : **+40-60% d'efficacité de déboggage** | **Priorité MOYENNE**

### Maintenabilité et développement

**Fonctionnalités** :
- Tooling templates (migration, linter, générateur)
- Documentation templates (guide, catalogue, exemples)
- Optimisation templates (cache, validation, détection duplication)

**Impact global attendu** : **+50-70% de productivité dev** | **Priorité MOYENNE-BASSE**

## Impact global estimé

Si toutes les améliorations **haute priorité** sont implémentées :

| Aspect | Amélioration attendue | Confiance |
|--------|----------------------|-----------|
| **Qualité des traductions** | +30-40% | Élevée |
| **Cohérence terminologique** | +40-50% | Élevée |
| **Coût tokens** | -30-40% | Moyenne-Élevée |
| **Robustesse** | +20-30% | Élevée |
| **Maintenabilité** | +50-70% | Élevée |
| **Efficacité de déboggage** | +40-60% | Moyenne-Élevée |

**Total attendu** : **+35-45% de qualité globale** avec **-25-35% de coût**

## Recommandations d'implémentation

### Phase 2.1 (court terme - 2-3 mois)

**Focus** : Qualité et robustesse

1. Validation post-traduction (v0.4.0) - 2-3 semaines
2. Tests complets (v0.7.0) - 1-2 semaines
3. Stratégies de fallback (v0.3.0) - 1 semaine

**Résultat attendu** : +20-30% qualité, +15-20% robustesse

### Phase 2.2 (moyen terme - 3-6 mois)

**Focus** : Performance et contexte

1. Contexte avancé (v0.4.0) - 3-4 semaines
2. Optimisation overlap (v0.7.0) - 2-3 semaines
3. Gestion avancée des logs (v0.6.0) - 1-2 semaines

**Résultat attendu** : +20-30% cohérence narrative, -25-35% coût tokens

### Phase 2.3 (long terme - 6-12 mois)

**Focus** : Observabilité et tooling

1. Métriques et monitoring (v0.6.0) - 2-3 semaines
2. Tooling templates (v0.9.0) - 2-3 semaines
3. Documentation templates (v0.9.0) - 1 semaine

**Résultat attendu** : +40-60% efficacité déboggage, +50-70% productivité dev

## Voir aussi

- [ARCHITECTURE.md](ARCHITECTURE.md) - Architecture globale du système
- [VALIDATION.md](VALIDATION.md) - Architecture de validation
- [TEMPLATES.md](TEMPLATES.md) - Architecture des templates LLM
- [CHANGELOG.md](CHANGELOG.md) - Historique des versions implémentées (à partir de 0.12.0)
- [CHANGELOG_ARCHIVE.md](CHANGELOG_ARCHIVE.md) - Historique 0.2.0 → 0.11.0
