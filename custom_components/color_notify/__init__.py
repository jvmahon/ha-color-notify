"""The ColorNotify integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY, TYPE_LIGHT, TYPE_POOL
from .utils.hass_data import HassData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up new entities from a config entry."""

    HassData.get_domain_data(hass)[entry.entry_id] = {
        CONF_TYPE: entry.data[CONF_TYPE],
        CONF_ENTRY: entry,
    }

    ok = True
    item_type = entry.data.get(CONF_TYPE, None)
    if item_type == TYPE_LIGHT:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.LIGHT])
        entry.async_on_unload(entry.add_update_listener(handle_config_updated))
    elif item_type == TYPE_POOL:
        # Register to reload config if options flow updates it
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SWITCH])
        entry.async_on_unload(entry.add_update_listener(handle_config_updated))
    else:
        _LOGGER.error("Unknown entry type '%s'", item_type)
        ok = False

    return ok


async def handle_config_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    item_type = entry.data.get(CONF_TYPE, None)
    if item_type == TYPE_LIGHT:
        await hass.config_entries.async_unload_platforms(entry, [Platform.LIGHT])
    elif item_type == TYPE_POOL:
        await hass.config_entries.async_unload_platforms(entry, [Platform.SWITCH])
    else:
        _LOGGER.error("Unknown entry type '%s'", item_type)
    HassData.get_domain_data(hass).pop(entry.entry_id)

    return True
