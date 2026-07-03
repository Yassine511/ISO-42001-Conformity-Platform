# Politique du cycle de vie des systèmes d'IA — Lumen AI

**Référence :** LUM-LCM-001 · **Version :** 1.1 · **Date d'effet :** 9 février 2026
**Propriétaire :** Responsable produit IA · **Classification :** Interne

---

## 1. Objet

La présente politique encadre le cycle de vie des systèmes d'intelligence artificielle développés ou adaptés par Lumen AI, de l'expression du besoin jusqu'au retrait du système.

## 2. Objectifs de développement responsable

Le développement de tout système d'IA chez Lumen AI est guidé par des objectifs de développement responsable définis et documentés : équité des sorties, robustesse face aux entrées inattendues, transparence du fonctionnement vis-à-vis des utilisateurs internes et explicabilité des résultats lorsque le cas d'usage l'exige. Ces objectifs sont pris en compte dès la phase de conception et vérifiés aux jalons du cycle de développement.

## 3. Exigences et spécifications

Tout nouveau système d'IA, et toute évolution significative d'un système existant, fait l'objet d'un document d'exigences et de spécifications validé avant le début du développement. Ce document précise : la finalité du système, les cas d'usage couverts, les exigences fonctionnelles et non fonctionnelles, les contraintes de données, ainsi que les critères de performance attendus.

## 4. Documentation de la conception et du développement

Les choix de conception structurants — architecture retenue, modèle ou algorithme choisi, jeux de données mobilisés, compromis effectués — sont documentés dans le dossier de conception du système, tenu à jour tout au long du développement et conservé dans l'outil de gestion documentaire.

## 5. Vérification et validation

Avant toute mise en production, chaque système d'IA est soumis à une phase de vérification et de validation formelle : exécution du plan de tests, mesure des performances sur un jeu d'évaluation indépendant du jeu d'entraînement, et comparaison des résultats aux seuils d'acceptation définis dans le document d'exigences. Un système dont les résultats sont inférieurs aux seuils d'acceptation ne peut pas être mis en production.

## 6. Déploiement

La mise en production des systèmes d'IA majeurs suit le plan de déploiement standard (LUM-LCM-PR-03). Pour les systèmes jugés mineurs par l'équipe de développement, le déploiement peut être réalisé directement par l'équipe sans plan formalisé.

## 7. Exploitation et surveillance

Les systèmes d'IA en production font l'objet d'une surveillance continue : suivi des indicateurs de performance définis en phase de spécification, détection des dérives de comportement par rapport aux performances de validation, et traitement des incidents selon la procédure de gestion des incidents. Lorsqu'une dérive durable est constatée, le système est réentraîné, corrigé ou retiré de la production sur décision du Responsable produit IA.

## 8. Journalisation

Les systèmes d'IA en production critique enregistrent des journaux d'événements permettant de retracer leurs sollicitations et leurs sorties. Ces journaux sont conservés pendant trente jours. Les systèmes non critiques ne sont pas soumis à une obligation de journalisation.

---

*Document approuvé par le Responsable produit IA le 9 février 2026.*
