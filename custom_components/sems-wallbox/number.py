"""
Support for number entity controlling GoodWe SEMS Wallbox charge power.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
)
from homeassistant.config_entries import ConfigEntry
    # type: ignore[import]
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SemsUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

NUMBER_VERSION = "0.3.1"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add numbers for passed config_entry in HA."""
    runtime = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: SemsUpdateCoordinator = runtime["coordinator"]
    api = runtime["api"]

    _LOGGER.debug(
        "Setting up SemsNumber entities (version %s) for entry %s",
        NUMBER_VERSION,
        config_entry.entry_id,
    )

    entities: list[SemsNumber] = []
    for sn, data in coordinator.data.items():
        set_charge_power = data.get("set_charge_power")
        entities.append(SemsNumber(coordinator, sn, api, set_charge_power))

    async_add_entities(entities)


class SemsNumber(CoordinatorEntity, NumberEntity):
    """Number entity for setting wallbox charge power."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: SemsUpdateCoordinator, sn: str, api, value: float):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.api = api
        self.sn = sn
        self._attr_native_value = float(value) if value is not None else None
        _LOGGER.debug(
            "Creating SemsNumber (v%s) for Wallbox %s, initial value=%s",
            NUMBER_VERSION,
            self.sn,
            self._attr_native_value,
        )

    @property
    def name(self) -> str:
        """Return the name of the number entity."""
        return "Wallbox set charge power"

    @property
    def device_class(self):
        return NumberDeviceClass.POWER

    @property
    def native_unit_of_measurement(self):
        return UnitOfPower.KILO_WATT

    @property
    def native_step(self):
        return 0.1

    @property
    def native_min_value(self):
        return 4.2

    @property
    def native_max_value(self):
        return 11

    @property
    def unique_id(self) -> str:
        # stejné chování, jen f-string
        return f"{self.coordinator.data[self.sn]['sn']}_number_set_charge_power"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.sn)},
            "name": self.name,
            "manufacturer": "GoodWe",
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
        _LOGGER.debug("SemsNumber added to hass for wallbox %s", self.sn)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data[self.sn]
        set_charge_power = data.get("set_charge_power")
        if set_charge_power is not None:
            try:
                self._attr_native_value = float(set_charge_power)
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "SemsNumber %s: invalid set_charge_power value %r from API",
                    self.sn,
                    set_charge_power,
                )
        _LOGGER.debug(
            "SemsNumber coordinator update SN=%s → native_value=%s",
            self.sn,
            self._attr_native_value,
        )
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Manual update from HA (e.g. z UI)."""
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data[self.sn]
        set_charge_power = data.get("set_charge_power")
        if set_charge_power is not None:
            try:
                self._attr_native_value = float(set_charge_power)
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "SemsNumber %s: invalid set_charge_power value %r from API (async_update)",
                    self.sn,
                    set_charge_power,
                )
        _LOGGER.debug(
            "Updating SemsNumber for Wallbox %s state to %s (async_update)",
            self.sn,
            self._attr_native_value,
        )
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Handle change from UI slider."""
        data = self.coordinator.data.get(self.sn, {})
        active_mode = data.get("chargeMode", 0)

        _LOGGER.debug(
            "Setting set_charge_power for SN=%s to %s (active_mode=%s)",
            self.sn,
            value,
            active_mode,
        )

        # 1) Optimisticky nastavíme hodnotu v UI
        self._attr_native_value = float(value)
        self.async_write_ha_state()

        # 2) Zavoláme SEMS API v executor jobu
        await self.hass.async_add_executor_job(
            self.api.set_charge_mode,
            self.sn,
            0 if value > 4.2 else active_mode,
            value,
        )

        # 3) Naplánujeme refresh z API (NEčekáme na něj, aby slider nevisel)
        self.hass.async_create_task(self.coordinator.async_request_refresh())
