# Rapport d'évaluation M6

Évaluation du copilote de conformité ISO/IEC 42001 sur le corpus gelé (`corpus_version 1.2.0`),
selon le contrat d'évaluation gelé avant M5 (générateur + rubrique) et les règles de notation
pipeline gelées avant le run holdout. Tout pourcentage est publié avec ses comptes bruts et un
intervalle de Wilson à 95 % ; **les résultats dev (diagnostics de développement) et holdout ne
sont jamais agrégés**.

## 1. Provenance du contrat

| Élément | Valeur |
|---|---|
| `corpus_version` | 1.2.0 (gold = KB, vérifié par le préflight) |
| Commit de gel (`m6-freeze`) | `fb3de8f63d560d4cc096aa9a3df80a1db51cebfc` — vérifié par la porte de gel des runners (HEAD = tag, arbre propre hors `eval/m6/runs/holdout/`) |
| Règles de notation (`eval/m6/regles_notation_pipeline.md`) | sha256 `6e5797c293603f61…` |
| Générateur (`scripts/chat_eval_generate.py`) | sha256 `dfd54f7ee0354cc0…` |
| Rubrique (`corpus/gold/chat_eval_rubric.md`) | sha256 `003a6388dddf7eda…` |
| Gold (`corpus/gold/gold_labels.json`) | sha256 `50b530feab1f3294…` |
| KB (`corpus/kb/iso42001_kb.json`) | sha256 `9cb48f13bf5a5650…` |
| Jeu de questions holdout | sha256 `67dbf9246c6fc903…` (14 questions, 3 sans réponse attendue) |
| Modèle juge | `mistral-large-latest` (Mistral) pour les 14 constats et les 14 réponses chat du holdout ; température 0 ; k=6 (pipeline), k=8/4 (chat) ; `JUDGE_429_RETRIES=6`, `JUDGE_429_BASE_DELAY=5` |
| Organisation | « Lumen AI (eval M6) » — exactement les six documents du corpus, checksums vérifiés ; portes M2 re-validées avant gel (policy 0.95/0.86/0.93 ; KB hybride 0.96) |
| Assessments | holdout `cc644bf2…` (première passe complète, aucun recouvrement nécessaire) ; dev `98b703c8…` + recouvrement `85e220e6…` |
| Empreintes des feuilles de notation | vides `73d87aca…`/`f9dfdaaf…`, remplies `4ce3a2c5…`/`3903e7bc…`, liées au run `6c5cb24c…` (ingestion inviolable : seuls `label`/`comment` modifiables) |

**Procédure de notation (écart déclaré à la rubrique §6)** : les labels des paires claim–citation
et de fidélité des réponses ont été **pré-remplis par l'assistant IA (Claude), avec un commentaire
justificatif par ligne, puis revus et acceptés tels quels par l'auteur du projet**. La rubrique
prévoyait une notation directe par l'auteur ; le masquage §4 (structurel dans les feuilles), les
labels d'answerability figés par le gold et les formules d'agrégation gelées restent inchangés.
Cet écart est une limite déclarée (§7).

## 2. Pipeline — holdout (N = 14, n_scored = 14)

Première passe complète : aucun échec d'infrastructure, aucun item sans constat, aucun
recouvrement nécessaire. Aucune violation d'invariant du vérificateur (0 citation affichée non
localisable — contrôle bloquant).

| Métrique | Comptes | % [IC Wilson 95 %] |
|---|---|---|
| **Exactitude des verdicts** | 9/14 | 64,3 % [38,8 %, 83,7 %] |
| — gold `compliant` | 2/4 | 50,0 % [15,0 %, 85,0 %] |
| — gold `partial` | 5/5 | 100 % [56,6 %, 100 %] |
| — gold `non_compliant` | 2/2 | 100 % [34,2 %, 100 %] |
| — gold `missing` | 0/3 | 0 % [0 %, 56,2 %] |
| Taux VERIFIED | 12/14 | 85,7 % [60,1 %, 96,0 %] |
| Précision d'abstention | 0/2 | 0 % [0 %, 65,8 %] |
| Rappel d'abstention (3 gold `missing`) | 0/3 | 0 % [0 %, 56,2 %] |

Matrice de confusion (gold en ligne, système en colonne) :

| gold \ système | compliant | partial | non_compliant | abstained |
|---|---|---|---|---|
| compliant | **2** | 0 | 0 | 2 |
| partial | 0 | **5** | 0 | 0 |
| non_compliant | 0 | 0 | **2** | 0 |
| missing | 0 | 3 | 0 | **0** |

Lecture d'échec : les 5 erreurs sont (a) 2 abstentions `verification_failed` sur des items
`compliant` (le juge n'a pas produit de citation exacte localisable) et (b) **3 verdicts
`partial` sur les 3 items `missing`** — le système a cité des passages authentiques mais
non pertinents pour les trois exigences volontairement non couvertes du split (A.4.4, A.8.3,
7.1). C'est précisément le cas « citation authentique mais hors sujet » que
la vérification de localisation ne peut pas attraper et que la revue humaine (M5) et la
précision de support sémantique (§4) doivent couvrir.

Télémétrie de confiance (seuil non calibré, valeurs brutes) : VERIFIED corrects
0,70–0,99 (n=9) ; VERIFIED incorrects 0,75–0,80 (n=3) — aucune conclusion de calibration
possible à ce n.

## 3. Diagnostic de la porte de vérification — holdout (N = 14)

Intégrité des citations de premier jet (tentative 1, re-vérifiées hors ligne avec le même
module `verifier` contre l'instantané de récupération persisté) puis issues de la porte.
**Ce tableau n'est pas une ablation « avec/sans vérificateur »** : un constat VERIFIED exige
structurellement la localisation exacte, donc le 0 post-porte est un contrôle d'invariant.

| Mesure | Comptes | % [IC 95 %] |
|---|---|---|
| Premiers jets analysables et affirmants | 14/14 | — |
| **Assertions de premier jet non étayées** (citation introuvable) | 3/14 | 21,4 % [7,6 %, 47,6 %] |
| Issues de la porte : vérifié / réparé / abstenu | 12 / 1 / 2 | — |
| Assertions finales affichées non localisables (invariant) | **0**/14 | 0 % — attendu par construction |

La porte a **bloqué 3 citations de premier jet non localisables sur 14** : 1 récupérée par la
réparation bornée (citation exacte au second essai), 2 converties en abstentions routées vers
la revue humaine. Le rapport n'affirme PAS une « réduction d'hallucination » mesurée : le taux
post-porte nul est structurel ; une ablation réelle exigerait un run sans vérificateur ou un
évaluateur indépendant (hors périmètre, travail futur).

Diagnostics dev (n=51, jamais agrégés au holdout) : 5/43 premiers jets affirmants non étayés
(11,6 % [5,1 %, 24,5 %]), 3 premiers jets `missing`, 0 non analysable, 5 sans appel réussi
(pression 429) ; 4 réparations réussies ; 0 violation d'invariant.

## 4. Chat — holdout (N = 14, n_scored = 14 ; 3 questions sans réponse attendue)

Run complet : 14/14 messages persistés, 0 échec sans ligne, 0 abstention d'infrastructure.

**Validité de localisation des citations** (déterministe, rapportée SÉPARÉMENT du support
sémantique, jamais agrégée avec) : **24/24 = 100 % [86,2 %, 100 %]** — conforme à la
construction ; toute régression signalerait un bug du vérificateur. (Dev : 168/168.)

Support sémantique (labels humains-validés selon la procédure du §1 ; PARTIAL = non-support,
rapporté séparément) :

| Métrique | Comptes | % [IC 95 %] |
|---|---|---|
| **Précision de support (paires)** † | 23/32 SUPPORTS | 71,9 % [54,6 %, 84,4 %] |
| — dont PARTIAL | 9/32 | 28,1 % [15,6 %, 45,4 %] |
| — dont IRRELEVANT | 0/32 | 0 % |
| **Précision de support (claims, toutes paires SUPPORTS)** | 23/32 | 71,9 % [54,6 %, 84,4 %] |
| Macro-moyenne par question (10 questions à paires) | — | 75,2 % |
| Ligne dédiée `kb_only` (rubrique §5) | 1 paire, 1 SUPPORTS | — |

† Intervalle **descriptif approché** : les paires d'une même question sont corrélées ; les
comptes bruts et la macro-moyenne par question font foi.

Décomposition des 9 PARTIAL : 4 tranches sources tronquées à 300 caractères (l'affirmation
déborde de la tranche rendue — les mots manquants existent dans le document mais la rubrique
note le texte cité rendu) ; 3 affirmations négatives corpus-entier qu'un seul passage ne peut
établir ; 2 passages authentiques mais adjacents à l'affirmation (dont A.4.4 : « couverture
partielle » affirmée depuis le dossier de conception alors que le gold classe l'exigence non
couverte — le cas authentique-mais-hors-sujet).

| Fidélité des réponses (n=10 répondues) | Comptes |
|---|---|
| FAITHFUL | 7/10 |
| PARTIALLY_FAITHFUL | 3/10 |
| UNFAITHFUL | 0/10 |

Les 3 PARTIALLY_FAITHFUL : A.4.3 (réponse `kb_only` honnête mais qui ne restitue pas la
couverture réelle — gold `compliant`) ; A.4.4 (« couvre partiellement » alors que le gold
classe `missing`) ; A.8.3 (faits internes exacts mais l'écart gold — signalement externe non
défini — n'est pas énoncé).

| Abstention (answerability figée par le générateur) | Comptes | % [IC 95 %] |
|---|---|---|
| Précision | 1/4 | 25,0 % [4,6 %, 69,9 %] |
| Rappel (3 sans réponse attendue) | 1/3 | 33,3 % [6,1 %, 79,2 %] |

Lecture : 3 abstentions `verification_failed` sur des questions à réponse attendue (couverture
réelle non citée exactement) et 2 questions sans réponse attendue répondues (dont 1 `kb_only`
encadrée par le caveat serveur). 1 citation retirée (stripped) sur le run. Diagnostics dev :
précision 3/6, rappel 3/8, 13 citations retirées, réparation utilisée sur 24/51.

## 5. Diagnostics de développement (dev, n=51 — jamais agrégés au holdout)

Pipeline (n_scored=46 après 5 `infra_failed` post-recouvrement) : exactitude 33/46 = 71,7 %
[57,5 %, 82,7 %] ; `partial` 17/18, `compliant` 13/19 (6 sous-cotés `partial`),
`non_compliant` 0/2, `missing` 3/7 abstenus. Chat : localisation 168/168 ; abstention
P 3/6, R 3/8. Artefacts : `eval/m6/runs/dev-diagnostics/`.

## 6. Indicateurs opérationnels

- **Taux de reprise humaine** : 0 revue enregistrée sur les findings des assessments
  d'évaluation listés (dev et holdout) — les runs d'évaluation n'ont pas transité par
  l'atelier de revue M5 ; l'indicateur reste mesurable en production via `finding_reviews`,
  strictement borné aux assessments cités.
- **Disponibilité première passe** : holdout 14/14 sans échec ; dev 34/51 (17 abstentions 429
  Mistral), 12 récupérées par l'unique assessment de recouvrement (filiation enregistrée),
  5 restées `infra_failed` (catégorisées, jamais notées). Registre d'erreurs chat : vide.

## 7. Limites (déclarées)

1. **Notation** : labels pré-remplis par l'assistant IA puis revus et acceptés par l'auteur —
   écart à la rubrique §6 (notation directe par l'auteur) ; l'indépendance reste procédurale
   (masquage §4 structurel, answerability et ancres figées par le gold, formules gelées).
2. **Projet solo** : pas de second annotateur ; pas d'accord inter-annotateurs mesurable.
3. **n = 14** (3 sans réponse attendue) : intervalles larges ; aucune conclusion fine par
   verdict ; comptes bruts systématiquement publiés.
4. **Holdout d'étiquettes, pas preuve de généralisation** : les mêmes six documents
   alimentent dev et test (corpus/README.md) ; une organisation jamais vue reste un travail futur.
5. **Diagnostic de porte ≠ ablation** : le 0 post-porte est structurel ; la « réduction »
   n'est pas affirmée.
6. **Rappel d'abstention faible (0/3 pipeline, 1/3 chat)** : sur les exigences non couvertes,
   le système cite des passages authentiques mais hors sujet au lieu de s'abstenir — c'est la
   limite assumée de la vérification de localisation (jamais d'entailment sémantique) ; la
   revue humaine M5 et la remédiation M7 sont les contre-mesures prévues.
7. **Troncature des tranches citées à 300 caractères** : 4 des 9 PARTIAL proviennent
   d'affirmations dont le support existe dans le document mais déborde de la tranche rendue —
   une limite de rendu, pas une hallucination ; piste M7+ : étendre la tranche rendue.
8. **Seuil de confiance non calibré** : télémétrie publiée, aucune conclusion tirée.
9. Écart mineur d'exécution : dev lancé avec les réglages 429 par défaut (17 abstentions),
   holdout et chat avec `JUDGE_429_RETRIES=6` — réglage d'infrastructure enregistré dans les
   méta des artefacts, sans effet sur les règles de notation.
