"""Light platform for Notify Light-er integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Coroutine
import asyncio
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field, replace
from functools import cached_property
from itertools import cycle
import json
import logging
import time
from typing import Any, NoReturn

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
    CONF_RGB,
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
    CONF_DELAY,
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


def _interpolate(start: tuple, end: tuple, amount: float) -> tuple:
    return tuple(
        int(t1 + (t2 - t1) * amount) for t1, t2 in zip(start, end, strict=True)
    )


@dataclass
class _ColorInfo:
    """Internal color representation."""

    rgb: tuple = WARM_WHITE_RGB
    brightness: float = 100.0

    def interpolated_to(self, end: _ColorInfo, amount: float) -> _ColorInfo:
        a = (*self.rgb, self.brightness)
        b = (*end.rgb, end.brightness)
        return _ColorInfo(*_interpolate(a, b, amount))

    @property
    def light_params(self) -> dict[str, Any]:
        return {ATTR_RGB_COLOR: self.rgb}


@dataclass
class _AnimationState:
    """Info about the current state of a animation."""

    color: _ColorInfo = field(default_factory=_ColorInfo)
    prev_color: _ColorInfo | None = None
    trans_start_time: float = 0
    trans_end_time: float = 0


@dataclass
class _AnimWorkspace:
    next_idx: int = 0
    cur_loop: int = 0
    data: dict[Any, Any] = field(default_factory=dict)
    color: _ColorInfo = field(default_factory=_ColorInfo)


class _AnimationStep(ABC):
    def __init__(self) -> None:
        self._idx: int | None = None

    @abstractmethod
    async def execute(self, workspace: _AnimWorkspace):
        pass

    @property
    def idx(self):
        return self._idx

    @idx.setter
    def idx(self, value):
        self._idx = value


class _Animation:
    def __init__(self) -> None:
        self._steps: list[_AnimationStep] = []
        self._workspace: _AnimWorkspace = _AnimWorkspace()

    async def runNextStep(self) -> bool:
        """Run the next step, returning 'True' if done."""
        if self._workspace.next_idx >= len(self._steps):
            return True
        next_step = self._steps[self._workspace.next_idx]
        self._workspace.next_idx += 1
        await next_step.execute(self._workspace)
        return self._workspace.next_idx >= len(self._steps)

    def addStep(self, step: _AnimationStep) -> None:
        step.idx = len(self._steps)
        self._steps.append(step)

    @property
    def color(self):
        return replace(self._workspace.color)

    @color.setter
    def color(self, value: _ColorInfo):
        self._workspace.color = value


@dataclass
class _LoopInfo:
    open_idx: int = 0
    loop_cnt: int = 0


class _StepOpenLoop(_AnimationStep):
    def __init__(self, loop_id: int) -> None:
        super().__init__()
        self._loop_id = loop_id

    async def execute(self, workspace: _AnimWorkspace):
        assert self.idx is not None
        if self._loop_id not in workspace.data:
            workspace.data[self._loop_id] = _LoopInfo(self.idx)


class _StepSetColor(_AnimationStep):
    def __init__(self, color: _ColorInfo) -> None:
        super().__init__()
        self._color: _ColorInfo = color

    async def execute(self, workspace: _AnimWorkspace):
        workspace.color = replace(self._color)  # creates a copy


class _StepDelay(_AnimationStep):
    def __init__(self, delay: float):
        super().__init__()
        self._delay = delay
        self._end_timestamp: float = 0.0

    async def execute(self, workspace: _AnimWorkspace):
        self._end_timestamp = time.time() + self._delay
        await asyncio.sleep(self._delay)
        self._end_timestamp = 0

    def get_end_timestamp(self):
        return self._end_timestamp


class _StepCloseLoop(_AnimationStep):
    def __init__(self, loop_id: int, loop_cnt: int) -> None:
        super().__init__()
        self._loop_id = loop_id
        self._total_repeats = loop_cnt

    async def execute(self, workspace: _AnimWorkspace):
        info: _LoopInfo | None = workspace.data.get(self._loop_id)
        if info is None:
            raise ValueError("CloseLoop with no matching OpenLoop!")
        info.loop_cnt += 1
        if self._total_repeats < 0 or info.loop_cnt <= self._total_repeats:
            workspace.next_idx = info.open_idx
        else:
            workspace.data.pop(self._loop_id)


@dataclass
class _NotificationAnimation:
    """A color sequence to queue on the light."""

    def __init__(
        self,
        pattern: list[str | _ColorInfo],
        priority: int = DEFAULT_PRIORITY,
    ) -> None:
        self.priority = priority

        self._animation: _Animation = self._parse_pattern(pattern)
        self._condition: asyncio.Condition = asyncio.Condition()
        self._state: _AnimationState = _AnimationState(
            color=pattern[0] if pattern else _ColorInfo()
        )
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._step_finished: asyncio.Event = asyncio.Event()
        self._step_finished.set()

    def __repr__(self) -> str:
        return f"Animation Pri: {self.priority} Pattern: {self._animation}"

    def _parse_pattern(self, pattern: list[str | _ColorInfo]) -> _Animation:
        new_anim: _Animation = _Animation()
        initial_color: _ColorInfo | None = None
        next_loop_id: int = 1
        loop_stack: list[int] = []
        for item in pattern:
            if isinstance(item, _ColorInfo):
                if initial_color is None:
                    initial_color = item
                new_anim.addStep(_StepSetColor(item))
            elif isinstance(item, str):
                item = item.strip()
                if item == "[":
                    new_anim.addStep(_StepOpenLoop(next_loop_id))
                    loop_stack.append(next_loop_id)
                    next_loop_id += 1
                elif item.startswith("]"):
                    with_iter_cnt = item.split(",")
                    iter_cnt = int(with_iter_cnt[1]) if len(with_iter_cnt) == 2 else -1
                    loop_id = loop_stack.pop()
                    new_anim.addStep(_StepCloseLoop(loop_id, iter_cnt))
                else:
                    try:
                        json_txt = f"{{{item.strip().strip('{}')}}}"  # Ensure there are curly braces
                        item_dict = json.loads(json_txt)
                    except:
                        logging.exception("Failed to parse json")
                    rgb = item_dict.get(
                        ATTR_RGB_COLOR, item_dict.get(CONF_RGB, WARM_WHITE_RGB)
                    )
                    color = _ColorInfo(rgb=rgb)
                    if initial_color is None:
                        initial_color = color
                    # TODO: Fade
                    new_anim.addStep(_StepSetColor(color))
                    if delay := item_dict.get(CONF_DELAY):
                        new_anim.addStep(_StepDelay(delay))
        new_anim.color = initial_color or _ColorInfo(OFF_RGB, 0)
        # TODO:  Get the options flow to validate the json that is entered
        return new_anim

    def wait(self) -> Coroutine:
        return self._step_finished.wait()

    async def _worker_func(self, stop_event: asyncio.Event):
        """Coroutine to run the animation until finished or interrupted."""
        done = False
        try:
            while not done and not stop_event.is_set():
                self._step_finished.clear()
                done = await self._animation.runNextStep()
                self._step_finished.set()
                if not stop_event.is_set():  # Don't update if we were interrupted
                    self._state.color = self._animation.color
        except Exception as e:
            _LOGGER.exception("Failed running NotificationAnimation")
        _LOGGER.warning("Done with worker func for NotificationAnimation")

    async def run(self, hass: HomeAssistant, config_entry: ConfigEntry):
        if self._stop_event:
            self._stop_event.set()
        self._stop_event = asyncio.Event()
        self._task = config_entry.async_create_background_task(
            hass, self._worker_func(self._stop_event), name="Animation worker"
        )
        self._state.color = self._animation.color

    async def color(self) -> _ColorInfo:
        """Return the current, possibly interpolated, color of this animation."""
        # Linearly interpolate if there is a transition
        cur_time = time.time()
        if self._state.prev_color and cur_time < self._state.trans_end_time:
            total = self._state.trans_end_time - self._state.trans_start_time
            elapsed = cur_time - self._state.trans_start_time
            amount = elapsed / total if total > 0 else 0
            return self._state.prev_color.interpolated_to(self._state.color, amount)
        return self._state.color

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


LIGHT_OFF_SEQUENCE = _NotificationAnimation(
    pattern=[_ColorInfo(OFF_RGB, 0)],
    priority=0,
)
LIGHT_ON_SEQUENCE = _NotificationAnimation(
    pattern=[_ColorInfo(WARM_WHITE_RGB, 255)],
    priority=DEFAULT_PRIORITY,
)


@dataclass
class _QueueEntry:
    action: str
    notify_id: str
    sequence: _NotificationAnimation | None = None


@dataclass
class _ActiveAnimation:
    animation: _NotificationAnimation | None = None
    fade_start_time: float = 0
    fade_out_time: float = 0
    fade_in_time: float = 0


class NotificationLightEntity(LightEntity, RestoreEntity):
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
        self._wrapped_entity_id: str = wrapped_entity_id
        self._attr_name: str = name
        self._attr_unique_id: str = unique_id
        self._config_entry: ConfigEntry = config_entry
        self._wrapped_init: bool = False

        self._active_animations: dict[str, _ActiveAnimation] = {}
        self._sequences: dict[str, _NotificationAnimation] = {}
        self._last_set_color: _ColorInfo | None = None

        self._worker_queue: asyncio.Queue[_QueueEntry] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

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

        self._worker = self._config_entry.async_create_background_task(
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
        await self._add_sequence(STATE_OFF, LIGHT_OFF_SEQUENCE)

        restored_state = await self.async_get_last_state()
        if restored_state:
            self._attr_is_on = restored_state.state == STATE_ON
            self.async_schedule_update_ha_state(True)
            self.hass.async_create_task(self.async_turn_on())

    async def async_will_remove_from_hass(self):
        """Clean up before removal from HASS."""
        if self._worker:
            self._worker.cancel()

    async def _worker_func(self):
        while True:
            try:
                await self._work_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.exception("Error running %s worker!", self.name)

    @callback
    def _is_animating(self):
        """Return True if any active notification is an animation."""
        return any([x.animation.is_running() for x in self._active_animations.values()])

    @callback
    def _get_wait_events(self) -> set:
        """Return awaitable events for the current light."""
        return {
            x.animation.wait()
            for x in self._active_animations.values()
            if x.animation and x.animation.is_running()
        }

    async def _update_light_color(self):
        """Process the sequence list for the current display color and set it on the bulb."""
        if self._sequences:
            # _LOGGER.warning("Sequences: %s", self._sequences)
            next_id, next_sequence = next(iter(self._sequences.items()))
            # If highest priority sequence is not in the active list then put it there.
            if next_id not in self._active_animations:
                await next_sequence.run(self.hass, self._config_entry)
                self._active_animations[next_id] = _ActiveAnimation(
                    animation=next_sequence
                )

            remove_list = {
                k: v
                for k, v in self._active_animations.items()
                if k not in self._sequences
                or (
                    v.animation is not None
                    and v.animation.priority < next_sequence.priority
                )
            }

            # Stop animations that are lower priority than the current
            for seq_id, anim in remove_list.items():
                if anim.animation:
                    await anim.animation.stop()
                self._active_animations.pop(seq_id)

            # Now combine the colors
            colors = [
                await anim.animation.color()
                for anim in self._active_animations.values()
                if anim.animation is not None
            ]
            # _LOGGER.warning(colors)
            color = NotificationLightEntity.mix_colors(colors)
            if color != self._last_set_color:
                await self._wrapped_light_turn_on(**color.light_params)
                _LOGGER.warning(f"setting color {color} for {self._active_animations}")
                self._last_set_color = color

        else:
            _LOGGER.error("Sequence list empty for %s", self.name)

    async def _work_loop(self):
        """Worker loop to manage light."""
        # Wait until the list is not empty
        q_task: asyncio.Task | None = None
        while True:
            await self._update_light_color()
            if q_task is None or q_task.done():
                q_task = asyncio.create_task(self._worker_queue.get())
            wait_tasks = [asyncio.create_task(x) for x in self._get_wait_events()]
            wait_tasks.append(q_task)
            _LOGGER.warning(
                f"Waiting for asyncio  {self._worker_queue.qsize()} {hex(id(self._worker_queue))}"
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
                    if item.notify_id in self._sequences:
                        anim = self._sequences.pop(item.notify_id)
                        if item.notify_id in self._active_animations:
                            await anim.stop()
                            self._active_animations.pop(item.notify_id)

                if item.action == CONF_ADD and item.sequence:
                    _LOGGER.warning("Action: %s %s", item.action, item.notify_id)
                    # Add the new sequence in, sorted by priority
                    self._sequences[item.notify_id] = item.sequence
                    self._sequences = dict(
                        sorted(
                            self._sequences.items(), key=lambda item: -item[1].priority
                        )
                    )
                self._worker_queue.task_done()

            # TODO: Task needs to interpolate between current and next. We need to schedule 'enxt needed time'. If we are moving between
            # two static colors we can probably trust the lamp's transition to handle this for us (do we need transition time), but if we
            # are in the middle of an animation then we need to keep on rescheduling remixes, so we should schedule the 'next update time' for us

    @callback
    @staticmethod
    def mix_colors(
        colors: list[_ColorInfo], weights: list[float] | None = None
    ) -> _ColorInfo:
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

        return _ColorInfo((r, g, b), brightness_total)

    async def _add_sequence(
        self, notify_id: str, sequence: _NotificationAnimation
    ) -> None:
        """Add a sequence to this light."""
        _LOGGER.error(
            f"Adding {notify_id} add to worker queue {hex(id(self._worker_queue))}"
        )
        await self._worker_queue.put(
            _QueueEntry(action=CONF_ADD, notify_id=notify_id, sequence=sequence)
        )

    async def _remove_sequence(self, notify_id: str) -> None:
        """Remove a sequence from this light."""
        _LOGGER.error(
            f"Adding {notify_id} delete to worker queue {hex(id(self._worker_queue))}"
        )
        await self._worker_queue.put(
            _QueueEntry(notify_id=notify_id, action=CONF_DELETE)
        )

    async def _handle_notification_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle a notification changing state."""
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
            self._wrapped_init = True
            self.async_write_ha_state()

    async def _wrapped_light_turn_on(self, **kwargs: Any) -> None:
        """Turn on the underlying wrapped light entity."""
        if kwargs.get(ATTR_RGB_COLOR, []) == OFF_RGB:
            await self._wrapped_light_turn_off()
        else:
            if not self._wrapped_init:
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
        if not self._wrapped_init:
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
    ) -> _NotificationAnimation:
        """Create a light NotifySequence from a notification attributes."""
        pattern = attributes.get(CONF_NOTIFY_PATTERN)
        if not pattern:
            pattern = [
                _ColorInfo(rgb=attributes.get(CONF_RGB_SELECTOR, WARM_WHITE_RGB))
            ]
        priority = attributes.get(CONF_PRIORITY, DEFAULT_PRIORITY)
        return _NotificationAnimation(pattern=pattern, priority=priority)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
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
            pattern=[_ColorInfo(rgb=rgb)],
            priority=self._light_on_priority,
        )

        await self._add_sequence(STATE_ON, sequence)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        self.async_write_ha_state()
        await self._remove_sequence(STATE_ON)

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
