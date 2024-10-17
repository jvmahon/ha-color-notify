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
    CONF_CUSTOM_TEXT,
    CONF_RGB_SELECTOR,
    CONF_NOTIFY_PATTERN,
    CONF_EXPIRE_ENABLED,
    CONF_NTFCTN_ENTRIES,
    CONF_PRIORITY,
)


ADD_NOTIFY_DEFAULTS = {
    CONF_NOTIFY_PATTERN: [],
    CONF_RGB_SELECTOR: [0, 0, 0],
    CONF_DELAY_TIME: {"seconds": 0},
    CONF_EXPIRE_ENABLED: False,
    CONF_PRIORITY: 1000,
}
ADD_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(
            CONF_PRIORITY, default=ADD_NOTIFY_DEFAULTS[CONF_PRIORITY]
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(
            CONF_EXPIRE_ENABLED, default=ADD_NOTIFY_DEFAULTS[CONF_EXPIRE_ENABLED]
        ): cv.boolean,
        vol.Optional(
            CONF_DELAY_TIME, default=ADD_NOTIFY_DEFAULTS[CONF_DELAY_TIME]
        ): selector.DurationSelector(selector.DurationSelectorConfig()),
        vol.Optional(
            CONF_RGB_SELECTOR, default=ADD_NOTIFY_DEFAULTS[CONF_RGB_SELECTOR]
        ): selector.ColorRGBSelector(),
        vol.Optional(
            CONF_NOTIFY_PATTERN, default=ADD_NOTIFY_DEFAULTS[CONF_NOTIFY_PATTERN]
        ): selector.TextSelector(
            selector.TextSelectorConfig(
                multiple=True,
            )
        ),
        vol.Optional(CONF_UNIQUE_ID): selector.ConstantSelector(
            selector.ConstantSelectorConfig(label="UID", value="")
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
        if user_input is not None:
            return await self.async_step_modify_notification(user_input)

        hass_data: dict = self.hass.data[DOMAIN]
        entry_data: dict = hass_data.get(self.config_entry.entry_id, {})
        ntfctn_entries: dict[str, dict] = entry_data.get(CONF_NTFCTN_ENTRIES, {})
        byUuid: dict[str, dict] = ntfctn_entries.get(CONF_UNIQUE_ID, {})

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        # Set up multi-select
        ntfctn_entities = {
            e.unique_id: f"{byUuid.get(e.unique_id, {}).get(CONF_NAME)} [{e.entity_id}]"
            for e in entries
        }

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

        if item_data is None:
            return self.async_abort(reason="Can't locate notification to modify")

        if CONF_FORCE_UPDATE in user_input:
            # FORCE_UPDATE was just a flag to indicate modification is done
            user_input.pop(CONF_FORCE_UPDATE)
            return await self.async_step_finish_add_notification(user_input)

        # Merge in default values
        item_data = {**ADD_NOTIFY_DEFAULTS, **item_data}

        # TODO: Is it possible to progmatically clone this?
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
                vol.Optional(
                    CONF_UNIQUE_ID, default=item_data.get(CONF_UNIQUE_ID)
                ): selector.ConstantSelector(
                    selector.ConstantSelectorConfig(
                        label="", value=item_data.get(CONF_UNIQUE_ID)
                    )
                ),
                # Flag to indicate modify_notification has been submitted
                vol.Optional(
                    CONF_FORCE_UPDATE, default=True
                ): selector.ConstantSelector(
                    selector.ConstantSelectorConfig(label="", value=True)
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
        if user_input is not None:
            pass
        """Launch the Delete Notification form."""
        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        # Set up multi-select
        ntfctn_entities = {e.entity_id: e.original_name for e in entries}

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

        # ensure defaults are set
        user_input = {**ADD_NOTIFY_DEFAULTS, **user_input}
        name = user_input.get(CONF_NAME)
        uuid = user_input.get(CONF_UNIQUE_ID)
        if uuid is None:
            uuid = ntfctn_entries.get(CONF_NAME, {}).get(name, {}).get(CONF_UNIQUE_ID)
            uuid = uuid or uuid4().hex
            user_input[CONF_UNIQUE_ID] = uuid

        # Add to the entry to hass_data
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
