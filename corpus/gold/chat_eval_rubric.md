# Rubrique d'évaluation du chat (M6) — GELÉE AVANT M5

Ce document, avec `scripts/chat_eval_generate.py`, constitue le contrat d'évaluation gelé du
chat (plan §10). Il est committé **avant** le développement de l'interface M5, afin qu'aucune
liberté de notation ne subsiste après observation du comportement du système. Le sha256 des
deux fichiers est inscrit dans chaque jeu de questions généré et doit être rapporté avec les
résultats M6. Toute modification antérieure au run M6 doit être signalée dans le rapport.

## 1. Unité de notation

- **Support sémantique** : la paire **claim–citation**. Chaque claim survivant est apparié à
  chacune des citations qu'il référence ; chaque paire reçoit exactement un label :
  - `SUPPORTS` — le passage cité (tranche source pour policy, paraphrase pour KB) soutient
    l'affirmation du claim ;
  - `PARTIAL` — le passage est pertinent mais ne suffit pas à établir l'affirmation ;
  - `IRRELEVANT` — le passage, bien qu'authentique et localisé, ne soutient pas l'affirmation.
- **Fidélité de la réponse** : la réponse assemblée entière, un label parmi
  `FAITHFUL` / `PARTIALLY_FAITHFUL` / `UNFAITHFUL`, jugé contre le corpus auteur (vérité
  terrain exacte, car le corpus est rédigé par nous).

## 2. Agrégation (formules figées)

- **Précision de support (paires)** = |paires SUPPORTS| / |toutes paires notées|.
  `PARTIAL` compte comme non-support (conservateur) et est rapporté séparément.
- **Précision de support (claims)** = |claims dont TOUTES les paires sont SUPPORTS| / |claims|.
  Les deux niveaux sont rapportés ; les citations multiples d'un claim ne se compensent pas.
- **Abstention** : précision = |abstentions sur questions sans réponse attendue| /
  |abstentions| ; rappel = |abstentions sur questions sans réponse attendue| / |questions sans
  réponse attendue|. `answerable` est fixé par le générateur (`verdict gold != missing`).
- **Validité de localisation** : fraction des citations retournées que le vérificateur
  déterministe localise — rapportée SÉPARÉMENT du support sémantique, jamais agrégée avec.

## 3. Ancre gold = référence, pas exclusivité

L'ancre `gold_evidence_anchor` indique la citation minimale attendue. Un passage différent qui
soutient réellement le claim est labellisé `SUPPORTS` au même titre : l'ancre sert de repère au
correcteur, pas de seule réponse acceptable.

## 4. Masquage (adapté au chat)

Le correcteur note chaque paire à partir de **(texte du claim, texte cité rendu)** uniquement —
`source_quote` pour policy, `requirement_fr` hydratée pour KB. Sont masqués pendant la
notation : `status`, `abstain_reason`, `evidence_scope`, `citations_verified`,
`match_method/score`, les métadonnées de fichier et le raisonnement brut du modèle. (Le chat
n'ayant pas de verdict de pipeline, « verdicts masqués » signifie exactement cette liste.)

## 5. Ambiguïté et cas limites

- Doute entre `SUPPORTS` et `PARTIAL` → `PARTIAL` (conservateur).
- Doute entre `PARTIAL` et `IRRELEVANT` → `PARTIAL`, signalé en commentaire.
- Une réponse `kb_only` sur une question de couverture organisationnelle est notée sur ses
  paires comme les autres, mais rapportée dans une ligne dédiée (le caveat serveur est censé
  l'encadrer).
- Les abstentions n'ont pas de paires ; elles n'entrent que dans précision/rappel d'abstention.

## 6. Notation et incertitude

- Correcteur : l'auteur du projet (projet solo — dit honnêtement dans le rapport) ;
  l'indépendance est procédurale : labels d'answerability et ancres fixés par le gold
  préexistant, rubrique et générateur gelés avant tout run, notation avec les champs masqués
  du §4.
- Le holdout ne compte que **14 questions (3 sans réponse attendue)** : les résultats M6
  rapportent les **comptes bruts** et des intervalles de confiance (Wilson 95 %) à côté de
  tout pourcentage ; aucun pourcentage n'est publié sans son n.
- Les résultats dev (diagnostics de développement) et holdout sont rapportés séparément,
  toujours étiquetés comme tels.
