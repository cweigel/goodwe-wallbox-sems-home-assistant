"""Constants for the sems integration."""

DOMAIN = "sems-wallbox"

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_SCAN_INTERVAL

CONF_STATION_ID = "wallbox_serial_No"

# Default polling interval (seconds)
DEFAULT_SCAN_INTERVAL = 60

# Validation of the user's configuration
# POZN: scan_interval zde necháváme jen jako optional – uživatel ho může nastavit hned při přidání integrace,
# ale runtime stejně použije hodnotu z options (pokud existuje).
SEMS_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_STATION_ID): str,
        vol.Optional(
            CONF_SCAN_INTERVAL,
            description={"suggested_value": DEFAULT_SCAN_INTERVAL},
        ): cv.positive_int,
    }
)
