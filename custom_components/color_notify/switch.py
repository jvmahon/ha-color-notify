"""Switch platform for Notify Switch-er integration."""

from collections.abc import Callable
from datetime import timedelta
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DELAY_TIME,
    CONF_ENTITIES,
    CONF_FORCE_UPDATE,
    CONF_NAME,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize ColorNotify config entry."""
    runtime_data: dict[str, Any] = HassData.get_config_entry_runtime_data(
        config_entry.entry_id
    )
    runtime_entities = runtime_data.setdefault(CONF_ENTITIES, {})

    entries: dict[str, dict] = config_entry.options.get(CONF_NTFCTN_ENTRIES, {})

    entities_to_delete: list[str] = config_entry.options.get(CONF_DELETE, [])
    if entities_to_delete:
        new_options = dict(config_entry.options)
        new_options.pop(CONF_DELETE)
        ntfctns = new_options.get(CONF_NTFCTN_ENTRIES, {})
        for entity_uid in entities_to_delete:
            HassData.remove_entity(hass, config_entry.entry_id, entity_uid)
            if entity_uid in ntfctns:
                ntfctns.pop(entity_uid)
            else:
                _LOGGER.warning(
                    "Entity uid %s missing in notifications list", entity_uid
                )
        hass.config_entries.async_update_entry(config_entry, options=new_options)
    post_del_entries: dict[str, dict] = config_entry.options.get(
        CONF_NTFCTN_ENTRIES, {}
    )
    entities_to_use = [
        (
            uid,
            NotificationSwitchEntity(
                hass, unique_id=uid, name=data[CONF_NAME], config_entry=config_entry
            ),
        )
        for uid, data in entries.items()
        if uid not in entities_to_delete
    ]

    if entities_to_use:
        async_add_entities([entity for uid, entity in entities_to_use])

        # Track change subscriptions in runtime data
        runtime_subs = runtime_data.setdefault(CONF_CLEANUP, {})
        for uid, entity in entities_to_use:
            if entity.entity_id in runtime_subs:
                continue
            runtime_entities[uid] = entity
            runtime_subs[entity.entity_id] = async_track_state_change_event(
                hass,
                entity.entity_id,
                partial(forward_pooled_update, hass, config_entry),
            )

    if CONF_FORCE_UPDATE in config_entry.options:
        new_options = dict(config_entry.options)
        new_options.pop(CONF_FORCE_UPDATE)
        hass.config_entries.async_update_entry(config_entry, options=new_options)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload a config entry."""
    runtime_data: dict[str, Any] = HassData.get_config_entry_runtime_data(
        config_entry.entry_id
    )
    for unsub in runtime_data.get(CONF_CLEANUP, {}).values():
        if callable(unsub):
            unsub()
    HassData.clear_config_entry_runtime_data(config_entry.entry_id)


async def forward_pooled_update(hass: HomeAssistant, config_entry: ConfigEntry, *args):
    """Forward notifications from this pool along to any pool subscribers."""
    subs = HassData.get_config_entry_runtime_data(config_entry.entry_id).get(
        CONF_SUBSCRIPTION, []
    )
    for sub in subs:
        if callable(sub):
            await sub(*args)


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
