"""Config flow for ecoControl Floor Heating."""

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
        """Handle the device selection step when the user initiates configuration."""
        errors: dict[str, str] = {}

        # 1. Check if Bluetooth integration is loaded and actively scanning
        if bluetooth.async_scanner_count(self.hass) == 0:
            return self.async_abort(reason="bluetooth_not_available")

        if user_input is not None:
            address = user_input["device"]
            name = self._discovered_devices[address]
            await self.async_set_unique_id(address.replace(":", "").lower())
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=name, 
                data={"address": address, "default_name": name}
            )

        # 2. Safely grab discovered service info
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

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("device"): vol.In(self._discovered_devices)}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """🚀 Link the custom Options Flow menu handler to this integration."""
        return EcoControlOptionsFlowHandler(config_entry)


class EcoControlOptionsFlowHandler(config_entries.OptionsFlow):
    """🚀 Options Flow menu handler to update parameters live via the UI."""

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
