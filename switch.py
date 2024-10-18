"""Switch platform for Notify Switch-er integration."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_flow import HassData
from .const import CONF_DELETE, CONF_NTFCTN_ENTRIES, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Notify Light-er config entry."""
    # Update hass.data with any options
    config = hass.data[DOMAIN][config_entry.entry_id]
    if config_entry.options:
        config.update(config_entry.options)

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
        notify_lighterSwitchEntity(hass, unique_id=uid, name=data[CONF_NAME])
        for uid, data in new_entities.items()
        if uid not in entities_to_delete
    ]

    if entities_to_add:
        async_add_entities(entities_to_add)


class notify_lighterSwitchEntity(SwitchEntity):
    """notify_lighter Light."""

    def __init__(self, hass: HomeAssistant, unique_id: str, name: str) -> None:
        """Initialize notify_lighter light."""
        super().__init__()
        self._hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the state attributes."""
        return {"notify_lighter": True}
