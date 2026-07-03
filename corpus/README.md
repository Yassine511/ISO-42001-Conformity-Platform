# Corpus M1b — Base de connaissances ISO 42001, documents Lumen AI et gold set

Ce dossier contient le livrable du jalon **M1b** : tout ce que les jalons aval consomment
(M2 indexation, M3 jugement/vérification, M6 évaluation).

## Contenu

| Chemin | Rôle |
|--------|------|
| `kb/iso42001_kb.json` | 65 exigences **paraphrasées** de l'ISO/IEC 42001:2023 (clauses 4–10 + Annexe A A.2–A.10, contrôles A.2.2 → A.10.4), en français — atomiques sauf les trois entrées agrégées ci-dessous |
| `documents/*.md` | Les 6 politiques de l'organisation fictive **Lumen AI** (français), avec des écarts volontairement semés |
| `gold/gold_labels.json` | 65 vérités terrain (couverture 100 % de la KB) : verdict + citation d'évidence verbatim — c'est le gold set de l'évaluation M6 |

**Granularité de la KB** : `7.5`, `9.2` et `9.3` sont représentées chacune par une entrée unique
(plutôt que leurs sous-clauses 7.5.1–7.5.3, 9.2.1–9.2.2, 9.3.1–9.3.3) — un choix assumé de
granularité : ces sous-clauses se testent naturellement ensemble sur un corpus documentaire.
Le découpage en obligations atomiques plus fin (manifeste d'obligations avec relecture
indépendante) est nommé comme travail futur dans le rapport.

## Règle de droit d'auteur

Le texte de l'ISO/IEC 42001 est protégé : la KB ne contient **que des paraphrases dans nos
propres mots**, chaque entrée ne portant qu'une *référence* de clause (ex. `A.7.2`). Le
validateur rejette toute paraphrase > 400 caractères (garde-fou anti-verbatim). Les citations
verbatim ne concernent que les documents Lumen AI, que nous avons rédigés.

## Sémantique des verdicts

- **compliant** — une disposition explicite et complète couvre l'exigence ;
- **partial** — une disposition existe mais avec une lacune délibérée (ex. revue « si nécessaire »
  sans intervalle planifié, formation sur la base du volontariat) ;
- **non_compliant** — le document contredit ou exclut explicitement l'exigence
  (ex. provenance des données « non exigée », impacts sociétaux « exclus du périmètre ») ;
- **missing** — aucune couverture nulle part dans le corpus : la bonne réponse du système est
  l'**abstention**. 11 exigences sont volontairement absentes : A.4.4, A.4.5, A.4.6, A.6.2.7,
  A.8.3, A.8.5, 6.3, 7.1, 7.5, 9.2, 10.2.

Répartition actuelle : 26 compliant · 24 partial · 4 non_compliant · 11 missing.

**Sémantique de l'ancre d'évidence** : `evidence_quote_fr` est l'ancre de récupération et de
vérification — la citation minimale attendue — pas la totalité de la preuve. Le verdict est
établi par les auteurs sur l'ensemble du corpus. La métrique d'hallucination M6 porte sur
l'existence verbatim des citations *produites par le système*, pas sur cette ancre.

## Partition dev / test

Chaque cas gold porte un champ `split` :

- **dev** — utilisable pour régler les prompts, la récupération et les seuils (M2–M5) ;
- **test** (~25 %, stratifié par verdict) — **réservé au rapport M6** : jamais consulté pour
  un réglage, afin que le chiffre final ne soit pas sur-ajusté.

**Limite assumée** : ce découpage est un *holdout d'étiquettes*, pas une preuve de
généralisation — les mêmes six documents alimentent les deux splits. Le validateur garantit
seulement qu'aucune citation identique n'apparaît dans les deux. Une preuve de généralisation
exigerait une seconde organisation jamais vue (travail futur, cf. rapport).

`corpus_version` (identique dans la KB et le gold, vérifié par le validateur) fige la version
du corpus utilisée pour chaque run d'évaluation rapporté.

## Contrat du gold set

`evidence_quote_fr` est une **sous-chaîne verbatim** (≤ 300 caractères, comparaison après
normalisation Unicode NFC uniquement) du document source. C'est ce qui rend la métrique
d'hallucination de M6 exacte. Les documents utilisent volontairement une typographie
française réaliste (apostrophes typographiques, guillemets « », accents) pour éprouver le
normalisateur de citations de M3.

## Validation

```bash
backend/.venv/Scripts/python scripts/validate_corpus.py   # rapport + code retour
backend/.venv/Scripts/python -m pytest                    # inclut backend/tests/test_corpus.py
```

Vérifications : unicité des ids KB, domaines valides, garde anti-verbatim, chaque
`requirement_id` du gold présent dans la KB, chaque citation retrouvée exactement dans son
document, cohérence verdict/document/citation, chaque document référencé au moins une fois.

**Règle d'édition** : toute modification d'un document doit être suivie du validateur — une
citation cassée du gold set est une erreur bloquante, pas un avertissement.
