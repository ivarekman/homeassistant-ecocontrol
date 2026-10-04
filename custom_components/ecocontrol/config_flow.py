"""Config flow for ecoControl Floor Heating."""

import asyncio
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from . import DOMAIN, DEFAULT_POLL_INTERVAL, CONF_POLL_INTERVAL_LABEL

# Target Manufacturer Broadcast Profile ID
ECOCONTROL_MFR_ID = 1162

def parse_name_from_mfr(mfr_bytes: bytes) -> str | None:
    """Passively extracts and decodes the string given name out of index 8."""
    if len(mfr_bytes) < 9:
        return None

    try:
        name_bytes = mfr_bytes[8:]
        decoded_name = name_bytes.decode("utf-8", errors="ignore").strip()
        decoded_name = "".join(c for c in decoded_name if c.isprintable()).strip()
        if decoded_name.endswith(" 2Z"):
            decoded_name = decoded_name[:-3].strip()
        return decoded_name if len(decoded_name) > 0 else None
    except Exception:
        return None

def parse_floor_temp_from_mfr(mfr_bytes: bytes) -> float | None:
    """🚀 Passively extracts and decodes the floor temperature out of index 0."""
    if len(mfr_bytes) < 1:
        return None

    try:
        # Index 0 stores the raw floor temperature directly scaled by 10
        raw_floor = int(mfr_bytes[0])
        return round(float(raw_floor) / 10.0, 1)
    except Exception:
        return None

class EcoControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ecoControl Floor Heating using passive BLE data."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the configuration menu storage flow."""
        self._discovered_devices: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the device selection step with dynamic scanning feedback."""
        errors: dict[str, str] = {}

        # 1. Hardware State Verification (Ensure Bluetooth engine is running adapters)
        if bluetooth.async_scanner_count(self.hass) == 0:
            return self.async_abort(reason="bluetooth_not_available")

        # 2. Processing user form submissions
        if user_input is not None:
            # Checks if the user checked the "Refresh" box or submitted on an empty screen ("device" key doesn't exist)
            if user_input.get("refresh") or "device" not in user_input:
                await asyncio.sleep(3.0)  # Pauses to allow background BLE engine to populate cache
                return await self.async_step_user(user_input=None)

            # Otherwise, process the actual selected device configuration entry
            address = user_input.get("device")
            if address and address in self._discovered_devices:
                name = self._discovered_devices[address]
                await self.async_set_unique_id(address.replace(":", "").lower())
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=name, 
                    data={"address": address, "default_name": name}
                )

        # 3. Pull cached data from Home Assistant's background scanner engine
        try:
            discovered = bluetooth.async_discovered_service_info(self.hass)
        except Exception:
            return self.async_abort(reason="bluetooth_scan_failed")

        self._discovered_devices = {}
        for device in discovered:
            adv = device.advertisement
            if not adv or not adv.manufacturer_data:
                continue

            if ECOCONTROL_MFR_ID in adv.manufacturer_data:
                mfr_payload = adv.manufacturer_data[ECOCONTROL_MFR_ID]
                parsed_name = parse_name_from_mfr(mfr_payload)
                parsed_temp = parse_floor_temp_from_mfr(mfr_payload)

                if parsed_name:
                    self._discovered_devices[device.address] = f"{parsed_name} ({parsed_temp}°C) [{device.address}]"

        # 4. Shown if adapter is  found but cache is empty.
        # This renders as a clean window with a "Submit" button to retry (no checkbox).
        if not self._discovered_devices:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found_retry"}
            )

        # 5. Show normal selection dropdown list if devices are found
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("device"): vol.In(self._discovered_devices),
                # Show Refresh function under the list dropdown
                vol.Optional("refresh", default=False): bool
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
        
        display_label = f"{parsed_name} ({parsed_temp}°C) [{address}]" if parsed_temp else f"{parsed_name} [{address}]"
        self._discovered_devices[address] = display_label

        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Link custom Options Flow menu handler to this integration."""
        return EcoControlOptionsFlowHandler(config_entry)


class EcoControlOptionsFlowHandler(config_entries.OptionsFlow):
    """Options Flow menu handler to update parameters live via the UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow using the base class pattern."""
        super().__init__()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the configuration options screen."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_POLL_INTERVAL_LABEL, 
            self.config_entry.data.get(CONF_POLL_INTERVAL_LABEL, DEFAULT_POLL_INTERVAL)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_POLL_INTERVAL_LABEL, 
                    default=int(current_interval)
                ): int
            }),
        )
