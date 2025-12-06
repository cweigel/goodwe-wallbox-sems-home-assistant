"""
Support for switch controlling an output of a GoodWe SEMS wallbox.

For more details about this platform, please refer to the documentation at
https://github.com/TimSoethout/goodwe-sems-home-assistant
"""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SemsUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SWITCH_VERSION = "0.3.3"

# Jak dlouho po příkazu ON ignorujeme „Waiting/power=0“ a držíme optimistický ON (v sekundách)
GRACE_ON_SECONDS = 130

# Volitelné – jak dlouho po příkazu OFF tolerujeme, že API může ještě krátce hlásit power>0
GRACE_OFF_SECONDS = 130


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add switches for passed config_entry in HA."""
    runtime = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: SemsUpdateCoordinator = runtime["coordinator"]
    api = runtime["api"]

    _LOGGER.debug(
        "Setting up SemsSwitch entities (version %s) for entry %s",
        SWITCH_VERSION,
        config_entry.entry_id,
    )

    entities: list[SemsSwitch] = []
    for sn, data in coordinator.data.items():
        status = data.get("status")
        power = float(data.get("power", 0) or 0)
        current_is_on = status == "EVDetail_Status_Title_Charging" or power > 0
        entities.append(SemsSwitch(coordinator, sn, api, current_is_on))

    async_add_entities(entities)


class SemsSwitch(CoordinatorEntity, SwitchEntity):
    """Switch to start/stop charging."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsUpdateCoordinator,
        sn: str,
        api,
        current_is_on: bool,
    ) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.api = api
        self.sn = sn
        self._attr_is_on = current_is_on

        # pro grace period
        self._last_command_ts: float | None = None
        self._last_command_target: bool | None = None

        _LOGGER.debug(
            "Creating SemsSwitch (v%s) for Wallbox %s, initial is_on=%s",
            SWITCH_VERSION,
            self.sn,
            self._attr_is_on,
        )

    # ---------- základní vlastnosti ----------

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return "Start charging"

    @property
    def device_class(self):
        return SwitchDeviceClass.SWITCH

    @property
    def unique_id(self) -> str:
        return f"{self.coordinator.data[self.sn]['sn']}-switch-start-charging"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.sn)},
            "name": self.name,
            "manufacturer": "GoodWe",
        }

    @property
    def available(self):
        """Return if entity is available."""
        return self.coordinator.last_update_success

    # ---------- helper pro vyhodnocení stavu z API + grace ----------

    def _compute_is_on_from_data(self, data: dict) -> bool:
        """Spočítá finální is_on z API + zohlední grace period po posledním příkazu."""
        status = data.get("status")
        power = float(data.get("power", 0) or 0)

        api_is_on = status == "EVDetail_Status_Title_Charging" or power > 0

        now = self.hass.loop.time()
        target = self._last_command_target
        ts = self._last_command_ts

        # Pokud jsme nedávno poslali ON a API pořád tvrdí "Waiting/power=0",
        # tak nějakou dobu držíme optimistický ON.
        if (
            target is True
            and ts is not None
            and now - ts < GRACE_ON_SECONDS
            and not api_is_on
        ):
            _LOGGER.debug(
                "SemsSwitch %s: within ON grace (%.1fs < %.1fs), "
                "API status=%s, power=%s -> držím is_on=True",
                self.sn,
                now - ts,
                GRACE_ON_SECONDS,
                status,
                power,
            )
            return True

        # Pokud jsme nedávno poslali OFF a API ještě krátce ukazuje power>0,
        # můžeme krátce držet OFF (typicky kratší doba než pro ON).
        if (
            target is False
            and ts is not None
            and now - ts < GRACE_OFF_SECONDS
            and api_is_on
        ):
            _LOGGER.debug(
                "SemsSwitch %s: within OFF grace (%.1fs < %.1fs), "
                "API status=%s, power=%s -> držím is_on=False",
                self.sn,
                now - ts,
                GRACE_OFF_SECONDS,
                status,
                power,
            )
            return False

        # Mimo grace period nebo stav už sedí – přebíráme přímo z API
        if target is not None and api_is_on == target:
            # Stav z API už odpovídá poslednímu příkazu, můžeme grace „vyčistit“
            self._last_command_target = None
            self._last_command_ts = None

        _LOGGER.debug(
            "SemsSwitch %s: API status=%s, power=%s -> is_on=%s (no grace override)",
            self.sn,
            status,
            power,
            api_is_on,
        )
        return api_is_on

    # ---------- ovládání switche ----------

    async def async_turn_off(self, **kwargs):
        _LOGGER.debug("Wallbox %s set to Off (optimistic UI + OFF grace)", self.sn)

        # 1) uložíme info o příkazu pro grace logiku
        self._last_command_target = False
        self._last_command_ts = self.hass.loop.time()

        # 2) OPTIMISTICKY přepneme UI hned
        self._attr_is_on = False
        self.async_write_ha_state()

        # 3) naplánujeme refresh z API (NEčekáme na něj)
        self.hass.async_create_task(self.coordinator.async_request_refresh())

        # 4) pošleme příkaz na SEMS API
        await self.hass.async_add_executor_job(self.api.change_status, self.sn, 2)

    async def async_turn_on(self, **kwargs):
        _LOGGER.debug("Wallbox %s set to On (optimistic UI + ON grace)", self.sn)

        # 1) uložíme info o příkazu pro grace logiku
        self._last_command_target = True
        self._last_command_ts = self.hass.loop.time()

        # 2) OPTIMISTICKY přepneme UI hned
        self._attr_is_on = True
        self.async_write_ha_state()

        # 3) naplánujeme refresh z API (NEčekáme na něj)
        self.hass.async_create_task(self.coordinator.async_request_refresh())

        # 4) pošleme příkaz na SEMS API
        await self.hass.async_add_executor_job(self.api.change_status, self.sn, 1)

    # ---------- napojení na coordinator ----------

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("SemsSwitch added to hass for wallbox %s", self.sn)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data[self.sn]
        self._attr_is_on = self._compute_is_on_from_data(data)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Manual update (např. z UI)."""
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data[self.sn]
        self._attr_is_on = self._compute_is_on_from_data(data)
        self.async_write_ha_state()
