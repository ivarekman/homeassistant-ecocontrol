"""The ecoControl Floor Heating integration."""

import logging
from datetime import timedelta
import struct
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components import bluetooth
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

DOMAIN = "ecocontrol"
PLATFORMS = ["sensor"]
_LOGGER = logging.getLogger(__name__)

# Core GATT Characteristics
UUID_NAME = "2be32db1-5f6b-4cbd-8833-8d6dfb164900"
UUID_HW = "2be32db1-5f6b-4cbd-8813-8d6dfb164900"
UUID_SERIAL_SETPOINT = "2be32db1-5f6b-5bd8-8238-d6dfb1649000"
UUID_DETAILS = "2be32db1-5f6b-4cbd-8843-8d6dfb164900"

CONF_POLL_INTERVAL_LABEL = "Polling interval (seconds)"
DEFAULT_POLL_INTERVAL = 600 #10 minutes

def clean_bytes_to_string(raw_bytes: bytes) -> str:
    """Safely decodes raw hardware byte buffers into clean strings."""
    try:
        text = raw_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        text = "".join(chr(b) for b in raw_bytes if 32 <= b <= 126 or b >= 128).strip()
    text = "".join(c for c in text if c.isprintable()).strip()
    if text.endswith(" 2Z"):
        text = text[:-3].strip()
    return text


def unpack_uint16(payload: bytes, offset: int) -> int | None:
    """Extracts a standard single 16-bit little-endian integer from a struct tuple securely."""
    if len(payload) < (offset + 2):
        return None
    val_tuple = struct.unpack_from("<H", payload, offset)
    return int(val_tuple[0])


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ecoControl from a config entry created via UI."""
    hass.data.setdefault(DOMAIN, {})
    address = entry.data["address"]
    fallback_name = entry.data["default_name"]

    async def _async_update_data() -> dict[str, Any]:
        """Fetch the latest high-resolution metrics from the thermostat registers."""
        ble_device = bluetooth.async_ble_device_from_address(hass, address)
        if not ble_device:
            if coordinator.data:
                return coordinator.data
            raise UpdateFailed(f"Thermostat {address} not found in tracking histories")

        try:
            async with await establish_connection(
                client_class=BleakClient, device=ble_device, name=fallback_name, use_services_cache=True, max_attempts=3
            ) as client:
                raw_name = await client.read_gatt_char(UUID_NAME)
                raw_hw = await client.read_gatt_char(UUID_HW)
                raw_serial_block = await client.read_gatt_char(UUID_SERIAL_SETPOINT)
                raw_details = await client.read_gatt_char(UUID_DETAILS)

                name = clean_bytes_to_string(raw_name) or fallback_name
                
                serial = None
                if len(raw_serial_block) >= 15:
                    serial = clean_bytes_to_string(raw_serial_block[6:15])

                hw_version = "4.0T"
                software_version = None
                # Isolate the exact trailing ASCII byte position safely to avoid TypeErrors
                if len(raw_hw) >= 15 and raw_hw[14] > 0:
                    software_version = str(raw_hw[14])

                error_code = None
                air_temp = None
                floor_temp = None
                desired_temp = None

                if len(raw_details) >= 12:
                    error_code = unpack_uint16(raw_details, 0)
                    desired_raw = unpack_uint16(raw_details, 4)
                    air_raw = unpack_uint16(raw_details, 6)
                    floor_raw = unpack_uint16(raw_details, 8)

                    if air_raw is not None:
                        air_temp = round(air_raw / 10.0, 1)
                    if floor_raw is not None:
                        floor_temp = round(floor_raw / 10.0, 1)
                    if desired_raw is not None:
                        desired_temp = 5.0 if desired_raw == 80 else round(desired_raw / 10.0, 1)

                return {
                    "name": name,
                    "hw_version": hw_version,
                    "software_version": software_version,
                    "serial": serial,
                    "error_code": error_code,
                    "air_temp": air_temp,
                    "floor_temp": floor_temp,
                    "desired_temp": desired_temp,
                }

        except Exception as err:
            if coordinator.data:
                _LOGGER.debug("GATT fetch transaction dropped, using cached states: %s", err)
                return coordinator.data
            raise UpdateFailed(f"Bluetooth data handshake failed: {err}")

    # Read live user configurations from options flow dynamically
    scan_interval = entry.options.get(CONF_POLL_INTERVAL_LABEL, entry.data.get(CONF_POLL_INTERVAL_LABEL, DEFAULT_POLL_INTERVAL))

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"ecocontrol_{address}",
        update_interval=timedelta(seconds=scan_interval),
        update_method=_async_update_data,
    )

    async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
        # Retrieve the newly saved seconds value out of your options schema entry
        new_interval = entry.options.get(CONF_POLL_INTERVAL_LABEL, DEFAULT_POLL_INTERVAL)
        _LOGGER.info("Updating ecoControl polling loop interval dynamically to: %s seconds", new_interval)
        
        coordinator.update_interval = timedelta(seconds=int(new_interval))
        
        await coordinator.async_request_refresh()

    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
