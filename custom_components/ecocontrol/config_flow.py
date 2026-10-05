"""Config flow for ecoControl Floor Heating."""

import asyncio
import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from . import DOMAIN, DEFAULT_POLL_INTERVAL, CONF_POLL_INTERVAL_LABEL

# Target Manufacturer Broadcast Profile ID
ECOCONTROL_MFR_ID = 1162

_LOGGER = logging.getLogger(__name__)


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
    """Passively extracts and decodes the floor temperature out of index 0."""
    if not mfr_bytes or len(mfr_bytes) < 1:
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
        self._discovered_device: tuple[str, str] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the device selection step with dynamic scanning feedback."""
        errors: dict[str, str] = {}

        # 1. HARD BLOCK: Abort instantly if no active Bluetooth adapters exist on the host
        if bluetooth.async_scanner_count(self.hass) == 0:
            _LOGGER.warning("[ecoControl] Setup blocked: No active Bluetooth scanners/adapters found on host")
            return self.async_abort(reason="bluetooth_not_available")

        # 2. Check user input when form choices are submitted
        if user_input is not None:
            address = user_input.get("device")

            # Intercept manual menu refresh trigger requests
            if address == "REFRESH_TRIGGER" or not address:
                _LOGGER.debug("[ecoControl] Refresh triggered. Pausing 3s for BLE background cache to populate...")
                # Clear background discovery isolation context on manual rescan
                self._discovered_device = None
                await asyncio.sleep(3.0)
                return await self.async_step_user(user_input=None)

            # Process configuration save action for verified selections
            if address in self._discovered_devices:
                name = self._discovered_devices[address]
                await self.async_set_unique_id(address.replace(":", "").lower())
                self._abort_if_unique_id_configured()
                
                _LOGGER.info("[ecoControl] Successfully configured device: %s [%s]", name, address)
                return self.async_create_entry(
                    title=name, 
                    data={"address": address, "default_name": name}
                )

        # 3. CONTEXT MANAGEMENT: Preserve isolated state or query the global cache
        if self._discovered_device:
            # Preservation block for passive background discovery events
            addr, label = self._discovered_device
            self._discovered_devices = {addr: label}
            _LOGGER.debug("[ecoControl] Processing setup using passive background discovery context: %s", addr)
        else:
            # Run generic collection routine across the centralized manager cache
            try:
                discovered = bluetooth.async_discovered_service_info(self.hass)
            except Exception as ex:
                _LOGGER.error("[ecoControl] Global Bluetooth cache inspection crashed: %s", ex)
                return self.async_abort(reason="bluetooth_scan_failed")

            _LOGGER.debug("[ecoControl] Global BLE cache items inspected: %d", len(discovered))
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
                        self._discovered_devices[device.address] = (
                            f"{parsed_name} ({parsed_temp}°C) [{device.address}]"
                        )

            _LOGGER.debug("[ecoControl] Filtered matching ecoControl units discovered: %d", len(self._discovered_devices))

        # 4. CONDITIONAL EMPTY RETRY FORM: Shown if adapter is present but cache yields nothing
        if not self._discovered_devices:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found_retry"}
            )

        # 5. NORMAL DROPDOWN FORM: Displayed if devices are available in local stack
        menu_options = {
            **self._discovered_devices,
            "REFRESH_TRIGGER": "🔄 Refresh / Scan Again"
        }

        # Set default to first discovered device, or fallback to the refresh action
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
        _LOGGER.debug("[ecoControl] Passive background discovery intercepted unit broadcast at: %s", address)
        
        await self.async_set_unique_id(address.replace(":", "").lower())
        self._abort_if_unique_id_configured()

        mfr_payload = discovery_info.advertisement.manufacturer_data.get(ECOCONTROL_MFR_ID)
        parsed_name = parse_name_from_mfr(mfr_payload) if mfr_payload else "ecoControl Heater"
        parsed_temp = parse_floor_temp_from_mfr(mfr_payload) if mfr_payload else None
        
        display_label = (
            f"{parsed_name} ({parsed_temp}°C) [{address}]" 
            if parsed_temp else f"{parsed_name} [{address}]"
        )
        
        # Isolate discovery tracking context from runtime instance dictionary wipes
        self._discovered_device = (address, display_label)

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
