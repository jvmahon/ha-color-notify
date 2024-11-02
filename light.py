"""Light platform for Notify Light-er integration."""

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from functools import cached_property
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_XY_COLOR,
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
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_hs_to_xy,
    color_hsv_to_RGB,
    color_RGB_to_hsv,
    color_temperature_to_rgb,
    color_xy_to_temperature,
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
from .utils.hass_data import HassData
from .utils.light_sequence import ColorInfo, LightSequence

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
        [NotificationLightEntity(unique_id, name, wrapped_entity_id, config_entry)]
    )


@dataclass
class _NotificationSequence:
    """A color sequence to queue on the light."""

    def __init__(
        self,
        pattern: list[str | ColorInfo],
        priority: int = DEFAULT_PRIORITY,
    ) -> None:
        self.priority = priority

        self._sequence: LightSequence = LightSequence.create_from_pattern(pattern)
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._color: ColorInfo = ColorInfo(OFF_RGB, 0)
        self._step_finished: asyncio.Event = asyncio.Event()
        self._step_finished.set()

    def __repr__(self) -> str:
        return f"Animation Pri: {self.priority} Sequence: {self._sequence}"

    @property
    def color(self) -> ColorInfo:
        return self._color

    def wait(self) -> Coroutine:
        return self._step_finished.wait()

    async def _worker_func(self, stop_event: asyncio.Event):
        """Coroutine to run the animation until finished or interrupted."""
        done = False
        try:
            while not done and not stop_event.is_set():
                self._step_finished.clear()
                done = await self._sequence.runNextStep()
                self._step_finished.set()
                if not stop_event.is_set():  # Don't update if we were interrupted
                    self._color = self._sequence.color
        except Exception as e:
            _LOGGER.exception("Failed running NotificationAnimation")
        _LOGGER.warning("Done with worker func for NotificationAnimation")

    async def run(self, hass: HomeAssistant, config_entry: ConfigEntry):
        if self._stop_event:
            self._stop_event.set()
        self._stop_event = asyncio.Event()
        self._color = self._sequence.color
        self._task = config_entry.async_create_background_task(
            hass, self._worker_func(self._stop_event), name="Animation worker"
        )

    async def stop(self):
        if self._stop_event:
            self._stop_event.set()

    def is_running(self) -> bool:
        return bool(
            self._task
            and not self._task.done()
            and self._stop_event
            and not self._stop_event.is_set()
        )


LIGHT_OFF_SEQUENCE = _NotificationSequence(
    pattern=[ColorInfo(OFF_RGB, 0)],
    priority=0,
)
LIGHT_ON_SEQUENCE = _NotificationSequence(
    pattern=[ColorInfo(WARM_WHITE_RGB, 255)],
    priority=DEFAULT_PRIORITY,
)


@dataclass
class _QueueEntry:
    action: str
    notify_id: str
    sequence: _NotificationSequence | None = None


class NotificationLightEntity(LightEntity, RestoreEntity):
    """notify_lighter Light."""

    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        name: str,
        wrapped_entity_id: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize notify_lighter light."""
        super().__init__()
        self._wrapped_entity_id: str = wrapped_entity_id
        self._wrapped_init_done: bool = False
        self._attr_name: str = name
        self._attr_unique_id: str = unique_id
        self._config_entry: ConfigEntry = config_entry

        self._visible_sequences: dict[str, _NotificationSequence] = {}
        self._active_sequences: dict[str, _NotificationSequence] = {}
        self._last_set_color: ColorInfo | None = None

        self._task_queue: asyncio.Queue[_QueueEntry] = asyncio.Queue()
        self._task: asyncio.Task | None = None

        self._light_on_priority: int = config_entry.options.get(
            CONF_PRIORITY, DEFAULT_PRIORITY
        )
        self._last_on_rgb: tuple = tuple(
            config_entry.options.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB)
        )
        self._last_brightness: int = 100

    async def async_added_to_hass(self):
        """Set up before initially adding to HASS."""
        await super().async_added_to_hass()
        # Spawn the worker function background task to manage this bulb
        self._task = self._config_entry.async_create_background_task(
            self.hass, self._worker_func(), name=f"{self.name} background task"
        )

        # Check if the wrapped entity is valid at startup
        state = self.hass.states.get(self._wrapped_entity_id)
        if state:
            await self._handle_wrapped_light_init()

        # Subscribe to notifications
        self._config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, self._wrapped_entity_id, self._handle_wrapped_light_change
            )
        )

        hass_data: dict[str, dict] = HassData.get_ntfctn_entries(
            self.hass, self._config_entry.entry_id
        )
        pool_subs: list[str] = hass_data.get(TYPE_POOL, [])
        entity_subs: list[str] = hass_data.get(CONF_ENTITIES, [])

        for entity in entity_subs:
            self._config_entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, entity, self._handle_notification_change
                )
            )
            # Fire state_changed to get initial notification state
            self.hass.bus.async_fire(
                "state_changed",
                {
                    ATTR_ENTITY_ID: entity,
                    "new_state": self.hass.states.get(entity),
                    "old_state": None,
                },
            )

        # Add the 'OFF' sequence so the list isn't empty
        await self._add_sequence(STATE_OFF, LIGHT_OFF_SEQUENCE)

        restored_state = await self.async_get_last_state()
        if restored_state:
            self._attr_is_on = restored_state.state == STATE_ON
            self.async_schedule_update_ha_state(True)
            self.hass.async_create_task(self.async_turn_on())

    async def async_will_remove_from_hass(self):
        """Clean up before removal from HASS."""
        if self._task:
            self._task.cancel()

    async def _worker_func(self):
        while True:
            try:
                await self._work_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.exception("Error running %s worker!", self.name)

    @callback
    def _get_sequence_step_events(self) -> set:
        """Return awaitable events for the current light."""
        return {
            anim.wait()
            for anim in self._visible_sequences.values()
            if anim and anim.is_running()
        }

    async def _process_sequence_list(self):
        """Process the sequence list for the current display color and set it on the bulb."""
        if self._active_sequences:
            next_id, next_sequence = next(iter(self._active_sequences.items()))
            # If highest priority sequence is not in the active list then put it there.
            if next_id not in self._visible_sequences:
                await next_sequence.run(self.hass, self._config_entry)
                self._visible_sequences[next_id] = next_sequence

            remove_list = {
                k: anim
                for k, anim in self._visible_sequences.items()
                if k not in self._active_sequences
                or (anim is not None and anim.priority < next_sequence.priority)
            }

            # Stop animations that are lower priority than the current
            for seq_id, anim in remove_list.items():
                if anim:
                    await anim.stop()
                self._visible_sequences.pop(seq_id)

            # Now combine the colors
            colors = [
                anim.color
                for anim in self._visible_sequences.values()
                if anim is not None
            ]
            # _LOGGER.warning(colors)
            color = NotificationLightEntity.mix_colors(colors)
            if color != self._last_set_color:
                await self._wrapped_light_turn_on(**color.light_params)
                _LOGGER.warning(f"setting color {color} for {self._visible_sequences}")
                self._last_set_color = color

        else:
            _LOGGER.error("Sequence list empty for %s", self.name)

    async def _work_loop(self):
        """Worker loop to manage light."""
        # Wait until the list is not empty
        q_task: asyncio.Task | None = None
        while True:
            # Update the bulb based off the current sequence list
            await self._process_sequence_list()

            # Now wait for a command or for an animation step
            if q_task is None or q_task.done():
                q_task = asyncio.create_task(self._task_queue.get())
            wait_tasks = [
                asyncio.create_task(x) for x in self._get_sequence_step_events()
            ]
            wait_tasks.append(q_task)
            _LOGGER.warning(
                f"Waiting for asyncio  {self._task_queue.qsize()} {hex(id(self._task_queue))}"
            )
            done, pending = await asyncio.wait(
                wait_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if q_task in done:
                item = await q_task
                _LOGGER.error(f"Got q: {item}")

                if item.action in (CONF_ADD, CONF_DELETE):
                    _LOGGER.warning(
                        "Action: %s %s [step delete]", item.action, item.notify_id
                    )
                    if item.notify_id in self._active_sequences:
                        anim = self._active_sequences.pop(item.notify_id)
                        if item.notify_id in self._visible_sequences:
                            await anim.stop()
                            self._visible_sequences.pop(item.notify_id)

                if item.action == CONF_ADD and item.sequence:
                    _LOGGER.warning("Action: %s %s", item.action, item.notify_id)
                    # Add the new sequence in, sorted by priority
                    self._active_sequences[item.notify_id] = item.sequence
                    self._active_sequences = dict(
                        sorted(
                            self._active_sequences.items(),
                            key=lambda item: -item[1].priority,
                        )
                    )
                self._task_queue.task_done()

            # TODO: Task needs to interpolate between current and next. We need to schedule 'enxt needed time'. If we are moving between
            # two static colors we can probably trust the lamp's transition to handle this for us (do we need transition time), but if we
            # are in the middle of an animation then we need to keep on rescheduling remixes, so we should schedule the 'next update time' for us

    @callback
    @staticmethod
    def mix_colors(
        colors: list[ColorInfo], weights: list[float] | None = None
    ) -> ColorInfo:
        """Mix a list of RGB colors with their respective brightness and weight values."""
        if weights is None:
            weights = [1.0] * len(colors)

        # Normalize the weights so they sum to 1
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]

        # Initialize accumulators for the weighted RGB values
        r_total, g_total, b_total, brightness_total = 0.0, 0.0, 0.0, 0.0

        # Calculate the weighted average of RGB channels
        for color, weight in zip(colors, normalized_weights, strict=True):
            r, g, b = color.rgb
            # Apply brightness scaling to each color
            r_total += r * weight
            g_total += g * weight
            b_total += b * weight
            brightness_total += color.brightness * weight

        # Ensure RGB values are within the valid range [0, 255]
        r = min(int(round(r_total)), 255)
        g = min(int(round(g_total)), 255)
        b = min(int(round(b_total)), 255)
        brightness_total = min(int(round(brightness_total)), 255)

        return ColorInfo((r, g, b), brightness_total)

    async def _add_sequence(
        self, notify_id: str, sequence: _NotificationSequence
    ) -> None:
        """Add a sequence to this light."""
        _LOGGER.error(
            f"Adding {notify_id} add to worker queue {hex(id(self._task_queue))}"
        )
        await self._task_queue.put(
            _QueueEntry(action=CONF_ADD, notify_id=notify_id, sequence=sequence)
        )

    async def _remove_sequence(self, notify_id: str) -> None:
        """Remove a sequence from this light."""
        _LOGGER.error(
            f"Adding {notify_id} delete to worker queue {hex(id(self._task_queue))}"
        )
        await self._task_queue.put(_QueueEntry(notify_id=notify_id, action=CONF_DELETE))

    async def _handle_notification_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle a subscribed notification changing state."""
        is_on = event.data["new_state"].state == STATE_ON
        notify_id = event.data[CONF_ENTITY_ID]
        if is_on:
            sequence = self._create_sequence_from_attr(
                event.data["new_state"].attributes
            )
            await self._add_sequence(notify_id, sequence)
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
                "supported_color_modes", set()
            )
            self._wrapped_init_done = True
            self.async_write_ha_state()

    async def _wrapped_light_turn_on(self, **kwargs: Any) -> None:
        """Turn on the underlying wrapped light entity."""
        if kwargs.get(ATTR_RGB_COLOR, []) == OFF_RGB:
            await self._wrapped_light_turn_off()
        else:
            if not self._wrapped_init_done:
                _LOGGER.warning(
                    "Can't turn on light before it is initialized: %s", self.name
                )
                return
            if (
                ATTR_RGB_COLOR in kwargs
                and ATTR_BRIGHTNESS not in kwargs
                and ColorMode.RGB
                not in (
                    self._attr_supported_color_modes or {}
                )  # wrapped bulb's real capabilities
            ):
                # We want low RGB values to be dim, but HomeAssistant needs a separate brightness value for that.
                # TODO: Do we want this?
                # If brightness was not passed in and bulb doesn't support RGB then convert to HS + Brightness.
                rgb = kwargs.pop(ATTR_RGB_COLOR)
                h, s, v = color_RGB_to_hsv(*rgb)
                # Re-scale 'v' from 0-100 to 0-255
                brightness = (255 / 100) * v
                kwargs[ATTR_HS_COLOR] = (h, s)
                kwargs[ATTR_BRIGHTNESS] = brightness

            await self.hass.services.async_call(
                Platform.LIGHT,
                SERVICE_TURN_ON,
                service_data={ATTR_ENTITY_ID: self._wrapped_entity_id} | kwargs,
            )

    async def _wrapped_light_turn_off(self, **kwargs: Any) -> None:
        """Turn off the underlying wrapped light entity."""
        if not self._wrapped_init_done:
            return
        await self.hass.services.async_call(
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
        self, attributes: dict[str, Any]
    ) -> _NotificationSequence:
        """Create a light NotifySequence from a notification attributes."""
        pattern = attributes.get(CONF_NOTIFY_PATTERN)
        if not pattern:
            pattern = [ColorInfo(rgb=attributes.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB))]
        priority = attributes.get(CONF_PRIORITY, DEFAULT_PRIORITY)
        return _NotificationSequence(pattern=pattern, priority=priority)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Handle a turn_on service call."""
        self._attr_is_on = True

        if ATTR_HS_COLOR in kwargs:
            rgb = color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            rgb = color_temperature_to_rgb(kwargs[ATTR_COLOR_TEMP_KELVIN])
        elif ATTR_RGB_COLOR in kwargs or ATTR_BRIGHTNESS in kwargs:
            rgb = kwargs.get(ATTR_RGB_COLOR, self._last_on_rgb)
            self._last_brightness = kwargs.get(ATTR_BRIGHTNESS, self._last_brightness)
            v = (100 / 255) * self._last_brightness
            h, s, _ = color_RGB_to_hsv(*rgb)
            rgb = color_hsv_to_RGB(h, s, v)
        else:
            rgb = self._last_on_rgb

        self._last_on_rgb = rgb
        sequence = replace(
            LIGHT_ON_SEQUENCE,
            pattern=[ColorInfo(rgb=rgb)],
            priority=self._light_on_priority,
        )

        await self._add_sequence(STATE_ON, sequence)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Handle a turn_off service call."""
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._remove_sequence(STATE_ON)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Handle a toggle service call."""
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
        data: dict[str, Any] = {}
        if self.is_on:
            data[ATTR_COLOR_MODE] = ColorMode.RGB
            data[ATTR_RGB_COLOR] = self._last_on_rgb
            h, s, v = color_RGB_to_hsv(*self._last_on_rgb)
            brightness = (255 / 100) * v  # Re-scale 'v' from 0-100 to 0-255
            data[ATTR_BRIGHTNESS] = brightness
            data[ATTR_COLOR_TEMP_KELVIN] = color_temperature_to_rgb
            x, y = color_hs_to_xy(h, s)
            data[ATTR_XY_COLOR] = (x, y)
            data[ATTR_COLOR_TEMP_KELVIN] = color_xy_to_temperature(x, y)
        return data

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        return self._attr_color_mode

    @cached_property
    def supported_color_modes(self) -> set[str] | None:
        """Light wrapper expects RGB."""
        return [ColorMode.RGB]
