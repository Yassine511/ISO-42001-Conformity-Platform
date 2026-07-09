# Règles de notation du pipeline (M6) — GELÉES AVANT TOUT RUN HOLDOUT

Ce document complète le contrat d'évaluation gelé (`scripts/chat_eval_generate.py`,
`corpus/gold/chat_eval_rubric.md`) pour le volet **pipeline** : exactitude des verdicts,
précision/rappel d'abstention et **diagnostic de la porte de vérification**. Son sha256 est
inscrit dans chaque artefact de run et rapporté avec les résultats M6. Toute modification
antérieure au run holdout doit être signalée dans le rapport.

## 1. Étiquette système et politique d'infrastructure

- Un constat `VERIFIED` porte l'étiquette de son verdict (`compliant` / `partial` /
  `non_compliant`). `VERIFIED` avec verdict `missing` est structurellement impossible
  (vérifié empiriquement ; toute occurrence est un bug bloquant).
- Un constat `ABSTAINED` pour raison **évidentiaire** (`model_abstained`,
  `verification_failed`, `fuzzy_citation`, `low_confidence`) porte l'étiquette `abstained`.
- Un constat `ABSTAINED` pour raison **d'infrastructure** (`llm_error`, `rate_limited`) est
  classé `infra_failed` : jamais noté, jamais supprimé.

**Politique de recouvrement (bornée, prédéclarée)** : la première passe est scellée intégralement
(y compris les échecs). Ensuite, **exactement UNE tentative de recouvrement** par item échoué,
selon le mode d'échec :
- assessment resté `RUNNING` (échec opérationnel sans constat) → **une reprise** ;
- constat d'infrastructure terminal, ou assessment `FAILED` → **un nouvel assessment de
  recouvrement** ne contenant que les exigences échouées, avec filiation parent→recouvrement
  enregistrée (une reprise ne peut pas les rejouer : idempotence terminale par
  (assessment, exigence)) ;
- pour le chat : échec de service sans ligne persistée → **une re-demande**, consignée au
  registre d'erreurs du runner.

Disponibilité première passe et résultats post-recouvrement sont rapportés séparément.

**Dénominateurs distincts** : `N` (= 14 holdout / 51 dev) est le dénominateur de
disponibilité/couverture — les items `infra_failed` y figurent comme catégorie propre ;
`n_scored = N − infra_failed − sans_constat` est le dénominateur de toutes les métriques de
qualité, toujours publié à côté de `N`. Ids d'assessments et compteurs de recouvrement rapportés.

## 2. Exactitude des verdicts

Un item est correct si et seulement si :
- verdict gold ≠ `missing` **et** constat `VERIFIED` **et** verdict système = verdict gold ; ou
- verdict gold = `missing` **et** étiquette `abstained`.

Tout le reste est incorrect — y compris un `VERIFIED` au mauvais verdict et toute abstention
évidentiaire sur un item gold non-`missing`. Rapporté : global, par verdict gold, et matrice
de confusion 4×4 (système `compliant`/`partial`/`non_compliant`/`abstained` × gold quatre
verdicts).

## 3. Précision / rappel d'abstention

- précision = |abstentions sur gold `missing`| / |abstentions évidentiaires| ;
- rappel = |abstentions sur gold `missing`| / |gold `missing` parmi les items notés|
  (dev : 8 ; test : 3).

## 4. Diagnostic de la porte de vérification

**Dénomination stricte** : « diagnostic de la porte de vérification » (intégrité des citations
de premier jet + issues de la porte) — jamais « taux d'hallucination avec/sans vérificateur »,
jamais « pipeline sans vérificateur ». Un constat `VERIFIED` exige structurellement la même
localisation exacte : le taux post-porte de 0 % est un **contrôle d'invariant** (vérifié
empiriquement ; toute valeur non nulle est un bug bloquant), pas un résultat empirique.
Le rapport peut dire que la porte a **bloqué N citations de premier jet non localisables** ;
il ne peut PAS affirmer une « réduction d'hallucination » mesurée — cela exigerait un
évaluateur indépendant ou un vrai run sans vérificateur, hors périmètre et dit comme tel.

Méthode : le premier jet (tentative 1) est récupéré depuis `assessment_attempts` /
`llm_calls.raw_response` (le contenu même du dernier appel SUCCESS) et re-vérifié hors ligne
avec le MÊME module `verifier` contre l'instantané `retrieved` persisté du constat.

Une assertion de premier jet est **non étayée** ssi `find_quote_in_retrieved` ne trouve rien
ou seulement une correspondance non exacte (fuzzy), ou si la citation est nulle / hors bornes
alors qu'un verdict ≠ `missing` est affirmé. Rapporté, chaque dénominateur nommé :

- intégrité premier jet : exact / fuzzy-seul / introuvable / nulle-ou-invalide, sur les
  **premiers jets analysables et affirmants** et sur **tous les items du split** (`N`) ;
- issues de la porte : réparé (tentative 2 vérifiée) / abstenu / vérifié ;
- assertions finales affichées non étayées / **tous les items** — 0 attendu par invariant ;
- taux compagnons : échec d'analyse tentative 1, premier jet `missing`, usage de la
  réparation, abstention, sortie retenue (`VERIFIED`).

La provenance fournisseur/modèle par tentative provient des lignes `llm_calls` de la tentative
utilisée — `Finding.final_model` décrit la tentative finale et n'est jamais utilisé pour la
tentative 1.

## 5. Statistiques d'appui

Taux `VERIFIED`, usage de la réparation (attempts = 2), distributions des raisons d'abstention
et des méthodes de correspondance, télémétrie de confiance (valeurs brutes, `VERIFIED` corrects
vs incorrects — n trop petit pour toute affirmation de calibration).

## 6. Publication

Chaque pourcentage est publié avec ses comptes bruts et un intervalle de Wilson à 95 % ;
dev et holdout ne sont jamais agrégés. **Réserve Wilson pour les paires claim–citation** :
les paires d'une même question sont corrélées — l'intervalle par paire est étiqueté
*descriptif approché* ; comptes bruts et macro-moyenne par question publiés à côté.

## 7. Empreintes rapportées

Le rapport lie les résultats aux états exacts des fichiers : sha256 de ce document, du
générateur, de la rubrique, du gold, de la KB, des jeux de questions générés et des sources
de l'évaluateur (`backend/app/eval/` + les trois scripts `eval_*`). Un run holdout exige
`HEAD == m6-freeze` et un arbre de travail propre hors `eval/m6/runs/<run_id>/`.
