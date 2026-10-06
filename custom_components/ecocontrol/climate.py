"""Climate platform for the read-only ecoControl floor heating integration."""

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import DOMAIN


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
        )
    ])


class EcoControlThermostat(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]],
    ClimateEntity,
):
    """Representation of an ecoControl Floor Heating Thermostat device card."""

    _attr_has_entity_name = True
    _attr_name = None  # None ensures it takes the device name natively in the UI
    
    # Core temperature scale declarations
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    
    # Force Read-Only State: Clear ClimateEntityFeature flags entirely to lock sliders
    _attr_supported_features = ClimateEntityFeature(0)
    
    # Declare static mode maps to lock operational workflows to heating
    _attr_hvac_modes = [HVACMode.HEAT]

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        address: str,
        fallback_name: str,
    ) -> None:
        """Initialize the thermostat container entity."""
        super().__init__(coordinator)
        self.address = address
        self.fallback_name = fallback_name
        
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
            
        # Inspect our live boolean relay metric to toggle the dashboard background theme
        if self.coordinator.data.get("is_heating"):
            return HVACAction.HEATING
            
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose auxiliary non-standard high-res metrics safely."""
        attributes = {}
        if self.coordinator.data:
            if air_temp := self.coordinator.data.get("air_temp"):
                attributes["room_air_temperature"] = air_temp
            if error_code := self.coordinator.data.get("error_code"):
                attributes["system_error_code"] = error_code
            if mode_code := self.coordinator.data.get("operation_mode"):
                attributes["operational_mode_code"] = mode_code
        return attributes

    @property
    def device_info(self) -> DeviceInfo:
        """Bind the entity to the central ecoControl device container."""
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
