"""Config flow « assistant » : exécute la migration puis s'arrête.

Aucune entrée de configuration n'est créée : chaque passage par
« Ajouter une intégration » lance une migration ponctuelle.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.recorder import get_instance
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_MOVE,
    CONF_ON_CONFLICT,
    CONF_SOURCE,
    CONF_TARGET,
    DOMAIN,
    ON_CONFLICT_MERGE,
    ON_CONFLICT_REPLACE,
)
from .stats import NoStatisticsError, StatsMigrationError, migrate_statistics

STEP_USER_SCHEMA = vol.Schema(
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


class StatsImportConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Formulaire unique : source, cible, déplacer/copier."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Étape unique du flow."""
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
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )
