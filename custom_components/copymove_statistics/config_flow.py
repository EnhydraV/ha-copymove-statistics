"""Config flow « assistant » : exécute l'opération choisie puis s'arrête.

Aucune entrée de configuration n'est créée : chaque passage par
« Ajouter une intégration » ouvre un menu (transférer / nettoyer)
et lance une opération ponctuelle.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.recorder import get_instance
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONFIRM,
    CONF_DELETE,
    CONF_ENTITY,
    CONF_MOVE,
    CONF_ON_CONFLICT,
    CONF_PERIOD_END,
    CONF_PERIOD_START,
    CONF_ROWS,
    CONF_SOURCE,
    CONF_TABLE,
    CONF_TARGET,
    DOMAIN,
    ON_CONFLICT_MERGE,
    ON_CONFLICT_REPLACE,
    TABLE_LONG_TERM,
    TABLE_SHORT_TERM,
)
from .stats import (
    VALUE_COLUMNS,
    BrowseResult,
    NoStatisticsError,
    NotSumStatisticsError,
    RowNotFoundError,
    StatsMigrationError,
    clean_decreasing_statistics,
    delete_statistic_rows,
    list_statistic_rows,
    migrate_statistics,
    update_statistic_row,
)

# Nombre maximum de lignes proposées dans la liste (affiner via la période).
_ROW_LIMIT = 200

STEP_TRANSFER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SOURCE): selector.EntitySelector(
            selector.EntitySelectorConfig()
        ),
        vol.Required(CONF_TARGET): selector.EntitySelector(
            selector.EntitySelectorConfig()
        ),
        vol.Required(CONF_MOVE, default=True): selector.BooleanSelector(),
        vol.Required(
            CONF_ON_CONFLICT, default=ON_CONFLICT_MERGE
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[ON_CONFLICT_MERGE, ON_CONFLICT_REPLACE],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_ON_CONFLICT,
            )
        ),
    }
)

STEP_CLEAN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig()
        ),
    }
)

STEP_EDIT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig()
        ),
        vol.Required(CONF_TABLE, default=TABLE_LONG_TERM): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[TABLE_LONG_TERM, TABLE_SHORT_TERM],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_TABLE,
            )
        ),
        vol.Optional(CONF_PERIOD_START): selector.DateTimeSelector(),
        vol.Optional(CONF_PERIOD_END): selector.DateTimeSelector(),
    }
)

_NUMBER_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        mode=selector.NumberSelectorMode.BOX, step="any"
    )
)


def _parse_input_ts(value: str | None) -> float | None:
    """Convertit la valeur d'un DateTimeSelector en timestamp epoch."""
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed.timestamp()


def _format_when(start_ts: float) -> str:
    return dt_util.as_local(dt_util.utc_from_timestamp(start_ts)).strftime(
        "%Y-%m-%d %H:%M"
    )


def _row_label(row: dict[str, Any]) -> str:
    """Libellé d'une ligne dans la liste : horodatage + valeurs non nulles."""
    parts = [
        f"{column}={row[column]:.6g}"
        for column in VALUE_COLUMNS
        if row[column] is not None
    ]
    when = _format_when(row["start_ts"])
    return f"{when} — {', '.join(parts)}" if parts else when


class StatsImportConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Menu : transférer, nettoyer ou consulter/modifier des statistiques."""

    VERSION = 1

    # Contexte de la session de consultation/édition en cours.
    _edit_entity: str = ""
    _edit_short_term: bool = False
    _edit_start_ts: float | None = None
    _edit_end_ts: float | None = None
    _edit_browse: BrowseResult | None = None
    _edit_selected: list[dict[str, Any]] | None = None
    _edit_modified: int = 0
    _edit_deleted: int = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Menu d'entrée."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["transfer", "clean", "edit"],
        )

    async def async_step_transfer(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Transfert (déplacement ou copie) source -> cible."""
        errors: dict[str, str] = {}

        if user_input is not None:
            source: str = user_input[CONF_SOURCE]
            target: str = user_input[CONF_TARGET]
            move: bool = user_input[CONF_MOVE]
            replace: bool = user_input[CONF_ON_CONFLICT] == ON_CONFLICT_REPLACE

            if source == target:
                errors["base"] = "same_entity"
            else:
                instance = get_instance(self.hass)
                try:
                    result = await instance.async_add_executor_job(
                        migrate_statistics, instance, source, target, move, replace
                    )
                except NoStatisticsError:
                    errors[CONF_SOURCE] = "no_statistics"
                except StatsMigrationError:
                    errors["base"] = "migration_failed"
                else:
                    reason = "moved" if move else "copied"
                    if result.replaced:
                        reason += "_replaced"
                    return self.async_abort(
                        reason=reason,
                        description_placeholders={
                            "source": source,
                            "target": target,
                            "long_term": str(result.long_term),
                            "short_term": str(result.short_term),
                            "replaced": str(result.replaced),
                        },
                    )

        return self.async_show_form(
            step_id="transfer",
            data_schema=self.add_suggested_values_to_schema(
                STEP_TRANSFER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_clean(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Nettoyage d'une statistique de cumul (suppression des baisses)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entity: str = user_input[CONF_ENTITY]
            instance = get_instance(self.hass)
            try:
                result = await instance.async_add_executor_job(
                    clean_decreasing_statistics, instance, entity
                )
            except NoStatisticsError:
                errors[CONF_ENTITY] = "no_statistics"
            except NotSumStatisticsError:
                errors[CONF_ENTITY] = "not_sum"
            except StatsMigrationError:
                errors["base"] = "migration_failed"
            else:
                return self.async_abort(
                    reason="cleaned",
                    description_placeholders={
                        "entity": entity,
                        "long_term_deleted": str(result.long_term_deleted),
                        "long_term_scanned": str(result.long_term_scanned),
                        "short_term_deleted": str(result.short_term_deleted),
                        "short_term_scanned": str(result.short_term_scanned),
                    },
                )

        return self.async_show_form(
            step_id="clean",
            data_schema=self.add_suggested_values_to_schema(
                STEP_CLEAN_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def _async_refresh_rows(self) -> BrowseResult:
        """(Re)charge la liste des lignes avec les filtres de la session."""
        instance = get_instance(self.hass)
        self._edit_browse = await instance.async_add_executor_job(
            list_statistic_rows,
            instance,
            self._edit_entity,
            self._edit_short_term,
            self._edit_start_ts,
            self._edit_end_ts,
            _ROW_LIMIT,
        )
        return self._edit_browse

    def _value_columns(self) -> list[str]:
        """Colonnes de valeurs pertinentes selon le type de la statistique."""
        columns: list[str] = []
        if self._edit_browse and self._edit_browse.has_mean:
            columns += ["mean", "min", "max"]
        if self._edit_browse and self._edit_browse.has_sum:
            columns += ["state", "sum"]
        return columns or list(VALUE_COLUMNS)

    def _show_rows_form(self, errors: dict[str, str] | None = None) -> FlowResult:
        """Affiche la liste des lignes (sélection simple ou multiple)."""
        browse = self._edit_browse
        options = [
            selector.SelectOptionDict(value=str(row["id"]), label=_row_label(row))
            for row in browse.rows
        ]
        schema = vol.Schema(
            {
                vol.Optional(CONF_ROWS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="edit_rows",
            data_schema=schema,
            errors=errors or {},
            description_placeholders={
                "entity": self._edit_entity,
                "shown": str(len(browse.rows)),
                "total": str(browse.total),
            },
        )

    def _abort_edit_done(self) -> FlowResult:
        return self.async_abort(
            reason="edit_done",
            description_placeholders={
                "entity": self._edit_entity,
                "modified": str(self._edit_modified),
                "deleted": str(self._edit_deleted),
            },
        )

    async def _async_back_to_rows(self) -> FlowResult:
        """Recharge la liste après une opération ; termine si elle est vide."""
        await self._async_refresh_rows()
        if not self._edit_browse.rows:
            return self._abort_edit_done()
        return self._show_rows_form()

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choix de l'entité, de la table et de la période à consulter."""
        errors: dict[str, str] = {}

        if user_input is not None:
            start_ts = _parse_input_ts(user_input.get(CONF_PERIOD_START))
            end_ts = _parse_input_ts(user_input.get(CONF_PERIOD_END))
            if start_ts is not None and end_ts is not None and start_ts > end_ts:
                errors["base"] = "invalid_period"
            else:
                self._edit_entity = user_input[CONF_ENTITY]
                self._edit_short_term = (
                    user_input[CONF_TABLE] == TABLE_SHORT_TERM
                )
                self._edit_start_ts = start_ts
                self._edit_end_ts = end_ts
                self._edit_modified = 0
                self._edit_deleted = 0
                try:
                    browse = await self._async_refresh_rows()
                except NoStatisticsError:
                    errors[CONF_ENTITY] = "no_statistics"
                except StatsMigrationError:
                    errors["base"] = "migration_failed"
                else:
                    if not browse.rows:
                        errors["base"] = "no_rows"
                    else:
                        return self._show_rows_form()

        return self.async_show_form(
            step_id="edit",
            data_schema=self.add_suggested_values_to_schema(
                STEP_EDIT_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_edit_rows(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Liste des lignes : une pour éditer, plusieurs pour supprimer."""
        if user_input is not None:
            selected_ids = user_input.get(CONF_ROWS) or []
            if not selected_ids:
                return self._abort_edit_done()
            rows_by_id = {str(row["id"]): row for row in self._edit_browse.rows}
            self._edit_selected = [
                rows_by_id[row_id]
                for row_id in selected_ids
                if row_id in rows_by_id
            ]
            if len(self._edit_selected) == 1:
                return await self.async_step_edit_value()
            return await self.async_step_edit_delete()

        return self._show_rows_form()

    async def async_step_edit_value(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Modification (ou suppression) de la ligne sélectionnée."""
        row = self._edit_selected[0]
        columns = self._value_columns()

        if user_input is not None:
            instance = get_instance(self.hass)
            try:
                if user_input.get(CONF_DELETE):
                    await instance.async_add_executor_job(
                        delete_statistic_rows,
                        instance,
                        self._edit_entity,
                        self._edit_short_term,
                        [row["id"]],
                    )
                    self._edit_deleted += 1
                else:
                    # Seules les valeurs réellement changées sont écrites.
                    changed = {
                        column: user_input[column]
                        for column in columns
                        if user_input.get(column) is not None
                        and user_input[column] != row[column]
                    }
                    if changed:
                        await instance.async_add_executor_job(
                            update_statistic_row,
                            instance,
                            self._edit_entity,
                            self._edit_short_term,
                            row["id"],
                            changed,
                        )
                        self._edit_modified += 1
            except RowNotFoundError:
                await self._async_refresh_rows()
                if not self._edit_browse.rows:
                    return self._abort_edit_done()
                return self._show_rows_form({"base": "row_not_found"})
            except StatsMigrationError:
                return self._show_rows_form({"base": "migration_failed"})
            return await self._async_back_to_rows()

        fields: dict[Any, Any] = {
            vol.Optional(column): _NUMBER_SELECTOR for column in columns
        }
        fields[vol.Optional(CONF_DELETE, default=False)] = (
            selector.BooleanSelector()
        )
        suggested = {
            column: row[column] for column in columns if row[column] is not None
        }
        return self.async_show_form(
            step_id="edit_value",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), suggested
            ),
            description_placeholders={
                "entity": self._edit_entity,
                "when": _format_when(row["start_ts"]),
            },
        )

    async def async_step_edit_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirmation de la suppression des lignes sélectionnées."""
        if user_input is not None:
            if not user_input.get(CONF_CONFIRM):
                return self._show_rows_form()
            instance = get_instance(self.hass)
            try:
                deleted = await instance.async_add_executor_job(
                    delete_statistic_rows,
                    instance,
                    self._edit_entity,
                    self._edit_short_term,
                    [row["id"] for row in self._edit_selected],
                )
                self._edit_deleted += deleted
            except RowNotFoundError:
                await self._async_refresh_rows()
                if not self._edit_browse.rows:
                    return self._abort_edit_done()
                return self._show_rows_form({"base": "row_not_found"})
            except StatsMigrationError:
                return self._show_rows_form({"base": "migration_failed"})
            return await self._async_back_to_rows()

        return self.async_show_form(
            step_id="edit_delete",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONFIRM, default=False): (
                        selector.BooleanSelector()
                    ),
                }
            ),
            description_placeholders={
                "entity": self._edit_entity,
                "count": str(len(self._edit_selected)),
            },
        )
