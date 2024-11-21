"""Switch platform for Notify Switch-er integration."""

from __future__ import annotations
from collections.abc import Callable
from datetime import timedelta
from functools import partial
import logging
from typing import Any
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DELAY_TIME,
    CONF_ENTITIES,
    CONF_ENTITY_ID,
    CONF_FORCE_UPDATE,
    CONF_NAME,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_CLEANUP,
    CONF_DELETE,
    CONF_EXPIRE_ENABLED,
    CONF_NTFCTN_ENTRIES,
    CONF_SUBSCRIPTION,
)
from .utils.hass_data import HassData

_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeData:
    """Runtime data for notifications."""

    entity: NotificationSwitchEntity
    subbed_entity_id: str | None = None
    unsub: Callable | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize ColorNotify config entry."""
    entity_uids_to_delete: list[str] = config_entry.options.get(CONF_DELETE, [])
    if entity_uids_to_delete:
        new_options = dict(config_entry.options)
        new_options.pop(CONF_DELETE)
        ntfctns = new_options.get(CONF_NTFCTN_ENTRIES, {})
        for entity_uid in entity_uids_to_delete:
            HassData.remove_entity(hass, config_entry.entry_id, entity_uid)

            if entity_uid in ntfctns:
                ntfctns.pop(entity_uid)
            else:
                _LOGGER.warning(
                    "Entity uid %s missing in notifications list", entity_uid
                )
        hass.config_entries.async_update_entry(config_entry, options=new_options)

    ntfctn_entries: dict[str, dict] = config_entry.options.get(CONF_NTFCTN_ENTRIES, {})
    entities_to_use = [
        (
            uid,
            NotificationSwitchEntity(
                hass, unique_id=uid, name=data[CONF_NAME], config_entry=config_entry
            ),
        )
        for uid, data in ntfctn_entries.items()
        if uid not in entity_uids_to_delete
    ]

    if entities_to_use:
        async_add_entities([entity for uid, entity in entities_to_use])
        # Track change subscriptions in runtime data
        runtime_data: dict[str, Any] = HassData.get_config_entry_runtime_data(
            config_entry.entry_id
        )
        runtime_entities = runtime_data.setdefault(CONF_ENTITIES, {})

        # Mark runtime data for subscriptions by creating empty runtime data
        for uid, entity in entities_to_use:
            if uid not in runtime_entities:
                runtime_entities[uid] = RuntimeData(entity=entity)

    if CONF_FORCE_UPDATE in config_entry.options:
        new_options = dict(config_entry.options)
        new_options.pop(CONF_FORCE_UPDATE)
        hass.config_entries.async_update_entry(config_entry, options=new_options)

    # Update the subscriptions
    _subscribe_to_runtime_entities(hass, config_entry)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload a config entry."""
    runtime_data: dict[str, Any] = HassData.get_config_entry_runtime_data(
        config_entry.entry_id
    )
    for unsub in runtime_data.get(CONF_CLEANUP, {}).values():
        if callable(unsub):
            unsub()
    HassData.clear_config_entry_runtime_data(config_entry.entry_id)


async def forward_pooled_update(
    hass: HomeAssistant, config_entry: ConfigEntry, event: Event
) -> None:
    """Forward notifications from this pool along to any pool subscribers."""
    new_state = event.data.get("new_state")
    old_state = event.data.get("old_state")
    if (
        new_state is None
        and old_state is not None
        and old_state.state == STATE_UNAVAILABLE
    ):
        _LOGGER.warning(
            "%s detected deleted entity %s",
            config_entry.title,
            event.data[CONF_ENTITY_ID],
        )

    subs = HassData.get_config_entry_runtime_data(config_entry.entry_id).get(
        CONF_SUBSCRIPTION, []
    )
    for sub in subs:
        if callable(sub):
            await sub(event)

    if new_state is None:
        # Entity was renamed or deleted so resubscribe
        _subscribe_to_runtime_entities(hass, config_entry)


@callback
def _subscribe_to_runtime_entities(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle re-subscribing pool to entities."""
    runtime_data = HassData.get_config_entry_runtime_data(config_entry.entry_id)
    runtime_entities = runtime_data.setdefault(CONF_ENTITIES, {})
    sub_changes: list[RuntimeData] = [
        (uid, entity_data)
        for uid, entity_data in runtime_data[CONF_ENTITIES].items()
        if entity_data.entity is None
        or entity_data.subbed_entity_id != entity_data.entity.entity_id
    ]
    for uid, entity_data in sub_changes:
        # Remove the entity from runtime data if it no longer exists
        if entity_data.entity is None:
            runtime_entities.pop(uid)
            hass.bus.async_fire(
                "state_changed",
                {
                    ATTR_ENTITY_ID: entity_data.subbed_entity_id,
                    "new_state": None,
                    "old_state": None,
                },
            )

        if callable(entity_data.unsub):
            entity_data.unsub()

        if entity_data.entity is not None:
            entity_data.subbed_entity_id = entity_data.entity.entity_id
            entity_data.unsub = async_track_state_change_event(
                hass,
                entity_data.subbed_entity_id,
                partial(forward_pooled_update, hass, config_entry),
            )


class NotificationSwitchEntity(ToggleEntity, RestoreEntity):
    """ColorNotify Light."""

    _attr_should_poll = False

    def __init__(
        self, hass: HomeAssistant, unique_id: str, name: str, config_entry: ConfigEntry
    ) -> None:
        """Initialize notification toggleable."""
        super().__init__()
        self._hass = hass
        self._attr_name = name
        self._attr_unique_id: str = unique_id
        self._attr_is_on = False
        self._config_entry: ConfigEntry = config_entry
        self._timer_callback_canceller: Callable | None = None

        self._attr_extra_state_attributes: dict[str, Any] = config_entry.options.get(
            CONF_NTFCTN_ENTRIES, {}
        ).get(unique_id, {})

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._attr_is_on = True
        self.async_write_ha_state()
        self._start_expire_timer()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Set up before initially adding to HASS."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is None:
            _LOGGER.warning("%s no previous state?", str(self))
            return
        self._attr_is_on = state.state == STATE_ON
        if self.is_on:
            self._start_expire_timer()
        self.async_schedule_update_ha_state(True)

    @callback
    def _start_expire_timer(self):
        self._cancel_expire_timer()
        if not self.extra_state_attributes.get(CONF_EXPIRE_ENABLED, False):
            return

        expire_time = self.extra_state_attributes.get(CONF_DELAY_TIME, None)
        if expire_time is None:
            return
        delay_sec: float = timedelta(**expire_time).seconds
        # If delay is 0 then auto-clear after animation plays
        if delay_sec == 0:
            return

        async def turn_off_wrapper(*args, **kwargs):
            await self.async_turn_off()

        self._timer_callback_canceller = async_call_later(
            self.hass, delay_sec, turn_off_wrapper
        )

    @callback
    def _cancel_expire_timer(self):
        if self._timer_callback_canceller:
            self._timer_callback_canceller()

    async def async_will_remove_from_hass(self):
        """Clean up before removal from HASS."""
        self._cancel_expire_timer()
