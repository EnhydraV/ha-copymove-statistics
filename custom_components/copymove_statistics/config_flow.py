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

from .const import (
    CONF_ENTITY,
    CONF_MOVE,
    CONF_ON_CONFLICT,
    CONF_SOURCE,
    CONF_TARGET,
    DOMAIN,
    ON_CONFLICT_MERGE,
    ON_CONFLICT_REPLACE,
)
from .stats import (
    NoStatisticsError,
    NotSumStatisticsError,
    StatsMigrationError,
    clean_decreasing_statistics,
    migrate_statistics,
)

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


class StatsImportConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Menu : transférer des statistiques ou nettoyer une statistique."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Menu d'entrée."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["transfer", "clean"],
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
