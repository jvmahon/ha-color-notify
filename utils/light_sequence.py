"""Light sequence animation utils."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field, replace
import json
import logging
from typing import Any

from homeassistant.components.light import ATTR_RGB_COLOR
from homeassistant.const import CONF_RGB

from ..const import CONF_DELAY, OFF_RGB, WARM_WHITE_RGB

_LOGGER = logging.getLogger(__name__)


def _interpolate(start: tuple, end: tuple, amount: float) -> tuple:
    return tuple(
        int(t1 + (t2 - t1) * amount) for t1, t2 in zip(start, end, strict=True)
    )


@dataclass
class ColorInfo:
    """Internal color representation."""

    rgb: tuple = WARM_WHITE_RGB
    brightness: float = 100.0

    def interpolated_to(self, end: ColorInfo, amount: float) -> ColorInfo:
        """Return a new ColorInfo that is 0-1.0 linearly interpolated between end."""
        a = (*self.rgb, self.brightness)
        b = (*end.rgb, end.brightness)
        return ColorInfo(*_interpolate(a, b, amount))

    @property
    def light_params(self) -> dict[str, Any]:
        """Return dict suitable for passing to light.turn_on service."""
        return {ATTR_RGB_COLOR: self.rgb}


class LightSequence:
    """Handle cycling through sequences of colors."""

    def __init__(self) -> None:
        """Initialize a new LightSequence."""
        self._steps: list[_SeqStep] = []
        self._workspace: _SeqWorkspace = _SeqWorkspace()

    async def runNextStep(self) -> bool:
        """Run the next step, returning 'True' if done."""
        if self._workspace.next_idx >= len(self._steps):
            return True
        next_step = self._steps[self._workspace.next_idx]
        self._workspace.next_idx += 1
        await next_step.execute(self._workspace)
        return self._workspace.next_idx >= len(self._steps)

    def _addStep(self, step: _SeqStep) -> None:
        """Add a new step to this LightSequence."""
        step.idx = len(self._steps)
        self._steps.append(step)

    @staticmethod
    def create_from_pattern(pattern: list[str | ColorInfo]) -> LightSequence:
        """Create a LightSequence from a supplied pattern."""
        new_sequence: LightSequence = LightSequence()
        initial_color: ColorInfo | None = None
        next_loop_id: int = 1
        loop_stack: list[int] = []
        for item in pattern:
            if isinstance(item, ColorInfo):
                if initial_color is None:
                    initial_color = item
                new_sequence._addStep(_StepSetColor(item))
            elif isinstance(item, str):
                item = item.strip()
                if item == "[":
                    new_sequence._addStep(_StepOpenLoop(next_loop_id))
                    loop_stack.append(next_loop_id)
                    next_loop_id += 1
                elif item.startswith("]"):
                    with_iter_cnt = item.split(",")
                    iter_cnt = int(with_iter_cnt[1]) if len(with_iter_cnt) == 2 else -1
                    loop_id = loop_stack.pop()
                    new_sequence._addStep(_StepCloseLoop(loop_id, iter_cnt))
                else:
                    try:
                        json_txt = f"{{{item.strip().strip('{}')}}}"  # Strip and re-add curly braces
                        item_dict = json.loads(json_txt)
                    except:
                        _LOGGER.exception("Failed to parse json")
                    rgb = item_dict.get(
                        ATTR_RGB_COLOR, item_dict.get(CONF_RGB, WARM_WHITE_RGB)
                    )
                    color = ColorInfo(rgb=rgb)
                    if initial_color is None:
                        initial_color = color
                    # TODO: Fade
                    new_sequence._addStep(_StepSetColor(color))
                    if delay := item_dict.get(CONF_DELAY):
                        new_sequence._addStep(_StepDelay(delay))
        new_sequence._workspace.color = initial_color or ColorInfo(OFF_RGB, 0)
        # TODO:  Get the options flow to validate the json that is entered
        return new_sequence

    @property
    def color(self):
        """Return this sequence's current color."""
        return replace(self._workspace.color)

    @color.setter
    def color(self, value: ColorInfo):
        """Override this sequence's current color."""
        self._workspace.color = value


@dataclass
class _LoopInfo:
    """Information to store per-loop in a sequence."""

    open_idx: int = 0
    loop_cnt: int = 0


@dataclass
class _SeqWorkspace:
    """Runtime information for a sequence."""

    next_idx: int = 0
    cur_loop: int = 0
    data: dict[Any, Any] = field(default_factory=dict)
    color: ColorInfo = field(default_factory=ColorInfo)


class _SeqStep(ABC):
    """Abstract class representing a step in a sequence."""

    def __init__(self) -> None:
        self._idx: int | None = None  # This step's index within the sequence

    @abstractmethod
    async def execute(self, workspace: _SeqWorkspace):
        """Perform this steps action to update the workspace."""

    @property
    def idx(self):
        return self._idx

    @idx.setter
    def idx(self, value):
        self._idx = value


class _StepOpenLoop(_SeqStep):
    """Sequence step that opens a loop."""

    def __init__(self, loop_id: int) -> None:
        super().__init__()
        self._loop_id = loop_id

    async def execute(self, workspace: _SeqWorkspace):
        assert self.idx is not None
        if self._loop_id not in workspace.data:
            workspace.data[self._loop_id] = _LoopInfo(open_idx=self.idx)


class _StepCloseLoop(_SeqStep):
    """Sequence step that closes a loop."""

    def __init__(self, loop_id: int, loop_cnt: int) -> None:
        super().__init__()
        self._loop_id = loop_id
        self._total_repeats = loop_cnt

    async def execute(self, workspace: _SeqWorkspace):
        info: _LoopInfo | None = workspace.data.get(self._loop_id)
        if info is None:
            raise ValueError("CloseLoop with no matching OpenLoop!")
        info.loop_cnt += 1
        if self._total_repeats < 0 or info.loop_cnt <= self._total_repeats:
            workspace.next_idx = info.open_idx
        else:
            workspace.data.pop(self._loop_id)


class _StepSetColor(_SeqStep):
    """Sequence step that updates the color."""

    def __init__(self, color: ColorInfo) -> None:
        super().__init__()
        self._color: ColorInfo = color

    async def execute(self, workspace: _SeqWorkspace):
        workspace.color = replace(self._color)  # creates a copy


class _StepDelay(_SeqStep):
    """Sequence step that waits."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self._delay = delay

    async def execute(self, workspace: _SeqWorkspace):
        await asyncio.sleep(self._delay)
