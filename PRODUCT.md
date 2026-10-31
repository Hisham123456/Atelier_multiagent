# Atelier multi-agents

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python pour l'orchestration, interface web locale. Les détails techniques sont délégués à l'implémentation : FastAPI, JavaScript et CSS sans compilation.

## Users

Utilisateur francophone qui découvre les agents et souhaite observer et comprendre leurs décisions.

## Product Purpose

Décrire une petite application, laisser un chef répartir le travail, un routeur choisir les spécialistes et un sélecteur choisir les modèles, puis récupérer le code et les vérifications.

## Operating Context

Application personnelle sur Windows. Tableau de bord local demandé et appels OpenAI uniquement. Première démonstration : liste de tâches persistante.

## Capabilities and Constraints

- Travail simultané sur des tâches indépendantes et affichage des dépendances.
- Choix du modèle expliqué, durées et consommation des appels enregistrées.
- Mode démonstration explicitement simulé, sans clé et sans facturation.
- Aucune publication automatique. L'utilisateur prépare lui-même son dépôt GitHub.
- Hypothèse d'implémentation : une seule exécution active, trois spécialistes simultanés au maximum.

## Product Principles

- Montrer les décisions et leurs résultats plutôt que les raisonnements internes.
- Ne jamais présenter une simulation comme un appel réel.
- Faire apparaître les erreurs, les limites et les résultats des tests.
- Privilégier une première version locale facile à lire et à lancer.
