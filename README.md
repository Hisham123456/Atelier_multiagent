# Atelier de développement multi-agents

Une application locale en français pour observer une équipe d'agents construire une petite application. Python 3.11 ou plus récent. Windows : double-cliquer sur **lancer.cmd**. Le premier lancement installe les dépendances dans `.venv` ; le tableau de bord est sur http://127.0.0.1:8080.

## Démarrage manuel

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m atelier
```

Le mode **Démonstration** fonctionne sans clé : les décisions et fichiers des agents viennent d'un scénario fixe et sont explicitement simulés. Les tests du code produit sont, eux, réellement exécutés. Le scénario crée une liste de tâches avec ajout, modification de l'état, suppression et persistance SQLite.

## Activer les vrais modèles

1. Copier `.env.example` vers `.env`.
2. Renseigner `OPENAI_API_KEY` dans `.env` sur ton ordinateur, puis redémarrer le serveur. Ne pas communiquer cette clé dans le chat ou dans Git.
3. Dans le tableau de bord, choisir **Modèles OpenAI**, écrire une demande et lancer l'équipe.

Les appels nécessitent un accès API aux modèles configurés. Aucune clé n'est fournie avec le projet. Les identifiants sont modifiables dans `.env` : `ATELIER_MODEL_ECONOMY` et `ATELIER_MODEL_ADVANCED`. Par défaut : `gpt-6-luna` et `gpt-6.1-sol`. Le code ne suppose pas que ton compte y a accès.

Si tu renseignes les quatre prix dans `.env`, le coût indicatif est calculé à partir des tokens renvoyés par l'API. Sinon, seuls les tokens sont affichés : aucun coût n'est inventé. Le calcul optionnel ne distingue pas les tokens d'entrée en cache et ne remplace pas la facturation du fournisseur.

## L'équipe

| Agent | Mission |
|---|---|
| Chef | Produit les tâches, leurs dépendances et le contrat commun ; supervise les corrections. |
| Routeur | Attribue la tâche au spécialiste de sa zone de fichiers. |
| Sélecteur | Choisit le niveau de modèle pour la tâche et explique sa décision. |
| Développeur backend | Produit la logique, l'API WSGI et la persistance en Python. |
| Développeur frontend | Produit l'interface HTML/CSS/JS et ses appels à l'API. |
| Testeur | Écrit des tests unittest ; le programme les exécute une fois les fichiers assemblés. |
| Rédacteur | Écrit la documentation de lancement. |
| Relecteur | Examine le code assemblé, le contrat et les résultats des tests. |
| Sécurité | Examine le code en parallèle du relecteur : injections, XSS, secrets, chemins et validation des entrées. |
| Liaison | Demande ton avis après le plan, après la première version et avant la validation finale. |

Le chef démarre avec le modèle avancé. Le routeur et le sélecteur utilisent un modèle économique fixe : cela évite de demander au sélecteur de choisir son propre modèle indéfiniment. Les spécialistes et le relecteur utilisent le modèle choisi par le sélecteur. Les trois responsables sont de vrais appels distincts en mode OpenAI.

L'orchestration est du Python lisible avec `asyncio`, le SDK OpenAI et l'API Responses. Il n'y a pas de magie dans plusieurs chats. Chaque appel reçoit uniquement sa mission et le contexte utile. Le programme valide les réponses structurées et conserve l'état ; les agents ne disposent pas d'un terminal libre.

## Exécution et résultat

- Une seule équipe active ; trois appels simultanés par défaut. Les tâches indépendantes se chevauchent réellement. Les tâches dépendantes attendent la vague précédente.
- Une seule tâche par zone : `backend/`, `frontend/`, `tests/`, `docs/`. Le coordinateur écrit le serveur de lancement et le contrat. Aucun spécialiste ne peut écraser les fichiers d'un autre.
- Les fichiers sont générés en réponses structurées, validés, puis écrits par Python. Les spécialistes n'installent pas de dépendances.
- Une analyse de sécurité précède les tests et bloque leur exécution si le rapport est défavorable. Une seconde analyse participe à la validation finale.
- En mode OpenAI, les tests exigent Docker et une image locale `python:3.14-slim` (à préparer avec `docker pull python:3.14-slim`). Le conteneur n'a pas de réseau, utilise un utilisateur non privilégié, des limites de ressources et une copie jetable du projet ; aucun dossier personnel n'est monté. Le système du conteneur est en lecture seule. Docker et son image ne sont pas installés automatiquement. Si l'isolation manque ou ne démarre pas, les fichiers sont conservés et le projet n'est pas validé ; il n'y a aucun repli vers une exécution Windows directe.
- Le scénario fixe de démonstration est testé localement dans une copie temporaire. Ce mode utilise exclusivement les fichiers de référence fournis avec l'atelier. Le délai est de 30 secondes, suivi d'un nettoyage borné de l'arbre des processus ; la sortie mémoire est limitée.
- La validation exige les fichiers d'entrée du backend et du frontend, au moins un test réellement exécuté, ainsi qu'une page d'accueil non vide servie avec succès. Ce contrôle minimal ne garantit pas à lui seul toutes les fonctionnalités demandées.
- Après les tests, relecture et au maximum deux cycles de correction. Une limite de 64 appels évite les boucles sans fin. Les erreurs réseau ne sont pas réessayées automatiquement pour éviter des appels payants invisibles.
- Le contrôle de sécurité est une analyse défensive en lecture seule. Une vulnérabilité jugée élevée ou critique bloque la validation. En mode démonstration, son rapport est simulé et indiqué comme tel ; ce n'est pas un audit réel ni une certification.
- Les exécutions et les réponses des modèles sont conservées sous `.atelier/runs/<id>/`. `state.json` contient le suivi ; `calls.jsonl` contient instructions, entrées, réponses, durée et consommation. Les fichiers de l'application sont dans `project/`.
- Un arrêt conserve les résultats déjà produits. Au redémarrage, une exécution inachevée est marquée interrompue ; elle ne redémarre pas automatiquement.
- Le bouton de téléchargement fournit le code de l'application. Décompresser, puis lancer `python run_app.py --port 8090` et ouvrir http://127.0.0.1:8090.

**Plan uniquement** permet d'exécuter le chef, le routeur et le sélecteur sans générer ni exécuter le code de l'application.

## Les points avec toi

L'agent de liaison intervient aux grandes étapes, sans minuterie : confirmation du plan, première
version disponible et validation après les tests et les relectures. Chacun de ces points attend ta
réponse pour te laisser le temps d'examiner le résultat avant de poursuivre.

**Continuer** confirme la direction. Pour changer le travail, écris une précision puis choisis
**Adapter avec ma réponse**. Avant la construction, le chef adapte le plan et te le représente.
Après la première version ou au bilan final, le chef révise le plan et le contrat à partir de ta demande, puis te fait confirmer ce nouveau plan. Les spécialistes reçoivent ensuite le retour et les fichiers utiles de leurs dépendances ; les corrections respectent le même ordre que la construction.
Les réponses et leur traitement restent dans l'historique. Les adaptations partagent la limite de
deux cycles de correction ; au-delà, le projet reste disponible avec le statut à améliorer.

En démonstration, le scénario reste fixe : les réponses sont enregistrées, mais un modèle simulé
ne peut pas inventer du nouveau code. Utilise le mode OpenAI pour adapter réellement le projet.

## Vérifier l'atelier

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests ne font aucun appel payant. Ils couvrent notamment les dépendances, le parallélisme, la sélection et le routage, les chemins de fichiers, les limites d'appels, l'annulation, les échecs, l'API et l'application de démonstration.

## Dépôt Git

Le dossier `.git` est laissé à ta gestion. `.env`, `.venv` et l'historique `.atelier` sont ignorés. Tu peux créer ton dépôt GitHub privé puis y pousser ce dossier. Aucun dépôt distant n'est publié automatiquement.

## Documentation technique

- [API Responses et sorties structurées](https://developers.openai.com/api/docs/guides/structured-outputs)
- [SDK Python OpenAI et appels asynchrones](https://developers.openai.com/api/reference/python)
- [Guide officiel de sélection des modèles](https://developers.openai.com/api/docs/guides/latest-model)
