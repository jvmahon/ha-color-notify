"""Light platform for Notify Switch-er integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.core import (
    HomeAssistant,
    State,
    Event,
    EventStateChangedData,
    EventStateEventData,
)

from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_NAME,
    CONF_UNIQUE_ID,
    STATE_ON,
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
    Platform,
)

from typing import Any, Callable

from .const import DOMAIN, CONF_NTFCTN_ENTRIES
from homeassistant.helpers import selector, translation, entity_registry as er


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

    entity_registry = er.async_get(hass)
    existing_entities = er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    )
    existing_unique_ids = {entry.unique_id.lower() for entry in existing_entities}
    entries: dict[str, dict] = config.get(CONF_NTFCTN_ENTRIES, {})
    # Filter to only add new entries
    new_entities: dict[str, dict] = {
        uid: data
        for uid, data in entries.get(CONF_UNIQUE_ID, {}).items()
        if uid.lower() not in existing_unique_ids
    }
    entities_to_add = [
        notify_lighterSwitchEntity(hass, unique_id=uid, name=data[CONF_NAME])
        for uid, data in new_entities.items()
    ]

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
