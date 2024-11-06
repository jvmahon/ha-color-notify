"""The ColorNotify integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_NAME, CONF_TYPE, Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, TYPE_LIGHT, TYPE_POOL

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SWITCH]

type ColorNotifyConfigEntry = ConfigEntry[ColorNotifyData]  # noqa: F821


class ColorNotifyData:
    pass


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    async def handle_hello(call: ServiceCall):
        """Handle the service action call."""
        name = call.data.get(ATTR_NAME, "Default")

        hass.states.async_set("hello_action.hello", name)

    hass.services.async_register(DOMAIN, "hello", handle_hello)

    # Return boolean to indicate that initialization was successful.
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ColorNotifyConfigEntry) -> bool:
    """Set up new entities from a config entry."""

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = dict(entry.data)

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


# TODO Update entry annotation
async def async_unload_entry(
    hass: HomeAssistant, entry: ColorNotifyConfigEntry
) -> bool:
    """Unload a config entry."""
    item_type = entry.data.get(CONF_TYPE, None)
    if item_type == TYPE_LIGHT:
        await hass.config_entries.async_unload_platforms(entry, [Platform.LIGHT])
    elif item_type == TYPE_POOL:
        await hass.config_entries.async_unload_platforms(entry, [Platform.SWITCH])
    else:
        _LOGGER.error("Unknown entry type '%s'", item_type)
    hass.data[DOMAIN].pop(entry.entry_id)

    return True
