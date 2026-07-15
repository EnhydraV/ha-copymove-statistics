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

### 2026-07-15 — Consultation / édition des valeurs de statistiques

- Troisième entrée de menu `edit` : pour une entité, liste les lignes d'une table
  (long OU court terme, au choix, période filtrable par deux `DateTimeSelector`
  optionnels) puis permet de modifier ou supprimer des valeurs, en boucle.
- `stats.py` : `list_statistic_rows()` (BrowseResult : lignes en dicts + total +
  has_sum/has_mean — `_meta_has_mean()` gère l'ancien `has_mean` et le nouveau
  `mean_type`), `update_statistic_row()` (colonnes restreintes à `VALUE_COLUMNS`,
  garde-fou `metadata_id`), `delete_statistic_rows()` (par lots). Nouvelle erreur
  `RowNotFoundError` (clé `row_not_found`) si la ligne a disparu entre-temps
  (purge recorder) : la liste est alors rafraîchie.
- Config flow : étapes `edit` (filtres) → `edit_rows` (SelectSelector multiple,
  200 lignes max, les plus récentes de la période, rendues chronologiquement ;
  libellés horodatage + valeurs non nulles) → `edit_value` (1 ligne : champs
  Number suggérés selon le type + case Supprimer ; seules les valeurs réellement
  changées sont écrites) ou `edit_delete` (plusieurs lignes : confirmation).
  Validation à vide de `edit_rows` → abort `edit_done` avec compteurs
  modifiées/supprimées. Après chaque opération la liste est rechargée.
- Volontairement PAS de recalcul des cumuls après édition d'un `sum` (documenté ;
  pour ça, renvoyer vers l'outil natif « Ajuster une somme » des dev tools).

## À savoir / pistes

- Aucun test automatisé pour l'instant (nécessiterait un environnement HA + recorder ;
  base réelle → mode `--docker` du conteneur superclaude).
- Le README documente le fonctionnement utilisateur ; ce fichier documente le pourquoi
  technique.
