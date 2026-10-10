"""Config flow for ecoControl Floor Heating."""

import asyncio
import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from . import (
    DOMAIN, 
    DEFAULT_POLL_INTERVAL, 
    CONF_POLL_INTERVAL,
    parse_name_from_mfr,
    parse_floor_temp_from_mfr
)

ECOCONTROL_MFR_ID = 1162
_LOGGER = logging.getLogger(__name__)


class EcoControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ecoControl Floor Heating using passive BLE data."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the configuration menu storage flow."""
        self._discovered_devices: dict[str, str] = {}
        self._discovered_names: dict[str, str] = {}
        self._discovered_device: tuple[str, str, str] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the device selection step with dynamic scanning feedback."""
        errors: dict[str, str] = {}

        # Check for active GATT connection capabilities
        if bluetooth.async_scanner_count(self.hass, connectable=True) == 0:
            # Fall back to checking for any active listener (including passive-only ESP32 proxies)
            if bluetooth.async_scanner_count(self.hass, connectable=False) == 0:
                _LOGGER.warning("[ecoControl] Setup blocked: No Bluetooth adapters or remote proxies found")
                return self.async_abort(reason="bluetooth_not_available")
            
            _LOGGER.warning(
                "[ecoControl] Running in passive proxy fallback mode: Found remote listening "
                "nodes, but no connectable local hardware adapters are available on the host"
            )              

        if user_input is not None:
            address = user_input.get("device")

            if address == "REFRESH_TRIGGER" or not address:
                self._discovered_device = None
                return await self.async_step_user(user_input=None)

            if address in self._discovered_devices:
                clean_name = self._discovered_names.get(address, "ecoControl Thermostat")
                
                await self.async_set_unique_id(address.replace(":", "").lower())
                self._abort_if_unique_id_configured()
                
                _LOGGER.info("[ecoControl] Successfully configured device: %s [%s]", clean_name, address)
                return self.async_create_entry(
                    title=clean_name, 
                    data={
                        "address": address, 
                        "default_name": clean_name,
                        # Disable scanning if we cannot take GATT connections
                        CONF_POLL_INTERVAL: 0 if bluetooth.async_scanner_count(self.hass, connectable=True) == 0 else DEFAULT_POLL_INTERVAL, 
                    }
                )

        if self._discovered_device:
            addr, clean_label, menu_label = self._discovered_device
            self._discovered_devices = {addr: menu_label}
            self._discovered_names = {addr: clean_label}
        else:
            try:
                discovered = bluetooth.async_discovered_service_info(self.hass)
            except Exception as ex:
                _LOGGER.error("[ecoControl] Global Bluetooth cache inspection crashed: %s", ex)
                return self.async_abort(reason="bluetooth_scan_failed")

            self._discovered_devices = {}
            self._discovered_names = {}

            for device in discovered:
                adv = device.advertisement
                if not adv or not adv.manufacturer_data:
                    continue

                if ECOCONTROL_MFR_ID in adv.manufacturer_data:
                    mfr_payload = adv.manufacturer_data[ECOCONTROL_MFR_ID]
                    parsed_name = parse_name_from_mfr(mfr_payload)
                    parsed_temp = parse_floor_temp_from_mfr(mfr_payload)
                    p_flag = mfr_payload[2] if len(mfr_payload) >= 3 else 0
                    is_heating_active = bool(p_flag & 0x80)

                    if parsed_name:
                        self._discovered_names[device.address] = parsed_name
                        self._discovered_devices[device.address] = (
                            f"{parsed_name} ({parsed_temp}°C) {'🔥 Active (Heating)' if is_heating_active else '❄️ Idle (Balanced)'} [{device.address}]"
                        )

        if not self._discovered_devices:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found_retry"}
            )

        menu_options = {
            **self._discovered_devices,
            "REFRESH_TRIGGER": "🔄 Refresh / Scan Again"
        }

        default_selection = next(iter(self._discovered_devices.keys())) if self._discovered_devices else "REFRESH_TRIGGER"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("device", default=default_selection): vol.In(menu_options),
            }),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle background discovery triggered by Home Assistant's central BLE engine."""
        address = discovery_info.address
        await self.async_set_unique_id(address.replace(":", "").lower())
        self._abort_if_unique_id_configured()

        mfr_payload = discovery_info.advertisement.manufacturer_data.get(ECOCONTROL_MFR_ID)
        parsed_name = parse_name_from_mfr(mfr_payload) if mfr_payload else "ecoControl Heater"
        parsed_temp = parse_floor_temp_from_mfr(mfr_payload) if mfr_payload else None
        
        display_label = (
            f"{parsed_name} ({parsed_temp}°C) [{address}]" 
            if parsed_temp else f"{parsed_name} [{address}]"
        )
        
        self._discovered_device = (address, parsed_name, display_label)
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Link the custom Options Flow menu handler to this integration."""
        return EcoControlOptionsFlowHandler(config_entry)


class EcoControlOptionsFlowHandler(config_entries.OptionsFlow):
    """Options Flow menu handler to update parameters live via the UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow using the base class pattern."""
        super().__init__()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the configuration options screen parameters."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_active = self.config_entry.options.get(
            CONF_POLL_INTERVAL, 
            self.config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_POLL_INTERVAL, 
                    default=int(current_active)
                ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            }),
        )
