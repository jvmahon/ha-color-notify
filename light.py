"""Light platform for Notify Light-er integration."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.light import LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    Platform,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .config_flow import HassData
from .const import CONF_DELETE, CONF_NTFCTN_ENTRIES, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Notify Light-er config entry."""
    registry = er.async_get(hass)
    entity_id = er.async_validate_entity_id(registry, config_entry.data[CONF_ENTITY_ID])
    # TODO Optionally validate config entry options before creating entity
    name = config_entry.title
    unique_id = config_entry.entry_id
    config = HassData.get_entry_data(hass, config_entry.entry_id)
    if config_entry.options:
        config.update(config_entry.options)

    async_add_entities([notify_lighterLightEntity(hass, unique_id, name, entity_id)])


class notify_lighterLightEntity(LightEntity):
    """notify_lighter Light."""

    def __init__(
        self, hass: HomeAssistant, unique_id: str, name: str, wrapped_entity_id: str
    ) -> None:
        """Initialize notify_lighter light."""
        super().__init__()
        self._hass = hass
        self._wrapped_entity_id = wrapped_entity_id
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._unsub_updates: Callable = async_track_state_change_event(
            self._hass, self._wrapped_entity_id, self._callback
        )

    def __del__(self) -> None:
        if callable(self._unsub_updates):
            self._unsub_updates()

    def _callback(self, event: Event[EventStateChangedData]) -> None:
        self._attr_is_on = event.data["new_state"] == STATE_ON

    def is_on(self, hass: HomeAssistant, entity_id: str) -> bool:
        """Return if the lights are on based on the statemachine."""
        return hass.states.is_state(entity_id, STATE_ON)

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        self._hass.services.call(
            Platform.LIGHT,
            SERVICE_TURN_ON,
            target={"entity_id": self._wrapped_entity_id},
        )

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        self._hass.services.call(
            Platform.LIGHT,
            SERVICE_TURN_OFF,
            target={"entity_id": self._wrapped_entity_id},
        )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the state attributes."""
        return {"notify_lighter": True}
