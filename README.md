# Copy/Move Statistics


Dépôt : https://github.com/EnhydraV/ha-copymove-statistics
Intégration Home Assistant (compatible HACS) pour manipuler les statistiques **long terme** (`statistics`) et **court terme** (`statistics_short_term`) du recorder. Trois utilitaires :

- **Transférer** les statistiques d'une entité vers une autre. Cas d'usage typique : un capteur a été remplacé ou renommé et vous voulez rattacher son historique de statistiques à la nouvelle entité. Par défaut, les statistiques sont **déplacées** (retirées de l'entité source) ; décochez la case pour les **copier**.
- **Nettoyer** une statistique censée être toujours croissante (compteur `total` / `total_increasing`) en supprimant les valeurs qui baissent (pics aberrants, imports ratés).
- **Consulter / modifier** les valeurs de statistiques d'une entité : lister les lignes (long ou court terme, période filtrable), corriger des valeurs individuelles ou supprimer des lignes.

## Installation

### Via HACS (dépôt personnalisé)

1. HACS → menu ⋮ → *Dépôts personnalisés*.
2. Ajoutez l'URL du dépôt Git, catégorie **Intégration**.
3. Installez *Copy/Move Statistics*, puis redémarrez Home Assistant.

### Manuelle

Copiez `custom_components/copymove_statistics/` dans le dossier `custom_components/` de votre configuration, puis redémarrez.

## Utilisation

*Paramètres → Appareils et services → Ajouter une intégration → Copy/Move Statistics*, puis choisissez l'utilitaire dans le menu. Aucune entrée d'intégration n'est créée : le formulaire est un assistant ponctuel, relançable à volonté.

### Transférer des statistiques

1. Choisissez l'**entité source** et l'**entité cible** (sélecteurs avec autocomplétion).
2. Laissez **Déplacer** coché (ou décochez pour copier).
3. Choisissez la stratégie **si la cible a déjà des statistiques** : *Fusionner* (défaut) ou *Remplacer*, puis validez.
4. Un récapitulatif s'affiche (nombre de lignes long terme / court terme transférées).

### Nettoyer une statistique croissante

1. Choisissez l'**entité** à nettoyer (elle doit avoir des statistiques de type cumul/`sum`, c'est-à-dire un capteur `total` ou `total_increasing`).
2. Validez : les lignes dont le cumul passe sous le maximum atteint avant elles sont supprimées, en long terme comme en court terme. Un récapitulatif indique le nombre de lignes supprimées et examinées.

### Consulter / modifier des valeurs

1. Choisissez l'**entité**, la **table** (long terme = horaire, court terme = toutes les 5 minutes) et, au besoin, une **période** pour restreindre la liste.
2. La liste affiche jusqu'à 200 lignes (les plus récentes de la période), avec horodatage et valeurs. Sélectionnez :
   - **une seule ligne** pour ouvrir le formulaire d'édition : modifiez `state`/`sum` (statistiques de cumul) ou `mean`/`min`/`max` (statistiques de mesure), ou cochez *Supprimer cette ligne* ;
   - **plusieurs lignes** pour les supprimer d'un coup (avec confirmation) ;
   - **rien**, puis validez, pour terminer : un récapitulatif indique le nombre de lignes modifiées et supprimées.
3. Après chaque opération, la liste se rafraîchit : vous pouvez enchaîner autant de corrections que nécessaire.

Les valeurs sont écrites telles quelles : les lignes voisines et les cumuls ne sont **pas recalculés**. Pour corriger la dérive d'un cumul (`sum`) sur toute une plage, préférez l'outil intégré de Home Assistant (*Outils de développement → Statistiques → Ajuster une somme*), qui répercute l'ajustement sur les lignes suivantes.

## Fonctionnement

L'opération agit directement sur la base du recorder (SQLite, MariaDB/MySQL ou PostgreSQL), dans l'executor du recorder :

- **Déplacement, cible sans statistiques** : simple renommage du `statistic_id` dans `statistics_meta` — instantané, aucune ligne déplacée.
- **Déplacement, cible avec statistiques (fusion)** : les lignes source sont re-pointées vers la métadonnée cible, puis la métadonnée source est supprimée. En cas de collision sur un même `start_ts`, la ligne **de la cible** est conservée.
- **Remplacement** : toutes les statistiques existantes de la cible (long et court terme) sont d'abord supprimées ; les métadonnées (unité, type mean/sum) sont reprises de la source. Le récapitulatif indique le nombre de lignes supprimées.
- **Copie** : les lignes sont dupliquées ; la métadonnée cible est créée (clonée depuis la source) si nécessaire, et la source conserve tout.
- **Nettoyage** : les lignes sont parcourues dans l'ordre chronologique (`start_ts`) avec un maximum courant sur la colonne `sum` ; toute ligne strictement inférieure au maximum est supprimée, les autres font avancer le maximum. La colonne `state` n'est pas contrôlée : une remise à zéro du compteur y est légitime, seul le cumul `sum` doit être monotone.
- **Consultation / édition** : lecture paginée de la table choisie (200 lignes maximum par période), puis `UPDATE` ou `DELETE` ciblés sur les lignes sélectionnées, toujours contraints au `metadata_id` de l'entité. Les champs proposés dépendent du type de la statistique (cumul → `state`/`sum`, mesure → `mean`/`min`/`max`).

## Précautions

- **Sauvegardez votre base** (ou faites un snapshot) avant une grosse migration : l'opération modifie directement les tables du recorder.
- **Redémarrez Home Assistant après l'opération** : le recorder met en cache les métadonnées de statistiques ; sans redémarrage, de nouvelles statistiques de l'entité source pourraient encore s'écrire sous l'ancien identifiant.
- Idéalement, **désactivez ou supprimez l'entité source avant** un déplacement, pour éviter qu'elle ne continue à produire des statistiques.
- Vérifiez que les **unités et le type** (mesure vs. cumul/`sum`) des deux entités sont cohérents : l'intégration ne convertit rien.
- Le sélecteur ne propose que les entités existantes ; pour une statistique orpheline (entité déjà supprimée), saisissez son identifiant manuellement.

## Compatibilité

Home Assistant ≥ 2023.5 (schéma recorder avec colonnes `*_ts`). Testé sur le schéma actuel ; le clonage des lignes et des métadonnées est générique (copie de toutes les colonnes), ce qui le rend tolérant aux évolutions de schéma (`has_mean`/`mean_type`, etc.).
