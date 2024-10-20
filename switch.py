"""Switch platform for Notify Switch-er integration."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .hass_data import HassData
from .const import CONF_DELETE, CONF_NTFCTN_ENTRIES


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Notify Light-er config entry."""
    # Update hass.data with any options
    config = HassData.get_entry_data(hass, config_entry.entry_id)
    if config_entry.options:
        config.update(config_entry.options)
    config.update({CONF_UNIQUE_ID: config_entry.entry_id})
    existing_entities = HassData.get_all_entities(hass, config_entry)
    existing_unique_ids = {
        entry.unique_id.lower(): entry for entry in existing_entities
    }

    entries: dict[str, dict] = config.get(CONF_NTFCTN_ENTRIES, {})
    # Filter to only add new entries
    new_entities: dict[str, dict] = {
        uid: data
        for uid, data in entries.get(CONF_UNIQUE_ID, {}).items()
        if uid.lower() not in existing_unique_ids
    }

    entities_to_delete: list[str] = config_entry.options.get(CONF_DELETE, [])
    if entities_to_delete:
        new_options = dict(config_entry.options)
        new_options.pop(CONF_DELETE)
        hass.config_entries.async_update_entry(config_entry, options=new_options)
        for entity_uid in entities_to_delete:
            HassData.remove_entity(hass, config_entry.entry_id, entity_uid)

    entities_to_add = [
        NotificationSwitchEntity(
            hass, unique_id=uid, name=data[CONF_NAME], config_entry=config_entry
        )
        for uid, data in new_entities.items()
        if uid not in entities_to_delete
    ]

    if entities_to_add:
        async_add_entities(entities_to_add)


class NotificationSwitchEntity(ToggleEntity):
    """notify_lighter Light."""

    def __init__(
        self, hass: HomeAssistant, unique_id: str, name: str, config_entry: ConfigEntry
    ) -> None:
        """Initialize notify_lighter light."""
        super().__init__()
        self._hass = hass
        self._attr_name = name
        self._unique_id: str = unique_id
        self._attr_unique_id: str = self._unique_id
        self._attr_is_on = False
        self._config_entry: ConfigEntry = config_entry

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
