"""Light platform for Notify Light-er integration."""

from __future__ import annotations

from typing import Any, Callable
import logging
from functools import cached_property
from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_ENTITIES,
    CONF_UNIQUE_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    Platform,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import entity_registry as er
from .hass_data import HassData
from .const import TYPE_POOL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Notify Light-er config entry."""
    registry = er.async_get(hass)
    entity_id = er.async_validate_entity_id(registry, config_entry.data[CONF_ENTITY_ID])
    name = config_entry.title
    unique_id = config_entry.entry_id
    config = HassData.get_entry_data(hass, config_entry.entry_id)
    if config_entry.options:
        config.update(config_entry.options)
    config.update({CONF_UNIQUE_ID: unique_id})

    async_add_entities(
        [NotificationLightEntity(hass, unique_id, name, entity_id, config_entry)]
    )


class NotificationLightEntity(LightEntity):
    """notify_lighter Light."""

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        name: str,
        wrapped_entity_id: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize notify_lighter light."""
        super().__init__()
        self._hass: HomeAssistant = hass
        self._wrapped_entity_id: str = wrapped_entity_id
        self._attr_name: str = name
        self._unique_id: str = unique_id
        self._attr_unique_id: str = f"{self._unique_id}_{self.name}"
        self._config_entry: ConfigEntry = config_entry

        self._config_entry.async_on_unload(
            async_track_state_change_event(
                self._hass, self._wrapped_entity_id, self._handle_wrapped_light_change
            )
        )

        hass_data: dict[str, dict] = HassData.get_ntfctn_entries(
            self._hass, self._config_entry.entry_id
        )
        pool_subs: list[str] = hass_data.get(TYPE_POOL, [])
        entity_subs: list[str] = hass_data.get(CONF_ENTITIES, [])

        for entity in entity_subs:
            self._config_entry.async_on_unload(
                async_track_state_change_event(
                    self._hass, entity, self._handle_notification_change
                )
            )

    def _handle_notification_change(self, event: Event[EventStateChangedData]) -> None:
        _LOGGER.warning(f"_handle_notification_change: {event}")
        pass

    async def _handle_wrapped_light_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        if event.data["old_state"] is None:
            self._handle_wrapped_light_init()
        self._attr_is_on = event.data["new_state"].state == STATE_ON
        self.async_schedule_update_ha_state()

    def _handle_wrapped_light_init(self) -> None:
        """Handle wrapped light entity initializing."""
        entity_registry: er.EntityRegistry = er.async_get(self.hass)
        entity: er.RegistryEntry | None = entity_registry.async_get(
            self._wrapped_entity_id
        )
        if entity:
            self._attr_capability_attributes = dict(entity.capabilities)

    def is_on(self, hass: HomeAssistant, entity_id: str) -> bool:
        """Return if the lights are on based on the statemachine."""
        return hass.states.is_state(entity_id, STATE_ON)

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        self._hass.services.call(
            Platform.LIGHT,
            SERVICE_TURN_ON,
            target={"entity_id": self._wrapped_entity_id} | kwargs,
        )

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        self._hass.services.call(
            Platform.LIGHT,
            SERVICE_TURN_OFF,
            target={"entity_id": self._wrapped_entity_id} | kwargs,
        )

    @property
    def capability_attributes(self) -> dict[str, Any] | None:
        """Return the capability attributes of the underlying light entity."""
        return self._attr_capability_attributes

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        entity_state = self.hass.states.get(self._wrapped_entity_id)
        if entity_state is None:
            return {}
        return entity_state.attributes

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        _LOGGER.warning(f"color_mode")
        return self._attr_color_mode

    @property
    def supported_color_modes(self) -> set[str] | None:
        _LOGGER.warning(f"supported_color_modes")
        return self.state_attributes.get("supported_color_modes", {})
