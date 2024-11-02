"""Switch platform for Notify Switch-er integration."""

from datetime import timedelta
from functools import cached_property
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DELAY_TIME, CONF_NAME, CONF_UNIQUE_ID, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_DELETE, CONF_EXPIRE_ENABLED, CONF_NTFCTN_ENTRIES
from .utils.hass_data import HassData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Notify Light-er config entry."""
    # Update hass.data with any options
    config = HassData.get_entry_data(hass, config_entry.entry_id)
    if config_entry.options:
        config.update(config_entry.options)
    config.update({CONF_UNIQUE_ID: config_entry.entry_id})
    existing_entities = HassData.get_all_entities(hass, config_entry)
    existing_unique_ids = {
        entry.unique_id.lower(): entry for entry in existing_entities
    }

    entries: dict[str, dict] = config.get(CONF_NTFCTN_ENTRIES, {})
    # Filter to only add new entries
    new_entities: dict[str, dict] = {
        uid: data
        for uid, data in entries.get(CONF_UNIQUE_ID, {}).items()
        if uid.lower() not in existing_unique_ids
    }

    entities_to_delete: list[str] = config_entry.options.get(CONF_DELETE, [])
    if entities_to_delete:
        new_options = dict(config_entry.options)
        new_options.pop(CONF_DELETE)
        hass.config_entries.async_update_entry(config_entry, options=new_options)
        for entity_uid in entities_to_delete:
            HassData.remove_entity(hass, config_entry.entry_id, entity_uid)

    entities_to_add = [
        NotificationSwitchEntity(
            hass, unique_id=uid, name=data[CONF_NAME], config_entry=config_entry
        )
        for uid, data in new_entities.items()
        if uid not in entities_to_delete
    ]

    if entities_to_add:
        async_add_entities(entities_to_add)


class NotificationSwitchEntity(ToggleEntity, RestoreEntity):
    """notify_lighter Light."""

    _attr_should_poll = False

    def __init__(
        self, hass: HomeAssistant, unique_id: str, name: str, config_entry: ConfigEntry
    ) -> None:
        """Initialize notify_lighter light."""
        super().__init__()
        self._hass = hass
        self._attr_name = name
        self._attr_unique_id: str = unique_id
        self._attr_is_on = False
        self._config_entry: ConfigEntry = config_entry
        self._timer_callback_canceller: Callable | None = None
        hass_data: dict[str, dict] = HassData.get_ntfctn_entries(
            hass, config_entry.entry_id
        )
        self._attr_extra_state_attributes: dict[str, Any] = hass_data.get(
            CONF_UNIQUE_ID, {}
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
        delay_sec = timedelta(**expire_time)

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
