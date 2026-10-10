"""Climate platform for the native zero-config ecoControl floor heating integration."""

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import DOMAIN, _LOGGER, ThermostatState


@dataclass(frozen=True, kw_only=True)
class EcoControlClimateEntityDescription(ClimateEntityDescription):
    """Custom description class for mapping our static tracking limits."""

    min_temp: float
    max_temp: float
    target_temp_step: float
    temperature_unit: UnitOfTemperature


THERMOSTAT_DESCRIPTION = EcoControlClimateEntityDescription(
    key="thermostat",
    name=None,
    icon="mdi:thermometer",
    temperature_unit=UnitOfTemperature.CELSIUS, 
    min_temp=5.0,
    max_temp=35.0,
    target_temp_step=0.5,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ecoControl climate entity from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data["address"]
    fallback_name = entry.data["default_name"]

    async_add_entities([
        EcoControlThermostat(
            coordinator=coordinator,
            address=address,
            fallback_name=fallback_name,
            description=THERMOSTAT_DESCRIPTION,
        )
    ])


class EcoControlThermostat(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]],
    ClimateEntity,
):
    """Representation of an ecoControl Floor Heating Thermostat device card."""

    entity_description: EcoControlClimateEntityDescription
    _attr_has_entity_name = True
    
    _attr_supported_features = ClimateEntityFeature(0)
    _attr_hvac_modes = [HVACMode.HEAT]
    
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Reject background automation temperature changes gracefully."""
        _LOGGER.warning("Cannot set temperature: Thermostat %s is a read-only BLE integration.", self.name)

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        address: str,
        fallback_name: str,
        description: EcoControlClimateEntityDescription,
    ) -> None:
        """Initialize the thermostat container entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self.address = address
        self.fallback_name = fallback_name
        
        self._attr_temperature_unit = description.temperature_unit
        self._attr_target_temperature_step = description.target_temp_step
        self._attr_min_temp = description.min_temp
        self._attr_max_temp = description.max_temp

        
        mac_clean = address.replace(":", "").lower()
        self._attr_unique_id = f"ecocontrol_{mac_clean}_thermostat"

    @property
    def current_temperature(self) -> float | None:
        """Return the current floor temperature (primary tracking value)."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("floor_temp")

    @property
    def target_temperature(self) -> float | None:
        """Return the hardware setpoint target temperature."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("desired_temp")

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the active operational tracking mode context."""
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Dynamically return the running action state based on the relay flag."""
        if not self.coordinator.data:
            return HVACAction.OFF
            
        if self.coordinator.data.get("is_heating"):
            return HVACAction.HEATING
            
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Dynamically set custom state attributes for frontend dashboard cards."""
        attributes = {}
        
        if self.coordinator.data:
            air_temp = self.coordinator.data.get("air_temp")
            floor_temp = self.coordinator.data.get("floor_temp")
            mode_code = self.coordinator.data.get("operation_mode")
            error_code = self.coordinator.data.get("error_code")

            if air_temp is not None:
                attributes["room_air_temperature"] = float(air_temp)
                
            if floor_temp is not None:
                attributes["floor_probe_temperature"] = float(floor_temp)
                
            if mode_code is not None:
                attributes["operational_mode_code"] = mode_code

            air_display = f"{air_temp}°C" if air_temp is not None else "Unavailable"
            floor_display = f"{floor_temp}°C" if floor_temp is not None else "-"
            
            attributes["ambient_summary"] = f"Floor: {floor_display}  |  Air: {air_display}"

            if error_code and error_code != "-":
                attributes["hardware_fault_warning"] = f"⚠️ Code {error_code}"
            
        state_flag = getattr(self.coordinator, "thermostat_state", ThermostatState.GATT_DISABLED_BY_USER)
        if state_flag == ThermostatState.OK:
            attributes["connection_mode"] = "Active (includes GATT polling)"
        elif state_flag == ThermostatState.INITIAL_SETUP:
            attributes["connection_mode"] = "Active connection initializing..."
        elif state_flag == ThermostatState.STARTUP_GATT_FAILED:
            attributes["connection_mode"] = "Passive, GATT polling failed on setup"
        elif state_flag == ThermostatState.RUNTIME_FAILED:
            attributes["connection_mode"] = "Passive, GATT polling failed temporarily (waiting for packet to reactivate)"
        else:
            attributes["connection_mode"] = "Passive, GATT polling disabled by user"

        return attributes

    @property
    def device_info(self) -> DeviceInfo:
        """Bind entity to device container."""
        if self.coordinator.data:
            name = self.coordinator.data.get("name", self.fallback_name)
            hardware_version = self.coordinator.data.get("hw_version")
            software_version = self.coordinator.data.get("software_version")
            serial_number = self.coordinator.data.get("serial")
        else:
            name = self.fallback_name
            hardware_version = None
            software_version = None
            serial_number = None

        return DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            name=name,
            manufacturer="Taelek Oy",
            model="ecoControl Thermostat",
            serial_number=serial_number,
            hw_version=hardware_version,
            sw_version=software_version,
        )
