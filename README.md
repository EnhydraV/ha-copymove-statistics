# Copy/Move Statistics


Dépôt : https://github.com/EnhydraV/ha-copymove-statistics
Intégration Home Assistant (compatible HACS) pour transférer les statistiques **long terme** (`statistics`) et **court terme** (`statistics_short_term`) d'une entité vers une autre. Cas d'usage typique : un capteur a été remplacé ou renommé et vous voulez rattacher son historique de statistiques à la nouvelle entité.

Par défaut, les statistiques sont **déplacées** (retirées de l'entité source). Décochez la case pour les **copier**.

## Installation

### Via HACS (dépôt personnalisé)

1. HACS → menu ⋮ → *Dépôts personnalisés*.
2. Ajoutez l'URL du dépôt Git, catégorie **Intégration**.
3. Installez *Copy/Move Statistics*, puis redémarrez Home Assistant.

### Manuelle

Copiez `custom_components/copymove_statistics/` dans le dossier `custom_components/` de votre configuration, puis redémarrez.

## Utilisation

1. *Paramètres → Appareils et services → Ajouter une intégration → Copy/Move Statistics*.
2. Choisissez l'**entité source** et l'**entité cible** (sélecteurs avec autocomplétion).
3. Laissez **Déplacer** coché (ou décochez pour copier).
4. Choisissez la stratégie **si la cible a déjà des statistiques** : *Fusionner* (défaut) ou *Remplacer*, puis validez.
4. Un récapitulatif s'affiche (nombre de lignes long terme / court terme transférées). Aucune entrée d'intégration n'est créée : le formulaire est un assistant ponctuel, relançable à volonté.

## Fonctionnement

L'opération agit directement sur la base du recorder (SQLite, MariaDB/MySQL ou PostgreSQL), dans l'executor du recorder :

- **Déplacement, cible sans statistiques** : simple renommage du `statistic_id` dans `statistics_meta` — instantané, aucune ligne déplacée.
- **Déplacement, cible avec statistiques (fusion)** : les lignes source sont re-pointées vers la métadonnée cible, puis la métadonnée source est supprimée. En cas de collision sur un même `start_ts`, la ligne **de la cible** est conservée.
- **Remplacement** : toutes les statistiques existantes de la cible (long et court terme) sont d'abord supprimées ; les métadonnées (unité, type mean/sum) sont reprises de la source. Le récapitulatif indique le nombre de lignes supprimées.
- **Copie** : les lignes sont dupliquées ; la métadonnée cible est créée (clonée depuis la source) si nécessaire, et la source conserve tout.

## Précautions

- **Sauvegardez votre base** (ou faites un snapshot) avant une grosse migration : l'opération modifie directement les tables du recorder.
- **Redémarrez Home Assistant après l'opération** : le recorder met en cache les métadonnées de statistiques ; sans redémarrage, de nouvelles statistiques de l'entité source pourraient encore s'écrire sous l'ancien identifiant.
- Idéalement, **désactivez ou supprimez l'entité source avant** un déplacement, pour éviter qu'elle ne continue à produire des statistiques.
- Vérifiez que les **unités et le type** (mesure vs. cumul/`sum`) des deux entités sont cohérents : l'intégration ne convertit rien.
- Le sélecteur ne propose que les entités existantes ; pour une statistique orpheline (entité déjà supprimée), saisissez son identifiant manuellement.

## Compatibilité

Home Assistant ≥ 2023.5 (schéma recorder avec colonnes `*_ts`). Testé sur le schéma actuel ; le clonage des lignes et des métadonnées est générique (copie de toutes les colonnes), ce qui le rend tolérant aux évolutions de schéma (`has_mean`/`mean_type`, etc.).
