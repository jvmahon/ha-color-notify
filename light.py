"""Light platform for Notify Light-er integration."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
import logging
from typing import Any
from asyncio import Condition

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ENTITIES,
    CONF_ENTITY_ID,
    CONF_UNIQUE_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_RGB_SELECTOR,
    DEFAULT_PRIORITY,
    OFF_RGB,
    TYPE_POOL,
    WARM_WHITE_RGB,
)
from .hass_data import HassData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Notify Light-er config entry."""
    registry = er.async_get(hass)
    wrapped_entity_id = er.async_validate_entity_id(
        registry, config_entry.data[CONF_ENTITY_ID]
    )
    name = config_entry.title
    unique_id = config_entry.entry_id
    config = HassData.get_entry_data(hass, config_entry.entry_id)
    if config_entry.options:
        config.update(config_entry.options)
    config.update({CONF_UNIQUE_ID: unique_id})

    async_add_entities(
        [
            NotificationLightEntity(
                hass, unique_id, name, wrapped_entity_id, config_entry
            )
        ]
    )


@dataclass
class SequenceInfo:
    """A color sequence to queue on the light."""

    name: str
    pattern: tuple | list = field(default_factory=list)
    priority: int = DEFAULT_PRIORITY


LIGHT_OFF_SEQUENCE = SequenceInfo(name=STATE_OFF, pattern=OFF_RGB, priority=0)
LIGHT_ON_SEQUENCE = SequenceInfo(
    name=STATE_ON, pattern=WARM_WHITE_RGB, priority=DEFAULT_PRIORITY
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
        # TODO: self.hass auto-becomes available after constructor ends, maybe don't need to pass in copy
        self._hass: HomeAssistant = hass
        self._wrapped_entity_id: str = wrapped_entity_id
        self._attr_name: str = name
        self._attr_unique_id: str = unique_id
        self._config_entry: ConfigEntry = config_entry
        self._hass_entry: dict[str, Any] = HassData.get_entry_data(
            hass, config_entry.entry_id
        )
        self._sequences: list[SequenceInfo] = [LIGHT_OFF_SEQUENCE]
        self._light_on_sequence: SequenceInfo = SequenceInfo(
            name=STATE_ON,
            pattern=self._hass_entry.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB),
        )
        self._new_sequences: list[SequenceInfo] = []

        self._condition = Condition()
        self._task = self._hass.async_create_task(self._worker())

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

    async def _worker(self):
        async with self._condition:
            # Wait until the list is not empty
            await self._condition.wait_for(lambda: len(self._new_sequences) > 0)
            sequence = self._new_sequences.pop()
            print(sequence)

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        await self._queue_sequence(self._light_on_sequence)
        await self._hass.services.async_call(
            Platform.LIGHT,
            SERVICE_TURN_ON,
            target={"entity_id": self._wrapped_entity_id} | kwargs,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        await self._remove_sequence(self._light_on_sequence)
        await self._hass.services.async_call(
            Platform.LIGHT,
            SERVICE_TURN_OFF,
            target={"entity_id": self._wrapped_entity_id} | kwargs,
        )

    async def _queue_sequence(self, sequence: SequenceInfo) -> None:
        async with self._condition:
            self._new_sequences.append(sequence)
            self._new_sequences.sort(key=lambda x: x.priority)
            self._condition.notify()  # Wake up waiting consumers

    async def _remove_sequence(self, sequence: SequenceInfo) -> None:
        if sequence in self._sequences:
            self._sequences.remove(sequence)

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
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        return self._attr_color_mode

    @property
    def supported_color_modes(self) -> set[str] | None:
        """Flag supported color modes."""
        return self.state_attributes.get("supported_color_modes", {})
