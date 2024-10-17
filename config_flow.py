"""Config flow for Notify Light-er integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from contextlib import suppress
from uuid import uuid4

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
    PLATFORM_SCHEMA as LIGHT_PLATFORM_SCHEMA,
)

from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_NAME,
    CONF_DELAY_TIME,
    Platform,
    CONF_TYPE,
    CONF_TIMEOUT,
    CONF_UNIQUE_ID,
    CONF_FORCE_UPDATE,
)
from homeassistant.helpers import selector, translation, entity_registry as er
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
)
from homeassistant.config_entries import (
    ConfigEntry,
    OptionsFlow,
    ConfigFlow,
    ConfigFlowResult,
    OperationNotAllowed,
)
from homeassistant.core import callback
from .const import (
    DOMAIN,
    TYPE_LIGHT,
    TYPE_POOL,
    TYPE_NOTIFICATION,
    CONF_CUSTOM_TEXT,
    CONF_RGB_SELECTOR,
    CONF_NOTIFY_PATTERN,
    CONF_EXPIRE_DELAY,
    CONF_EXPIRE_ENABLED,
    CONF_NTFCTN_ENTRIES,
    CONF_PRIORITY,
)


ADD_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_PRIORITY, default=1000): selector.NumberSelector(
            selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_EXPIRE_ENABLED, default=False): cv.boolean,
        vol.Optional(CONF_DELAY_TIME): selector.DurationSelector(
            selector.DurationSelectorConfig()
        ),
        vol.Optional(CONF_RGB_SELECTOR): selector.ColorRGBSelector(),
        vol.Optional(CONF_NOTIFY_PATTERN): selector.TextSelector(
            selector.TextSelectorConfig(
                multiple=True,
            )
        ),
    }
)

ADD_NOTIFY_SAMPLE_SCHEMA = ADD_NOTIFY_SCHEMA.extend(
    {
        vol.Optional(
            CONF_NOTIFY_PATTERN,
            default=["[", "#FF0000,250", "#0000FF,250", "],3", "#FFFFFF"],
        ): selector.TextSelector(
            selector.TextSelectorConfig(
                multiple=True,
            )
        ),
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=LIGHT_DOMAIN)
        ),
        vol.Optional(CONF_CUSTOM_TEXT): selector.TextSelector(
            selector.TextSelectorConfig(
                multiline=True,  # Set to True if you want a multiline text box,
                multiple=True,
            )
        ),
        vol.Optional(CONF_CUSTOM_TEXT): selector.ColorRGBSelector(),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
    }
).extend(OPTIONS_SCHEMA.schema)

ADD_POOL_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
    }
)

CONFIG_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "user": SchemaFlowFormStep(CONFIG_SCHEMA)
}

OPTIONS_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "init": SchemaFlowFormStep(OPTIONS_SCHEMA)
}


class ConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config or options flow for Notify Light-er."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        menu_options = ["new_pool", "new_light"]
        return self.async_show_menu(
            menu_options=menu_options,
        )

    async def async_step_new_pool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Pool flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["name"],
                data={CONF_TYPE: TYPE_POOL},
            )
        return self.async_show_form(step_id="new_pool", data_schema=ADD_POOL_SCHEMA)

    async def async_step_new_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Light flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["name"],
                data={"entity_id": user_input["entity_id"], CONF_TYPE: TYPE_LIGHT},
            )
        return self.async_show_form(step_id="new_light", data_schema=CONFIG_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        item_type = config_entry.data.get(CONF_TYPE, None)
        if item_type == TYPE_LIGHT:
            return LightOptionsFlowHandler(config_entry)
        elif item_type == TYPE_POOL:
            return PoolOptionsFlowHandler(config_entry)
        raise NotImplementedError


class PoolOptionsFlowHandler(OptionsFlow):
    """Handle options flow for a Pool"""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        # forward to pool_init to differentiate in strings.json
        return await self.async_step_pool_init(user_input)

    async def async_step_pool_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        return self.async_show_menu(
            step_id="pool_init",
            menu_options=[
                "add_notification",
                "add_notification_sample",
                "modify_notification_select",
                "delete_notification",
            ],
        )

    async def async_step_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form."""
        if user_input is not None:
            return await self.async_step_finish_add_notification(user_input)
        return self.async_show_form(
            step_id="add_notification", data_schema=ADD_NOTIFY_SCHEMA
        )

    async def async_step_add_notification_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form with sample."""
        return self.async_show_form(
            step_id="add_notification", data_schema=ADD_NOTIFY_SAMPLE_SCHEMA
        )

    async def async_step_modify_notification_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Modify Notification Selection form."""
        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        # Set up multi-select
        ntfctn_entities = {
            e.unique_id: f"{e.original_name} [{e.entity_id}]" for e in entries
        }

        if user_input is not None:
            return await self.async_step_modify_notification(user_input)

        options_schema = vol.Schema(
            {vol.Required(CONF_UNIQUE_ID): vol.In(ntfctn_entities)}
        )
        return self.async_show_form(
            step_id="modify_notification_select", data_schema=options_schema
        )

    async def async_step_modify_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Modify Notification form."""
        hass_data: dict = self.hass.data[DOMAIN]
        entry_data: dict = hass_data.get(self.config_entry.entry_id, {})
        ntfctn_entries: dict[str, dict] = entry_data.get(CONF_NTFCTN_ENTRIES, {})
        item_data: dict = None
        if uuid := user_input.get(CONF_UNIQUE_ID):
            item_data = ntfctn_entries[CONF_UNIQUE_ID][uuid]
        elif name := user_input.get(CONF_NAME):
            item_data = ntfctn_entries[CONF_NAME][name]

        if item_data is None:
            return self.async_abort("Can't locate notification to modify")

        # TODO: Progmatically clone this?
        new_schema = ADD_NOTIFY_SCHEMA.extend(
            {
                vol.Required(CONF_NAME, default=item_data.get(CONF_NAME)): cv.string,
                vol.Required(
                    CONF_PRIORITY, default=item_data.get(CONF_PRIORITY)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_EXPIRE_ENABLED,
                    default=item_data.get(CONF_EXPIRE_ENABLED),
                ): cv.boolean,
                vol.Optional(
                    CONF_DELAY_TIME, default=item_data.get(CONF_DELAY_TIME)
                ): selector.DurationSelector(selector.DurationSelectorConfig()),
                vol.Optional(
                    CONF_RGB_SELECTOR, default=item_data.get(CONF_RGB_SELECTOR)
                ): selector.ColorRGBSelector(),
                vol.Optional(
                    CONF_NOTIFY_PATTERN,
                    default=item_data.get(CONF_NOTIFY_PATTERN),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiple=True,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="modify_notification", data_schema=new_schema
        )

    async def async_step_add_notification_sample(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Add Notification form with sample."""
        return self.async_show_form(
            step_id="add_notification", data_schema=ADD_NOTIFY_SAMPLE_SCHEMA
        )

    async def async_step_delete_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the Delete Notification form."""
        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        # Set up multi-select
        ntfctn_entities = {e.entity_id: e.original_name for e in entries}

        if user_input is not None:
            pass

        options_schema = vol.Schema(
            {
                vol.Optional("delete_uuids"): cv.multi_select(ntfctn_entities),
            }
        )
        return self.async_show_form(
            step_id="delete_notification", data_schema=options_schema
        )

    async def async_step_finish_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize adding the notification."""
        hass_data: dict = self.hass.data[DOMAIN]
        entry_data: dict = dict(hass_data.get(self.config_entry.entry_id, {}))
        ntfctn_entries: dict[str, dict] = entry_data.get(CONF_NTFCTN_ENTRIES, {})

        # Make a change to ensure the update handler is called
        update_cnt: int = entry_data.get(CONF_FORCE_UPDATE, 0)
        update_cnt += 1

        uuid = uuid4().hex
        name = user_input.get(CONF_NAME)
        user_input[CONF_UNIQUE_ID] = uuid
        ntfctn_entries.setdefault(CONF_UNIQUE_ID, {})[uuid] = user_input
        ntfctn_entries.setdefault(CONF_NAME, {})[name] = user_input

        return self.async_create_entry(
            title=None,
            data={CONF_NTFCTN_ENTRIES: ntfctn_entries, CONF_FORCE_UPDATE: update_cnt},
        )  # updates config .options and triggers reload


class LightOptionsFlowHandler(OptionsFlow):
    """Handle an options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Launch the options flow."""
        if user_input is not None:
            # OperationNotAllowed: ZHA is not running
            with suppress(OperationNotAllowed):
                await self.hass.config_entries.async_unload(self.config_entry.entry_id)
            return self.async_create_entry(
                title="LightOptionsEntry", data={"data_key1": "data_val1"}
            )
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "add_device": "Add Device",
                "coord_config": "Coordinator Config",
            },
        )

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Virtual step for when the user is reconfiguring the integration."""

        if user_input is not None:
            return self.async_create_entry(
                title="TestEntryTitle", data={"data_key": "data_val"}
            )

        return self.async_show_form(step_id="test2")

    def async_remove(self):
        """Maybe reload ZHA if the flow is aborted."""
        # if self.config_entry.state not in (
        #     ConfigEntryState.SETUP_ERROR,
        #     ConfigEntryState.NOT_LOADED,
        # ):
        #     return

        self.hass.async_create_task(
            self.hass.config_entries.async_setup(self.config_entry.entry_id)
        )
