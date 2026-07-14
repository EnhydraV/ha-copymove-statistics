"""Migration des statistiques recorder (long terme + court terme).

Opère directement sur les tables `statistics`, `statistics_short_term`
et `statistics_meta` via la session SQLAlchemy du recorder. Doit être
exécuté dans l'executor du recorder (voir config_flow).

Règles :
- Cible sans statistiques + déplacement : simple renommage du
  `statistic_id` dans `statistics_meta` (aucune ligne déplacée).
- Cible avec statistiques, stratégie « merge » : les lignes des deux
  entités sont fusionnées ; en cas de collision sur `start_ts`, la
  ligne de la CIBLE est conservée.
- Cible avec statistiques, stratégie « replace » : toutes les
  statistiques existantes de la cible sont supprimées, puis
  remplacées par celles de la source (les métadonnées — unité,
  type — sont reprises de la source).
- Copie : comme le déplacement, mais les lignes sont dupliquées et
  la source conserve tout.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.db_schema import (
    Statistics,
    StatisticsMeta,
    StatisticsShortTerm,
)
from homeassistant.components.recorder.util import session_scope
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

_INSERT_CHUNK = 1000
# Colonnes jamais recopiées telles quelles lors d'un clonage de ligne.
_ROW_EXCLUDE = {"id", "metadata_id", "created", "created_ts"}


class StatsMigrationError(HomeAssistantError):
    """Erreur générique de migration de statistiques."""


class NoStatisticsError(StatsMigrationError):
    """L'entité source ne possède aucune statistique."""


@dataclass(slots=True)
class MigrationResult:
    """Résultat d'une migration."""

    long_term: int
    short_term: int
    merged: bool
    replaced: int = 0  # lignes de la cible supprimées (stratégie replace)


def _get_meta(session: Session, statistic_id: str) -> StatisticsMeta | None:
    return session.execute(
        select(StatisticsMeta).where(StatisticsMeta.statistic_id == statistic_id)
    ).scalar_one_or_none()


def _count_rows(session: Session, table: Any, metadata_id: int) -> int:
    return session.execute(
        select(func.count())
        .select_from(table)
        .where(table.metadata_id == metadata_id)
    ).scalar_one()


def _dst_start_ts_subquery(table: Any, dst_meta_id: int):
    """Sous-requête des start_ts déjà présents côté cible.

    Enveloppée dans un SELECT dérivé pour rester compatible MySQL
    (erreur 1093 : UPDATE/DELETE sur la table visée par la sous-requête).
    """
    inner = (
        select(table.start_ts).where(table.metadata_id == dst_meta_id).subquery()
    )
    return select(inner.c.start_ts)


def _clone_meta(meta: StatisticsMeta, new_statistic_id: str) -> StatisticsMeta:
    """Clone une ligne de métadonnées, indépendamment du schéma exact.

    Copie toutes les colonnes (unit, has_mean/has_sum ou mean_type
    selon la version de HA, source, name...) sauf l'id.
    """
    data = {
        column.name: getattr(meta, column.name)
        for column in StatisticsMeta.__table__.columns
        if column.name != "id"
    }
    data["statistic_id"] = new_statistic_id
    return StatisticsMeta(**data)


def _purge_rows(session: Session, meta_id: int) -> int:
    """Supprime toutes les lignes de statistiques d'une métadonnée."""
    deleted = 0
    for table in (Statistics, StatisticsShortTerm):
        result = session.execute(
            delete(table)
            .where(table.metadata_id == meta_id)
            .execution_options(synchronize_session=False)
        )
        deleted += result.rowcount or 0
    return deleted


def _sync_meta_from(meta_dst: StatisticsMeta, meta_src: StatisticsMeta) -> None:
    """Aligne les métadonnées de la cible sur celles de la source.

    Utilisé en stratégie « replace » : unité, type (mean/sum), source...
    tout est repris de l'entité source, hors id et statistic_id.
    """
    for column in StatisticsMeta.__table__.columns:
        if column.name in ("id", "statistic_id"):
            continue
        setattr(meta_dst, column.name, getattr(meta_src, column.name))


def _move_rows(session: Session, table: Any, src_meta_id: int, dst_meta_id: int) -> int:
    """Re-pointe les lignes source vers la métadonnée cible (fusion)."""
    colliding = _dst_start_ts_subquery(table, dst_meta_id)
    session.execute(
        delete(table)
        .where(table.metadata_id == src_meta_id, table.start_ts.in_(colliding))
        .execution_options(synchronize_session=False)
    )
    result = session.execute(
        update(table)
        .where(table.metadata_id == src_meta_id)
        .values(metadata_id=dst_meta_id)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def _copy_rows(
    session: Session,
    table: Any,
    src_meta_id: int,
    dst_meta_id: int,
    dst_had_stats: bool,
) -> int:
    """Duplique les lignes source vers la métadonnée cible."""
    stmt = select(table).where(table.metadata_id == src_meta_id)
    if dst_had_stats:
        stmt = stmt.where(
            ~table.start_ts.in_(_dst_start_ts_subquery(table, dst_meta_id))
        )
    rows = session.execute(stmt).scalars().all()
    if not rows:
        return 0

    columns = table.__table__.columns
    has_created_ts = "created_ts" in columns.keys()
    now = time.time()

    payload: list[dict[str, Any]] = []
    for row in rows:
        data = {
            column.name: getattr(row, column.name)
            for column in columns
            if column.name not in _ROW_EXCLUDE
        }
        data["metadata_id"] = dst_meta_id
        if has_created_ts:
            data["created_ts"] = now
        payload.append(data)

    for i in range(0, len(payload), _INSERT_CHUNK):
        session.execute(table.__table__.insert(), payload[i : i + _INSERT_CHUNK])
    return len(payload)


def migrate_statistics(
    instance: Recorder, source: str, target: str, move: bool, replace: bool = False
) -> MigrationResult:
    """Déplace (ou copie) toutes les statistiques de `source` vers `target`.

    `replace=True` : si la cible possède déjà des statistiques, elles
    sont intégralement supprimées avant le transfert (sinon fusion,
    la cible gagnant sur les collisions de `start_ts`).

    À exécuter via `instance.async_add_executor_job(...)`.
    """
    try:
        with session_scope(session=instance.get_session()) as session:
            meta_src = _get_meta(session, source)
            if meta_src is None:
                raise NoStatisticsError(
                    f"Aucune statistique trouvée pour {source}"
                )
            meta_dst = _get_meta(session, target)

            replaced = 0
            if replace and meta_dst is not None:
                replaced = _purge_rows(session, meta_dst.id)
                if move:
                    # La cible est repartie de zéro : on supprime aussi sa
                    # métadonnée et on retombe sur le simple renommage,
                    # qui reprend intégralement les métadonnées source.
                    session.delete(meta_dst)
                    session.flush()
                    meta_dst = None
                else:
                    # Copie : on garde la ligne meta cible mais on aligne
                    # ses attributs (unité, type...) sur la source.
                    _sync_meta_from(meta_dst, meta_src)

            # --- Déplacement, cible vierge : simple renommage. ---
            if move and meta_dst is None:
                long_term = _count_rows(session, Statistics, meta_src.id)
                short_term = _count_rows(session, StatisticsShortTerm, meta_src.id)
                meta_src.statistic_id = target
                _LOGGER.info(
                    "Statistiques renommées %s -> %s (%d LT / %d CT)",
                    source,
                    target,
                    long_term,
                    short_term,
                )
                return MigrationResult(long_term, short_term, merged=False, replaced=replaced)

            # --- Déplacement, fusion dans une cible existante. ---
            if move:
                long_term = _move_rows(session, Statistics, meta_src.id, meta_dst.id)
                short_term = _move_rows(
                    session, StatisticsShortTerm, meta_src.id, meta_dst.id
                )
                session.delete(meta_src)
                _LOGGER.info(
                    "Statistiques fusionnées %s -> %s (%d LT / %d CT)",
                    source,
                    target,
                    long_term,
                    short_term,
                )
                return MigrationResult(long_term, short_term, merged=True, replaced=replaced)

            # --- Copie. ---
            dst_had_stats = meta_dst is not None
            if meta_dst is None:
                meta_dst = _clone_meta(meta_src, target)
                session.add(meta_dst)
                session.flush()  # obtenir meta_dst.id

            long_term = _copy_rows(
                session, Statistics, meta_src.id, meta_dst.id, dst_had_stats
            )
            short_term = _copy_rows(
                session, StatisticsShortTerm, meta_src.id, meta_dst.id, dst_had_stats
            )
            _LOGGER.info(
                "Statistiques copiées %s -> %s (%d LT / %d CT)",
                source,
                target,
                long_term,
                short_term,
            )
            return MigrationResult(long_term, short_term, merged=dst_had_stats, replaced=replaced)

    except StatsMigrationError:
        raise
    except Exception as err:  # noqa: BLE001 - remonté sous forme d'erreur métier
        _LOGGER.exception(
            "Échec de la migration des statistiques %s -> %s", source, target
        )
        raise StatsMigrationError(str(err)) from err
