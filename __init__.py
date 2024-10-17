"""The NotifyLighter integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, TYPE_LIGHT, TYPE_POOL, TYPE_NOTIFICATION

from homeassistant.const import Platform, ATTR_NAME, CONF_TYPE

from typing import Any

import logging

_LOGGER = logging.getLogger(__name__)

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SWITCH]

# TODO Create ConfigEntry type alias with API object
# TODO Rename type alias and update all entry annotations
type NotifyLighterConfigEntry = ConfigEntry[NotifyLighterData]  # noqa: F821


class NotifyLighterData:
    pass


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    async def handle_hello(call: ServiceCall):
        """Handle the service action call."""
        name = call.data.get(ATTR_NAME, "Default")

        hass.states.async_set("hello_action.hello", name)

    hass.services.async_register(DOMAIN, "hello", handle_hello)

    # Return boolean to indicate that initialization was successful.
    return True


# TODO Update entry annotation
async def async_setup_entry(
    hass: HomeAssistant, entry: NotifyLighterConfigEntry
) -> bool:
    """Set up test_test_test from a config entry."""

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = dict(entry.data)

    # TODO 1. Create API instance
    # TODO 2. Validate the API connection (and authentication)
    # TODO 3. Store an API object for your platforms to access
    # entry.runtime_data = MyAPI(...)

    _LOGGER.error(f"async_setup_entry {entry} {entry.data}")
    ok = True
    item_type = entry.data.get(CONF_TYPE, None)
    if item_type == TYPE_LIGHT:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.LIGHT])
    elif item_type == TYPE_POOL:
        # Register to reload config if options flow updates it
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SWITCH])
        entry.async_on_unload(entry.add_update_listener(handle_pool_config_updated))
    elif item_type == TYPE_NOTIFICATION:
        pass
    else:
        _LOGGER.error("Unknown entry type '%s'", item_type)
        ok = False

    return ok


async def handle_pool_config_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    _LOGGER.error(f"handle_pool_config_updated {entry}")
    hass.config_entries.async_schedule_reload(entry.entry_id)


# TODO Update entry annotation
async def async_unload_entry(
    hass: HomeAssistant, entry: NotifyLighterConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.error(f"async_unload_entry {entry}")
    item_type = entry.data.get(CONF_TYPE, None)
    if item_type == TYPE_LIGHT:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    elif item_type == TYPE_POOL:
        await hass.config_entries.async_unload_platforms(entry, [Platform.SWITCH])
    elif item_type == TYPE_NOTIFICATION:
        pass
    else:
        _LOGGER.error("Unknown entry type '%s'", item_type)
    hass.data[DOMAIN].pop(entry.entry_id)

    return True
