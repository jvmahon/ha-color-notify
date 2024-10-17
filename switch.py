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
    entities = [
        notify_lighterSwitchEntity(hass, ntfctn[CONF_UNIQUE_ID], name)
        for name, ntfctn in config.get(CONF_NTFCTN_ENTRIES, {})
        .get(CONF_NAME, {})
        .items()
    ]
    async_add_entities(entities)


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
