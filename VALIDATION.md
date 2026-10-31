# Vérifications de cette première version

- 35 tests automatisés réussis : schémas, dépendances, limitation des appels, sortie OpenAI simulée,
  consommation, parallélisme réel des appels simulés, chemins de fichiers, liaison utilisateur,
  adaptations du plan, corrections après avis final, blocage des constats de sécurité élevés,
  annulation, redémarrage, serveur et scénario de démonstration.
- Les tests du scénario produisent une application avec huit tests de comportement réellement
  exécutés dans un processus distinct : ajout, modification, suppression, persistance, entrées invalides.
- Parcours du tableau de bord vérifié dans Edge avec Playwright, aux largeurs 1440 et 390 pixels :
  mission, validation du plan, rapports de tests et de sécurité, lecture des fichiers, validation
  finale, téléchargement et mode plan uniquement. Aucune erreur JavaScript ni débordement horizontal.
- Application téléchargée relancée séparément et vérifiée dans le navigateur : ajout, tâche terminée,
  persistance après rechargement, puis suppression.
- Les agents de démonstration et leurs rapports de relecture/sécurité sont simulés. Le transport
  OpenAI est testé avec une réponse contrôlée ; aucun appel payant n'a été réalisé, faute de clé API.

Pour vérifier avec de vrais modèles : configurer `.env`, redémarrer, choisir Modèles OpenAI et lancer
une petite mission. L'accès aux modèles dépend du compte et de la clé fournis. Les tests de code
généré nécessitent aussi Docker et son image locale `python:3.14-slim`.

## Corrections issues de l'audit

- Plans incomplets refusés ; présence du backend et de l'interface exigée ; démarrage du serveur
  généré et réponse non vide de la page d'accueil vérifiés avant validation.
- Analyse de sécurité avant exécution. En mode OpenAI, exécution exclusivement dans un conteneur
  avec une copie jetable, sans réseau ni dossiers personnels. Sans Docker, les tests sont bloqués.
- Tests tous ignorés refusés ; bilan lu dans un fichier dédié plutôt que dans la sortie des tests.
  Une ligne de sortie falsifiée ne peut plus modifier les compteurs affichés.
- Sortie capturée limitée et nettoyage de l'arbre des processus après dépassement du délai.
- Corrections ordonnées selon les dépendances, avec transmission des fichiers nécessaires.
  Les modifications demandées après construction déclenchent une révision du chef et une confirmation.
- Questions fermées à la récupération des missions interrompues ; verrou entre processus avant
  toute récupération de l'historique. Vérification avec deux processus réels : le second est refusé
  et la mission du premier reste en attente de réponse, sans être marquée interrompue.
- Reproductions dans Edge réussies : tâches visibles à la confirmation du plan, fichier de la bonne
  mission, réponse de suivi obsolète ignorée, historique visible à 390 pixels. Aucune erreur JavaScript.
- Parcours complet de démonstration et mode plan uniquement revérifiés dans Edge : validation des
  points clés, tests, rapports, lecture des fichiers et téléchargement ; aucun débordement à 1440/390 pixels.
- Doublons de chemins normalisés refusés avant toute écriture.

**Limites restantes :** aucun appel OpenAI réel et aucune exécution Docker n'ont été effectués ici,
car la clé et Docker sont absents. Le blocage en l'absence de Docker est testé. La configuration du
conteneur est implémentée mais devra être vérifiée sur une machine équipée. L'analyse par un modèle
et le test de démarrage ne garantissent pas l'absence de toutes les vulnérabilités ou erreurs métier.
