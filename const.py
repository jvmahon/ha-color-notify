"""Constants for the Notify Light-er integration."""

from typing import Final

DOMAIN: Final = "notify_lighter"

TYPE_POOL: Final = "pool"
TYPE_LIGHT: Final = "light"

CONF_RGB_SELECTOR: Final = "color_picker"
CONF_NOTIFY_PATTERN: Final = "pattern"
CONF_EXPIRE_DELAY: Final = "expire_delay"
CONF_EXPIRE_ENABLED: Final = "expire_enabled"
CONF_NTFCTN_ENTRIES: Final = "ntfctn_entries"
CONF_PRIORITY: Final = "priority"
CONF_DELETE: Final = "delete"
CONF_ADD: Final = "add"
CONF_ENTRY_ID: Final = "entry_id"

OFF_RGB: Final = (0, 0, 0)
WARM_WHITE_RGB: Final = (255, 249, 216)

DEFAULT_PRIORITY: Final = 1000
