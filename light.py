"""Light platform for Notify Light-er integration."""

from __future__ import annotations

import asyncio
import bisect
from dataclasses import dataclass, field, replace
from functools import cached_property
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
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
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_hsv_to_RGB,
    color_RGB_to_hsv,
    color_temperature_to_rgb,
)

from .const import (
    CONF_ADD,
    CONF_DELETE,
    CONF_NOTIFY_PATTERN,
    CONF_PRIORITY,
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


# TODO: Could a sequence be its own async worker?
# TODO: Light 'on' should support customizing RGB
# TODO: Light 'on' state needs to be saved?
@dataclass
class SequenceInfo:
    """A color sequence to queue on the light."""

    entity_id: str
    pattern: tuple | list = field(default_factory=list)
    priority: int = DEFAULT_PRIORITY


LIGHT_OFF_SEQUENCE = SequenceInfo(entity_id=STATE_OFF, pattern=[OFF_RGB], priority=0)
LIGHT_ON_SEQUENCE = SequenceInfo(
    entity_id=STATE_ON, pattern=[WARM_WHITE_RGB], priority=DEFAULT_PRIORITY
)


@dataclass
class QueueEntry:
    sequence: SequenceInfo
    action: str


class NotificationLightEntity(LightEntity):
    """notify_lighter Light."""

    _attr_should_poll = False

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
        self._worker_queue: list[QueueEntry] = []
        self._active_sequence: SequenceInfo | None = None
        self._should_stop: bool = False
        self._light_on_priority: int = self._config_entry.options.get(
            CONF_PRIORITY, DEFAULT_PRIORITY
        )
        self._last_on_rgb: tuple = tuple(
            self._config_entry.options.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB)
        )

        self._condition = asyncio.Condition()
        self._task = config_entry.async_create_background_task(
            self._hass, self._worker(), name=f"{name} background task"
        )

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
            # Fire state_changed to get initial notification state
            hass.bus.async_fire(
                "state_changed",
                {
                    ATTR_ENTITY_ID: entity,
                    "new_state": hass.states.get(entity),
                    "old_state": None,
                },
            )

    async def async_added_to_hass(self):
        """Set up before initially adding to HASS."""
        pass

    async def async_will_remove_from_hass(self):
        """Clean up before removal from HASS."""
        self._should_stop = True
        async with self._condition:
            self._condition.notify()

    async def _worker(self):
        """Worker loop to manage light."""
        while not self._should_stop:
            try:
                async with self._condition:
                    # Wait until the list is not empty
                    while True:
                        if not self._worker_queue:
                            await self._condition.wait()
                        if self._should_stop:
                            break

                        if self._worker_queue:
                            action: QueueEntry = self._worker_queue.pop()
                            if action.action in (CONF_ADD, CONF_DELETE):
                                self._sequences[:] = [
                                    seq
                                    for seq in self._sequences
                                    if seq.entity_id != action.sequence.entity_id
                                ]
                                if (
                                    self._active_sequence
                                    and self._active_sequence.entity_id
                                    == action.sequence.entity_id
                                ):
                                    self._active_sequence = None

                            if action.action == CONF_ADD:
                                bisect.insort(
                                    self._sequences,
                                    action.sequence,
                                    key=lambda x: -x.priority,
                                )

                        if self._sequences:
                            if (
                                self._active_sequence is None
                                or self._sequences[0].entity_id
                                != self._active_sequence.entity_id
                            ):
                                self._active_sequence = self._sequences[0]
                                light_params: dict = {
                                    ATTR_RGB_COLOR: tuple(
                                        self._active_sequence.pattern[0]
                                    )
                                }
                                await self._wrapped_light_turn_on(**light_params)

                        _LOGGER.warning(self._sequences)
            except Exception as e:
                _LOGGER.error(e)

    async def _add_sequence(self, sequence: SequenceInfo) -> None:
        """Add a sequence to this light."""
        async with self._condition:
            self._worker_queue.append(QueueEntry(sequence, action=CONF_ADD))
            self._condition.notify()

    async def _remove_sequence(self, id: str) -> None:
        """Remove a sequence from this light."""
        async with self._condition:
            self._worker_queue.append(QueueEntry(SequenceInfo(id), action=CONF_DELETE))
            self._condition.notify()

    async def _handle_notification_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle a notification changing state."""
        is_on = event.data["new_state"].state == STATE_ON
        notify_id = event.data[CONF_ENTITY_ID]
        if is_on:
            sequence = self._create_sequence_from_attr(
                event.data[CONF_ENTITY_ID], event.data["new_state"].attributes
            )
            await self._add_sequence(sequence)
        else:
            await self._remove_sequence(notify_id)

    async def _handle_wrapped_light_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle the underlying wrapped light changing state."""
        if event.data["old_state"] is None:
            await self._handle_wrapped_light_init()

    async def _handle_wrapped_light_init(self) -> None:
        """Handle wrapped light entity initializing."""
        entity_registry: er.EntityRegistry = er.async_get(self.hass)
        entity: er.RegistryEntry | None = entity_registry.async_get(
            self._wrapped_entity_id
        )
        if entity:
            self._attr_capability_attributes = dict(entity.capabilities)
            self._attr_supported_color_modes = self._attr_capability_attributes.get(
                "supported_color_modes"
            )
            self.async_write_ha_state()
            self._active_sequence = None
            async with self._condition:
                self._condition.notify()

    async def _wrapped_light_turn_on(self, **kwargs: Any) -> None:
        """Turn on the underlying wrapped light entity."""
        if kwargs.get(ATTR_RGB_COLOR, []) == OFF_RGB:
            await self._wrapped_light_turn_off()
        else:
            if (
                ATTR_RGB_COLOR in kwargs
                and ATTR_BRIGHTNESS not in kwargs
                and ColorMode.RGB
                not in self._attr_supported_color_modes  # wrapped bulb's real capabilities
            ):
                # We want low RGB values to be dim, but HomeAssistant needs a separate brightness value for that.
                # If brightness was not passed in and bulb doesn't support RGB then convert to HS + Brightness.
                rgb = kwargs.pop(ATTR_RGB_COLOR)
                h, s, v = color_RGB_to_hsv(*rgb)
                # Re-scale 'v' from 0-100 to 0-255
                brightness = (255 / 100) * v
                kwargs[ATTR_HS_COLOR] = (h, s)
                kwargs[ATTR_BRIGHTNESS] = brightness

            await self._hass.services.async_call(
                Platform.LIGHT,
                SERVICE_TURN_ON,
                service_data={ATTR_ENTITY_ID: self._wrapped_entity_id} | kwargs,
            )

    async def _wrapped_light_turn_off(self, **kwargs: Any) -> None:
        """Turn off the underlying wrapped light entity."""
        await self._hass.services.async_call(
            Platform.LIGHT,
            SERVICE_TURN_OFF,
            service_data={ATTR_ENTITY_ID: self._wrapped_entity_id} | kwargs,
        )

    @staticmethod
    def _rgb_to_hs_brightness(
        r: float, g: float, b: float
    ) -> tuple[float, float, float]:
        """Return RGB to HS plus brightness."""
        h, s, v = color_RGB_to_hsv(r, g, b)
        # Re-scale 'v' from 0-100 to 0-255
        v = round((255 / 100) * v)
        return (h, s, v)

    def _create_sequence_from_attr(
        self, entity_id: str, attributes: dict[str, Any]
    ) -> SequenceInfo:
        """Create a light SequenceInfo from a notification attributes."""
        pattern = attributes.get(CONF_NOTIFY_PATTERN)
        if not pattern:
            pattern = [attributes.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB)]
        priority = attributes.get(CONF_PRIORITY, DEFAULT_PRIORITY)
        return SequenceInfo(entity_id=entity_id, pattern=pattern, priority=priority)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        self.async_write_ha_state()

        if ATTR_HS_COLOR in kwargs:
            rgb = color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
        elif ATTR_COLOR_TEMP in kwargs:
            rgb = color_temperature_to_rgb(kwargs[ATTR_COLOR_TEMP])
        elif ATTR_RGB_COLOR in kwargs:
            rgb = kwargs[ATTR_RGB_COLOR]
        elif ATTR_BRIGHTNESS in kwargs:
            v = (100 / 255) * kwargs[ATTR_BRIGHTNESS]
            h, s, _ = color_RGB_to_hsv(*self._last_on_rgb)
            rgb = color_hsv_to_RGB(h, s, v)
        else:
            rgb = self._last_on_rgb

        self._last_on_rgb = rgb
        sequence = replace(
            LIGHT_ON_SEQUENCE, pattern=[rgb], priority=self._light_on_priority
        )

        await self._add_sequence(sequence)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._remove_sequence(LIGHT_ON_SEQUENCE.entity_id)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the entity."""
        if self.is_on:
            await self.async_turn_off(**kwargs)
        else:
            await self.async_turn_on(**kwargs)

    @property
    def capability_attributes(self) -> dict[str, Any] | None:
        """Return the capability attributes of the underlying light entity."""
        return self._attr_capability_attributes

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        data = super().state_attributes
        return data
        # entity_state = self.hass.states.get(self._wrapped_entity_id)
        if entity_state is None:
            return {}
        return entity_state.attributes

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        return self._attr_color_mode

    @cached_property
    def supported_color_modes(self) -> set[str] | None:
        """Light wrapper expects RGB."""
        return [ColorMode.RGB]
