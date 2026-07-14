"""Copy/Move Statistics — transfert de statistiques recorder entre entités.

L'intégration n'installe rien de permanent : le config flow sert
d'assistant ponctuel (il exécute la migration puis s'arrête sans
créer d'entrée de configuration).
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Rien à installer : tout se passe dans le config flow."""
    return True
