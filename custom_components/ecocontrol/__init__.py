"""The ecoControl Floor Heating integration."""

import asyncio
from datetime import timedelta
from enum import StrEnum
import logging
import struct
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components import bluetooth
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

# Global configuration handles imported by config_flow.py
DOMAIN = "ecocontrol"
PLATFORMS = ["sensor", "climate"]
_LOGGER = logging.getLogger(__name__)

# Core GATT Characteristics
UUID_NAME = "2be32db1-5f6b-4cbd-8833-8d6dfb164900"
UUID_HW = "2be32db1-5f6b-4cbd-8813-8d6dfb164900"
UUID_SERIAL_SETPOINT = "2be32db1-5f6b-5bd8-8238-d6dfb1649000"
UUID_DETAILS = "2be32db1-5f6b-4cbd-8843-8d6dfb164900"
UUID_STAT_8863 = "2be32db1-5f6b-4cbd-8863-8d6dfb164900"

CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 600   # 10 minutes

ECOCONTROL_MFR_ID = 1162

class ThermostatState(StrEnum):
    """Lifecycle and connection states for the ecoControl thermostat."""
    INITIAL_SETUP = "initial_setup"
    OK = "ok"
    STARTUP_GATT_FAILED = "startup_gatt_failed"
    RUNTIME_FAILED = "runtime_failed"
    GATT_DISABLED_BY_USER = "gatt_disabled_by_user"
    
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
    """Extracts a standard single 16-bit little-endian integer securely."""
    if len(payload) < (offset + 2):
        return None
    val_tuple = struct.unpack_from("<H", payload, offset)
    return int(val_tuple[0])


def unpack_uint32(payload: bytes, offset: int) -> int | None:
    """Extracts a standard single 32-bit little-endian integer securely."""
    if len(payload) < (offset + 4):
        return None
    val_tuple = struct.unpack_from("<I", payload, offset)
    return int(val_tuple[0])


def parse_name_from_mfr(mfr_bytes: bytes) -> str | None:
    """Passively extracts and decodes the string name out of index 8."""
    if len(mfr_bytes) < 9:
        return None
    try:
        return clean_bytes_to_string(mfr_bytes[8:])
    except Exception:
        return None


def parse_floor_temp_from_mfr(mfr_bytes: bytes) -> float | None:
    """Passively extracts and decodes the floor temperature out of index 0 safely."""
    if not mfr_bytes or len(mfr_bytes) < 1:
        return None
    try:
        raw_floor = int(mfr_bytes[0])
        return round(float(raw_floor) / 10.0, 1)
    except Exception:
        return None

def parse_discovery_labels(mfr_bytes: bytes, address: str) -> tuple[str, str]:
    """Extract payload into (short_name, display_name) tuple."""
    parsed_name = parse_name_from_mfr(mfr_bytes) or "ecoControl Thermostat"
    parsed_temp = parse_floor_temp_from_mfr(mfr_bytes)
    p_flag = mfr_bytes[2] if mfr_bytes and len(mfr_bytes) >= 3 else 0
    is_heating_active = bool(p_flag & 0x80)

    status = "🔥 Active (Heating)" if is_heating_active else "❄️ Idle (Balanced)"
    
    if parsed_temp is not None:
        display_name = f"{parsed_name} ({parsed_temp}°C) {status} [{address}]"
    else:
        display_name = f"{parsed_name} [{address}]"
        
    return parsed_name, display_name

def parse_thermostat_payload(
    raw_name: bytes,
    raw_hw: bytes,
    raw_serial_block: bytes,
    raw_details: bytes,
    raw_8863: bytes,
    fallback_name: str,
    raw_passive_flags: int = 0
) -> dict[str, Any]:
    """Parses raw GATT binary arrays into a clean state dictionary."""
    name = clean_bytes_to_string(raw_name) or fallback_name
    
    serial = None
    if len(raw_serial_block) >= 15:
        serial = clean_bytes_to_string(raw_serial_block[6:15])

    hw_version = clean_bytes_to_string(raw_hw[0:14]) or None if len(raw_hw) >= 14 else None
    software_version = str(raw_hw[14]) if len(raw_hw) >= 15 and raw_hw[14] > 0 else None
    
    error_code = None
    operation_mode = None
    desired_temp = None
    air_temp = None
    floor_temp = None
    
    is_heating = bool(raw_passive_flags & 0x80)

    if len(raw_details) >= 12:
        error_code = unpack_uint16(raw_details, 0)
        operation_mode = unpack_uint16(raw_details, 2)
        desired_raw = unpack_uint16(raw_details, 4)
        air_raw = unpack_uint16(raw_details, 6)
        floor_raw = unpack_uint16(raw_details, 8)

        if air_raw is not None:
            air_temp = round(air_raw / 10.0, 1)
        if floor_raw is not None:
            floor_temp = round(floor_raw / 10.0, 1)
        if desired_raw is not None:
            desired_temp = round(desired_raw / 10.0, 1)

    relay_cycles = unpack_uint32(raw_8863, 0) if len(raw_8863) >= 4 else None
    operating_hours = unpack_uint32(raw_8863, 4) if len(raw_8863) >= 8 else None
    heating_hours_raw = unpack_uint32(raw_8863, 8) if len(raw_8863) >= 12 else None
    heating_hours = round(heating_hours_raw / 100.0, 2) if heating_hours_raw is not None else None

    return {
        "name": name,
        "hw_version": hw_version,
        "software_version": software_version,
        "serial": serial,
        "error_code": error_code,
        "operation_mode": operation_mode,
        "air_temp": air_temp,
        "floor_temp": floor_temp,
        "desired_temp": desired_temp,
        "is_heating": is_heating,
        "relay_cycles": relay_cycles,
        "operating_hours": operating_hours,
        "heating_hours": heating_hours,
    }
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ecoControl from a config entry created via UI."""
    hass.data.setdefault(DOMAIN, {})
    
    address = entry.data["address"]
    fallback_name = entry.data["default_name"]

    # Verify device presence on startup
    service_info = bluetooth.async_last_service_info(hass, address)
    if not service_info:
        _LOGGER.debug("Thermostat %s [%s] not found in BLE cache. Delaying setup.", fallback_name, address)
        raise ConfigEntryNotReady(f"Thermostat {address} has not been seen by Bluetooth adapters yet.")

    # Initialize full fallback dictionary tracking state data
    initial_data = {
        "name": fallback_name,
        "hw_version": None,
        "software_version": None,
        "serial": None,
        "error_code": None,
        "operation_mode": None,
        "air_temp": None,
        "floor_temp": None,
        "desired_temp": None,
        "is_heating": False,
        "relay_cycles": None,
        "operating_hours": None,
        "heating_hours": None,
    }

    async def _async_update_data() -> dict[str, Any]:
        """Fetch the data over GATT connection."""

        if coordinator.update_interval is None or coordinator.thermostat_state in (ThermostatState.GATT_DISABLED_BY_USER, ThermostatState.STARTUP_GATT_FAILED, ThermostatState.RUNTIME_FAILED):
            _LOGGER.debug("Active polling loop suspended or sleeping (State: %s). Relying on passive scan metrics for %s", coordinator.thermostat_state, address)
            return coordinator.data if coordinator.data else initial_data
              
        service_info = bluetooth.async_last_service_info(hass, address)
        if not service_info or not service_info.device:
            if coordinator.data:
                return coordinator.data
            _LOGGER.debug("Thermostat %s not yet discovered on startup, falling back to initial structure", address)
            return initial_data

        ble_device = service_info.device

        # Extract flags from current advertisement if available to sync target properties
        current_adv = bluetooth.async_last_service_info(hass, address)
        p_flag = 0
        if current_adv and current_adv.advertisement and ECOCONTROL_MFR_ID in current_adv.advertisement.manufacturer_data:
            mfr_data = current_adv.advertisement.manufacturer_data[ECOCONTROL_MFR_ID]
            p_flag = mfr_data[2] if mfr_data and len(mfr_data) >= 3 else 0

        try:
            async with await establish_connection(
                client_class=BleakClient,
                device=ble_device,
                name=fallback_name,
                use_services_cache=True,
                max_attempts=2
            ) as client:
                raw_name = await client.read_gatt_char(UUID_NAME)
                raw_hw = await client.read_gatt_char(UUID_HW)
                raw_serial_block = await client.read_gatt_char(UUID_SERIAL_SETPOINT)
                raw_details = await client.read_gatt_char(UUID_DETAILS)
                
                raw_8863 = b""
                try:
                    raw_8863 = await client.read_gatt_char(UUID_STAT_8863)
                except Exception as stat_err:
                    _LOGGER.debug("Statistics handle 8863 not available or failed: %s", stat_err)

                parsed = parse_thermostat_payload(
                    raw_name, raw_hw, raw_serial_block, raw_details, raw_8863, fallback_name, p_flag
                )
                coordinator.thermostat_state = ThermostatState.OK
                return parsed
                    
        except Exception as err:
            if coordinator.thermostat_state == ThermostatState.INITIAL_SETUP:
                coordinator.thermostat_state = ThermostatState.STARTUP_GATT_FAILED
                coordinator.update_interval = None
                _LOGGER.info(
                    "Initial active connection failed for thermostat %s [%s] (%s). "
                    "Shifting integration permanently to pure passive background scanning mode.", 
                    fallback_name, address, err
                )
                return coordinator.data if coordinator.data else initial_data
                
            # Runtime connection fallback: Disable GATT tries until an advertisement packet arrives
            _LOGGER.info(
                "Thermostat %s [%s] connection dropped. Suspending active polling loop until next advertisement.", 
                fallback_name, address
            )
            coordinator.thermostat_state = ThermostatState.RUNTIME_FAILED
            coordinator.update_interval = None
            return coordinator.data if coordinator.data else initial_data

    # Read live user scan updates
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))

    # Check if Home Assistant has ANY adapter or proxy capable of making active connections to this device
    if poll_interval > 0 and service_info and not service_info.connectable:
        _LOGGER.info(
            "Thermostat %s [%s] is only reachable via passive-only proxies or adapters. "
            "Forcing pure passive background scanning mode to prevent connection retries.",
            fallback_name, address
        )
        poll_interval = 0
        
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"ecocontrol_{address}",
        update_interval=timedelta(seconds=poll_interval) if poll_interval > 0 else None,
        update_method=_async_update_data,
    )
    # Custom attribute directly to the coordinator to track permanent active-failure status
    if poll_interval > 0:
        coordinator.thermostat_state = ThermostatState.INITIAL_SETUP
    else:
        coordinator.thermostat_state = ThermostatState.GATT_DISABLED_BY_USER
    
    coordinator.async_set_updated_data(initial_data)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # Callback parsing handle for over-the-air passive advertisements
    @callback
    def _async_handle_bluetooth_advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Process incoming broadcast payloads passively when configured."""
        adv_data = service_info.advertisement
        if ECOCONTROL_MFR_ID not in adv_data.manufacturer_data:
            return

        mfr_bytes = adv_data.manufacturer_data[ECOCONTROL_MFR_ID]
        p_name = parse_name_from_mfr(mfr_bytes)
        p_floor = parse_floor_temp_from_mfr(mfr_bytes)
        p_flag = mfr_bytes[2] if mfr_bytes and len(mfr_bytes) >= 3 else 0
        is_heating = bool(p_flag & 0x80)

        # Merge extracted passive metrics update onto existing data context dict without wiping GATT metrics
        updated_data = {**(coordinator.data or initial_data)}
        if p_name:
            updated_data["name"] = p_name
        if p_floor is not None:
            updated_data["floor_temp"] = p_floor
        updated_data["is_heating"] = is_heating

        coordinator.async_set_updated_data(updated_data)
           
        if coordinator.thermostat_state == ThermostatState.INITIAL_SETUP:
            #Prevent race conditions on startup
            return

        configured_interval = int(entry.options.get(
            CONF_POLL_INTERVAL, 
            entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        ))

        # If a connection previously failed AND the user has not disabled active polling (interval > 0),
        # an advertisement packet proves the device is awake. Clear the flag and resume GATT loops.
        if configured_interval > 0 and coordinator.thermostat_state in (ThermostatState.STARTUP_GATT_FAILED, ThermostatState.RUNTIME_FAILED):
            _LOGGER.info("Device %s spotted online via broadcast. Testing active GATT link recovery...", address)
            coordinator.update_interval = timedelta(seconds=configured_interval)
            
            # Fire a background execution pass. If it succeeds, the update logic sets the state to OK.
            # If it fails, the exception block cleanly wipes the interval again and preserves the failure state.
            coordinator.thermostat_state = ThermostatState.INITIAL_SETUP
            coordinator.hass.async_create_task(coordinator.async_refresh())

    # Register passive advertisement listener filter matched specifically to this device's MAC address
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_handle_bluetooth_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=address),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    async def _async_startup_poll() -> None:
        """Execute the initial integration configuration connection check."""
        try:
            await coordinator.async_refresh()
            # Transition to OK only if the active GATT fetch completed with zero exceptions
            if coordinator.thermostat_state == ThermostatState.INITIAL_SETUP:
                coordinator.thermostat_state = ThermostatState.OK
        except Exception:
            # Exceptions are already safely handled inside _async_update_data
            pass
            
    # Try setting up data on startup. If active connection fails, it falls back gracefully
    if poll_interval > 0:
        entry.async_create_background_task(
            hass, 
            _async_startup_poll(), 
            "ecocontrol-initial-active-poll"
        )
    else:
        coordinator.thermostat_state = ThermostatState.GATT_DISABLED_BY_USER
        # Check background cache for immediate startup metrics if active scanning is disabled
        last_adv = bluetooth.async_last_service_info(hass, address)
        if last_adv and last_adv.advertisement and ECOCONTROL_MFR_ID in last_adv.advertisement.manufacturer_data:
            _async_handle_bluetooth_advertisement(last_adv, bluetooth.BluetoothChange.ADVERTISEMENT)
        else:
            coordinator.async_set_updated_data(initial_data)
        
    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle live user parameter modifications inside the Options Flow UI on-the-fly."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

    # Allow a manual user update via the UI to reset and re-evaluate active connection health
    if poll_interval > 0:
        coordinator.thermostat_state = ThermostatState.INITIAL_SETUP
        coordinator.update_interval = timedelta(seconds=poll_interval)
        _LOGGER.info("Resetting polling schedule loop to %s seconds for %s", poll_interval, entry.title)
    else:
        coordinator.thermostat_state = ThermostatState.GATT_DISABLED_BY_USER
        coordinator.update_interval = None
        _LOGGER.info("Active cyclical GATT polling disabled for %s", entry.title)

    await coordinator.async_refresh()
    
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
