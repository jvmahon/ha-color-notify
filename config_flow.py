"""Config flow for Notify Light-er integration."""

from __future__ import annotations

from contextlib import suppress
import logging
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
    PLATFORM_SCHEMA as LIGHT_PLATFORM_SCHEMA,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OperationNotAllowed,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_DELAY_TIME,
    CONF_ENTITY_ID,
    CONF_FORCE_UPDATE,
    CONF_NAME,
    CONF_TYPE,
    CONF_UNIQUE_ID,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_DELETE,
    CONF_EXPIRE_ENABLED,
    CONF_NOTIFY_PATTERN,
    CONF_NTFCTN_ENTRIES,
    CONF_PRIORITY,
    CONF_RGB_SELECTOR,
    DOMAIN,
    TYPE_LIGHT,
    TYPE_POOL,
)

_LOGGER = logging.getLogger(__name__)

WARM_WHITE_RGB = [255, 249, 216]

ADD_NOTIFY_DEFAULTS = {
    CONF_NAME: "New Notification Name",
    CONF_NOTIFY_PATTERN: [],
    CONF_RGB_SELECTOR: WARM_WHITE_RGB,
    CONF_DELAY_TIME: {"seconds": 0},
    CONF_EXPIRE_ENABLED: False,
    CONF_PRIORITY: 1000,
}
ADD_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=ADD_NOTIFY_DEFAULTS[CONF_NAME]): cv.string,
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
            selector.ConstantSelectorConfig(label=CONF_UNIQUE_ID, value="")
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

ADD_POOL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
    }
)

ADD_LIGHT_DEFAULTS = {
    CONF_NAME: "New Notification Light",
    CONF_RGB_SELECTOR: WARM_WHITE_RGB,
}
ADD_LIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=ADD_LIGHT_DEFAULTS[CONF_NAME]): cv.string,
        vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=LIGHT_DOMAIN)
        ),
        vol.Optional(
            CONF_RGB_SELECTOR, default=ADD_LIGHT_DEFAULTS[CONF_RGB_SELECTOR]
        ): selector.ColorRGBSelector(),
    }
)


class HassData:
    """Helper functions for access hass_data."""

    @callback
    @staticmethod
    def get_entry_data(hass: HomeAssistant, config_entry_id: int) -> dict[str, dict]:
        """Return hass_data entries for a ConfigEntry."""
        hass_data: dict = hass.data[DOMAIN]
        entry_data: dict = hass_data.setdefault(config_entry_id, {})
        return entry_data

    @callback
    @staticmethod
    def get_ntfctn_entries(
        hass: HomeAssistant, config_entry_id: int
    ) -> dict[str, dict]:
        """Return notification entries."""
        return HassData.get_entry_data(hass, config_entry_id).setdefault(
            CONF_NTFCTN_ENTRIES, {}
        )

    @callback
    @staticmethod
    def get_entries_by_uuid(
        hass: HomeAssistant, config_entry_id: int
    ) -> dict[str, dict]:
        """Return notification entries by uuid."""
        return HassData.get_ntfctn_entries(hass, config_entry_id).setdefault(
            CONF_UNIQUE_ID, {}
        )

    @callback
    @staticmethod
    def get_all_entities(
        hass: HomeAssistant, config_entry_id: int
    ) -> list[er.RegistryEntry]:
        """Get all entities from a given config_entry."""
        entity_registry = er.async_get(hass)
        return er.async_entries_for_config_entry(entity_registry, config_entry_id)

    @callback
    @staticmethod
    def remove_entity(
        hass: HomeAssistant, config_entry_id: int, unique_id: str
    ) -> bool:
        """Remove an entity by unique id"""
        ret: bool = False
        entity_info = HassData.get_entries_by_uuid(hass, config_entry_id).get(
            unique_id, {}
        )
        if entity_info:
            HassData.get_entries_by_uuid(hass, config_entry_id).pop(
                entity_info[CONF_UNIQUE_ID]
            )
            all_entities = HassData.get_all_entities(hass, config_entry_id)
            entity = next(
                (item for item in all_entities if item.unique_id == unique_id), None
            )
            if entity:
                entity_registry = er.async_get(hass)
                entity_registry.async_remove(entity.entity_id)
                ret = True
        return ret


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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle integration reconfiguration."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if entry.data[CONF_TYPE] == TYPE_LIGHT:
            return await self.async_step_reconfigure_light(user_input)
        elif entry.data[CONF_TYPE] == TYPE_POOL:
            return await self.async_step_reconfigure_pool(user_input)
        else:
            return self.async_abort(
                reason=f"Reconfigure not supported for {str(entry.data[CONF_TYPE])}"
            )

    async def async_step_reconfigure_pool(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguring the light entity."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                title=f"[Collection] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_POOL},
                reason="Changes saved",
            )

        schema = self.add_suggested_values_to_schema(
            ADD_POOL_SCHEMA, suggested_values=entry.data
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    async def async_step_reconfigure_light(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguring the light entity."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                title=f"[Light] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_LIGHT},
                reason="Changes saved",
            )

        schema = self.add_suggested_values_to_schema(
            ADD_LIGHT_SCHEMA, suggested_values=entry.data
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    async def async_step_new_pool(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Pool flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"[Collection] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_POOL},
            )
        return self.async_show_form(step_id="new_pool", data_schema=ADD_POOL_SCHEMA)

    async def async_step_new_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a New Light flow."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"[Light] {user_input[CONF_NAME]}",
                data=user_input | {CONF_TYPE: TYPE_LIGHT},
            )
        return self.async_show_form(step_id="new_light", data_schema=ADD_LIGHT_SCHEMA)

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

    @callback
    def _get_entry_data(self) -> dict[str, dict]:
        return HassData.get_entry_data(self.hass, self.context.get("entry_id", 0))

    @callback
    def _get_ntfctn_entries(self) -> dict[str, dict]:
        return HassData.get_ntfctn_entries(self.hass, self.context.get("entry_id", 0))

    @callback
    def _get_entries_by_uuid(self) -> dict[str, dict]:
        return HassData.get_entries_by_uuid(self.hass, self.context.get("entry_id", 0))

    @callback
    def _get_all_entities(self) -> list[er.RegistryEntry]:
        return HassData.get_all_entities(self.hass, self.context.get("entry_id", 0))


class PoolOptionsFlowHandler(OptionsFlow):
    """Handle options flow for a Pool"""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.config_entry = config_entry

    @callback
    def _get_entry_data(self) -> dict[str, dict]:
        return HassData.get_entry_data(self.hass, self.config_entry.entry_id)

    @callback
    def _get_ntfctn_entries(self) -> dict[str, dict]:
        return HassData.get_ntfctn_entries(self.hass, self.config_entry.entry_id)

    @callback
    def _get_entries_by_uuid(self) -> dict[str, dict]:
        return HassData.get_entries_by_uuid(self.hass, self.config_entry.entry_id)

    @callback
    def _get_all_entities(self) -> list[er.RegistryEntry]:
        return HassData.get_all_entities(self.hass, self.config_entry.entry_id)

    async def _async_trigger_conf_update(
        self, title: str | None = None, data: dict | None = None
    ) -> ConfigFlowResult:
        # Trigger a Config Update by setting a unique force_update_cnt
        force_update_cnt: int = self._get_entry_data().get(CONF_FORCE_UPDATE, 0) + 1
        return self.async_create_entry(
            title=title, data=data | {CONF_FORCE_UPDATE: force_update_cnt}
        )

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

        byUuid = self._get_entries_by_uuid()
        entities = self._get_all_entities()

        # Set up multi-select
        ntfctn_entities = {
            e.unique_id: f"{byUuid.get(e.unique_id, {}).get(CONF_NAME)} [{e.entity_id}]"
            for e in entities
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
        item_data: dict = None
        if uuid := user_input.get(CONF_UNIQUE_ID):
            item_data = self._get_entries_by_uuid().get(uuid)

        if item_data is None:
            return self.async_abort(reason="Can't locate notification to modify")

        if CONF_FORCE_UPDATE in user_input:
            # FORCE_UPDATE was just a flag to indicate modification is done
            user_input.pop(CONF_FORCE_UPDATE)
            return await self.async_step_finish_add_notification(user_input)

        # Merge in default values
        item_data = {**ADD_NOTIFY_DEFAULTS, **item_data}

        schema = self.add_suggested_values_to_schema(
            ADD_NOTIFY_SCHEMA, suggested_values=item_data
        )

        return self.async_show_form(step_id="modify_notification", data_schema=schema)

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
        if user_input is not None:
            # Set 'to delete' entries and trigger reload
            entry_data: dict = dict(self._get_entry_data())
            entry_data[CONF_DELETE] = user_input.get(CONF_DELETE, [])
            return await self._async_trigger_conf_update(data=entry_data)

        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        byUuid = self._get_entries_by_uuid()

        # Set up multi-select
        ntfctn_entities = {e.entity_id: e.original_name for e in entries}
        ntfctn_entities = {
            e.unique_id: f"{byUuid.get(e.unique_id, {}).get(CONF_NAME)} [{e.entity_id}]"
            for e in entries
        }

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_DELETE): cv.multi_select(ntfctn_entities),
            }
        )
        return self.async_show_form(
            step_id="delete_notification", data_schema=options_schema
        )

    async def async_step_finish_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finalize adding the notification."""
        # get hass_data entries
        ntfctn_entries = self._get_ntfctn_entries()

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

        return await self._async_trigger_conf_update(data=self._get_entry_data())


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
