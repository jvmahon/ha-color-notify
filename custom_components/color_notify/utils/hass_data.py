import logging
from typing import Any

from homeassistant.const import CONF_ENTITY_ID, CONF_TYPE, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN, TYPE_LIGHT, TYPE_POOL

_LOGGER = logging.getLogger(__name__)


class HassData:
    """Helper functions for access hass_data."""

    _runtime_data: dict[str, dict] = {}

    @callback
    @staticmethod
    def get_domain_data(hass: HomeAssistant) -> dict[str, dict]:
        """Return the domain hass_data."""
        return hass.data.setdefault(DOMAIN, {})

    @callback
    @staticmethod
    def get_config_entry_runtime_data(config_entry_id: str) -> dict[str, Any]:
        """Return non-persisted runtime data for a ConfigEntry."""
        return HassData._runtime_data.setdefault(config_entry_id, {})

    @callback
    @staticmethod
    def clear_config_entry_runtime_data(config_entry_id: str) -> None:
        """Clear runtime data for a ConfigEntry."""
        if config_entry_id in HassData._runtime_data:
            HassData._runtime_data.pop(config_entry_id)

    @callback
    @staticmethod
    def get_all_entities(
        hass: HomeAssistant, config_entry_id: str
    ) -> dict[str, er.RegistryEntry]:
        """Return all entities from a given config_entry."""
        entity_registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(entity_registry, config_entry_id)
        return {entity.unique_id: entity for entity in entities}

    @callback
    @staticmethod
    def get_all_pools(hass: HomeAssistant) -> list[tuple[str, dict]]:
        """Return all notification pools."""
        return [
            (uid, entry)
            for uid, entry in HassData.get_domain_data(hass).items()
            if entry.get(CONF_TYPE) == TYPE_POOL
        ]

    @callback
    @staticmethod
    def get_domain_lights(hass: HomeAssistant) -> list:
        """Return all notification lights."""
        return [
            entry
            for uid, entry in HassData.get_domain_data(hass).items()
            if entry.get(CONF_TYPE) == TYPE_LIGHT
        ]

    @callback
    @staticmethod
    def get_domain_light_entity_ids(hass: HomeAssistant) -> list[str]:
        """Return a list of all wrapper light entity_ids."""
        entity_registry: er.EntityRegistry = er.async_get(hass)
        ret: list[str] = []
        for light in HassData.get_domain_lights(hass):
            entry_id = light.get(CONF_UNIQUE_ID)
            entities = er.async_entries_for_config_entry(entity_registry, entry_id)
            ret.extend([entity.entity_id for entity in entities])
        return ret

    @callback
    @staticmethod
    def get_wrapped_light_entity_ids(hass: HomeAssistant) -> list[str]:
        """Return a list of all wrapped light entity_ids."""
        return [light[CONF_ENTITY_ID] for light in HassData.get_domain_lights(hass)]

    @callback
    @staticmethod
    def remove_entity(
        hass: HomeAssistant, config_entry_id: str, unique_id: str
    ) -> None:
        """Remove an entity by unique id."""
        entities = HassData.get_all_entities(hass, config_entry_id)
        entity_to_delete = entities.get(unique_id)
        if entity_to_delete is not None:
            HassData.clear_config_entry_runtime_data(config_entry_id)
            entity_registry = er.async_get(hass)
            entity_registry.async_remove(entity_to_delete.entity_id)
        else:
            _LOGGER.warning("Couldn't find entity with uid %s for removal", unique_id)
