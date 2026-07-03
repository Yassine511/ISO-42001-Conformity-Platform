# Corpus M1b — Base de connaissances ISO 42001, documents Lumen AI et gold set

Ce dossier contient le livrable du jalon **M1b** : tout ce que les jalons aval consomment
(M2 indexation, M3 jugement/vérification, M6 évaluation).

## Contenu

| Chemin | Rôle |
|--------|------|
| `kb/iso42001_kb.json` | 58 exigences atomiques **paraphrasées** de l'ISO/IEC 42001:2023 (clauses 4–10 + Annexe A A.2–A.10, contrôles A.2.2 → A.10.4), en français |
| `documents/*.md` | Les 6 politiques de l'organisation fictive **Lumen AI** (français), avec des écarts volontairement semés |
| `gold/gold_labels.json` | 41 vérités terrain : verdict + citation d'évidence verbatim — c'est le gold set de l'évaluation M6 |

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
  l'**abstention**. 7 exigences sont volontairement absentes : A.4.4, A.4.5, A.4.6, A.6.2.7,
  A.8.3, 9.2, 10.2.

Répartition actuelle : 20 compliant · 12 partial · 2 non_compliant · 7 missing.

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
