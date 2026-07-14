# HANDOFF — Copy/Move Statistics

Intégration Home Assistant (HACS) qui manipule les tables de statistiques du recorder
(`statistics`, `statistics_short_term`, `statistics_meta`) via la session SQLAlchemy,
dans l'executor du recorder. Pas d'entrée de configuration : le config flow est un
assistant ponctuel qui exécute l'opération puis `async_abort` avec un récapitulatif.

## Structure

- `custom_components/copymove_statistics/stats.py` — toute la logique métier (SQL).
- `custom_components/copymove_statistics/config_flow.py` — l'UI (menu + formulaires).
- `const.py`, `strings.json`, `translations/{en,fr}.json` — `en.json` est une copie
  exacte de `strings.json` (les garder synchronisés).

## Historique

### 2026-07-14 — Fonctionnalité initiale (commit 1f45637)

Transfert de statistiques entre entités : déplacement (renommage de `statistic_id` si
cible vierge, sinon fusion avec priorité à la cible sur collision de `start_ts`) ou
copie (duplication des lignes). Stratégie « remplacer » optionnelle (purge de la cible
d'abord). Clonage de lignes/métadonnées générique (copie de toutes les colonnes) pour
tolérer les évolutions de schéma HA.

### 2026-07-14 — Utilitaire de nettoyage des statistiques croissantes

- Le config flow devient un menu (`async_show_menu`) à deux entrées : `transfer`
  (l'ancien formulaire unique, renommé depuis l'étape `user`) et `clean` (nouveau).
- `stats.clean_decreasing_statistics()` : pour une statistique de cumul (`has_sum`),
  parcourt les lignes par `start_ts` croissant avec un maximum courant sur `sum` et
  supprime toute ligne strictement inférieure (long terme + court terme). Les lignes
  à `sum` NULL sont ignorées. La colonne `state` n'est volontairement pas contrôlée
  (une remise à zéro de compteur y est légitime).
- Erreur dédiée `NotSumStatisticsError` si la statistique n'a pas `has_sum`
  (clé de traduction `not_sum`).
- Nouveau `CleanResult` (lignes examinées/supprimées LT et CT), affiché dans l'abort
  `cleaned`.

## À savoir / pistes

- Aucun test automatisé pour l'instant (nécessiterait un environnement HA + recorder ;
  base réelle → mode `--docker` du conteneur superclaude).
- Le README documente le fonctionnement utilisateur ; ce fichier documente le pourquoi
  technique.
