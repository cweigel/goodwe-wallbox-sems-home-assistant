"""Config flow for sems-wallbox integration."""
from __future__ import annotations

from typing import Any
import logging

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
)

from .const import (
    DOMAIN,
    SEMS_CONFIG_SCHEMA,
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
)
from .sems_api import SemsApi

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from SEMS_CONFIG_SCHEMA with values provided by the user.
    """
    _LOGGER.debug("SEMS - Start validation config flow user input")
    api = SemsApi(hass, data[CONF_USERNAME], data[CONF_PASSWORD])

    authenticated = await hass.async_add_executor_job(api.test_authentication)
    if not authenticated:
        raise InvalidAuth

    return data


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for sems-wallbox."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=SEMS_CONFIG_SCHEMA,
            )

        errors: dict[str, str] = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected exception during config flow")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=info[CONF_STATION_ID],
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=SEMS_CONFIG_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler (Configure v UI)."""
        return SemsWallboxOptionsFlowHandler(config_entry)


class SemsWallboxOptionsFlowHandler(OptionsFlow):
    """Handle options for SEMS Wallbox (např. scan_interval)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Store the config entry."""
        # POZOR: OptionsFlow má property config_entry bez setteru,
        # proto MUSÍME použít jiný název, např. _config_entry
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Uložíme jen scan_interval do options (entry.options)
            return self.async_create_entry(title="", data=user_input)

        # Aktuální hodnota – nejdřív options, pak fallback do data, pak default
        current_scan_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current_scan_interval,
                ): cv.positive_int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
