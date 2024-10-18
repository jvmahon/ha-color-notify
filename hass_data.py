from homeassistant.core import HomeAssistant, callback
from .const import (
    CONF_PRIORITY,
    DEFAULT_PRIORITY,
    CONF_NTFCTN_ENTRIES,
    DOMAIN,
    TYPE_LIGHT,
    TYPE_POOL,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_ENTITY_ID,
    CONF_TYPE,
    CONF_UNIQUE_ID,
)
from homeassistant.helpers import entity_registry as er, selector


class HassData:
    """Helper functions for access hass_data."""

    @callback
    @staticmethod
    def get_domain_data(hass: HomeAssistant) -> dict[str, dict]:
        """Return the domain hass_data"""
        return hass.data[DOMAIN]

    @callback
    @staticmethod
    def get_entry_data(hass: HomeAssistant, config_entry_id: str) -> dict[str, dict]:
        """Return hass_data entries for a ConfigEntry."""
        return HassData.get_domain_data(hass).setdefault(config_entry_id, {})

    @callback
    @staticmethod
    def get_ntfctn_entries(
        hass: HomeAssistant, config_entry_id: str
    ) -> dict[str, dict]:
        """Return notification entries."""
        return HassData.get_entry_data(hass, config_entry_id).setdefault(
            CONF_NTFCTN_ENTRIES, {}
        )

    @callback
    @staticmethod
    def get_entries_by_uuid(
        hass: HomeAssistant, config_entry_id: str
    ) -> dict[str, dict]:
        """Return notification entries by uuid."""
        return HassData.get_ntfctn_entries(hass, config_entry_id).setdefault(
            CONF_UNIQUE_ID, {}
        )

    @callback
    @staticmethod
    def get_all_entities(
        hass: HomeAssistant, config_entry_id: str
    ) -> list[er.RegistryEntry]:
        """Return all entities from a given config_entry."""
        entity_registry = er.async_get(hass)
        return er.async_entries_for_config_entry(entity_registry, config_entry_id)

    @callback
    @staticmethod
    def get_all_pools(hass: HomeAssistant) -> list:
        """Return all notification pools."""
        return [
            entry
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
    def get_config_notification_list(
        hass: HomeAssistant, config_entry_id: str
    ) -> dict[str, str]:
        """Get list of notifications for display in config list."""
        entities = HassData.get_all_entities(hass, config_entry_id)
        items_by_uuid = HassData.get_entries_by_uuid(hass, config_entry_id)
        entities.sort(
            key=lambda x: -items_by_uuid.get(x.unique_id, {}).get(
                CONF_PRIORITY, DEFAULT_PRIORITY
            )
        )
        # Set up multi-select
        ntfctn_unique_ids = {
            e.unique_id: f"{items_by_uuid.get(e.unique_id, {}).get(CONF_NAME)} [{e.entity_id}] Prio: {items_by_uuid.get(e.unique_id, {}).get(CONF_PRIORITY):.0f}"
            for e in entities
        }
        return ntfctn_unique_ids

    @callback
    @staticmethod
    def remove_entity(
        hass: HomeAssistant, config_entry_id: str, unique_id: str
    ) -> bool:
        """Remove an entity by unique id."""
        ret: bool = False
        entity_info = HassData.get_entries_by_uuid(hass, config_entry_id).get(
            unique_id, {}
        )
        if entity_info:
            HassData.get_entries_by_uuid(hass, config_entry_id).pop(
                entity_info[CONF_UNIQUE_ID]
            )
            all_entities = HassData.get_all_entities(hass, config_entry_id)
            entity = next(
                (item for item in all_entities if item.unique_id == unique_id), None
            )
            if entity:
                entity_registry = er.async_get(hass)
                entity_registry.async_remove(entity.entity_id)
                ret = True
        return ret
