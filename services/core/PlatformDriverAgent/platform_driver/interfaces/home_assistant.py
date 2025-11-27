# -*- coding: utf-8 -*- {{{
# ===----------------------------------------------------------------------===
#
#                 Component of Eclipse VOLTTRON
#
# ===----------------------------------------------------------------------===
#
# Copyright 2023 Battelle Memorial Institute
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# ===----------------------------------------------------------------------===
# }}}


import logging
from typing import Dict, Any, Optional, List
from enum import IntEnum

import requests
from platform_driver.interfaces import BaseInterface, BaseRegister, BasicRevert

_log = logging.getLogger(__name__)


# =============================================================================
# Type Mappings and Constants
# =============================================================================

TYPE_MAPPING = {
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "bool": bool,
    "boolean": bool
}


class ClimateMode(IntEnum):
    """Enumeration for thermostat/climate device modes."""
    OFF = 0
    HEAT = 2
    COOL = 3
    AUTO = 4


class DeviceState(IntEnum):
    """Enumeration for binary device states (on/off)."""
    OFF = 0
    ON = 1


class LockState(IntEnum):
    """Enumeration for lock states."""
    UNLOCKED = 0
    LOCKED = 1
    UNLOCKING = 2
    LOCKING = 3
    JAMMED = 4
    OPENING = 5
    OPEN = 6


# Valid brightness range for lights
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 255


# =============================================================================
# Register Definition
# =============================================================================

class HomeAssistantRegister(BaseRegister):
    """
    Register representing a single point/attribute of a Home Assistant entity.
    
    Attributes:
        entity_id: Home Assistant entity identifier (e.g., 'light.bedroom')
        entity_point: Specific attribute to read/write (e.g., 'state', 'brightness')
        reg_type: Python type for value conversion
        attributes: Additional metadata about the register
    """
    
    def __init__(self, read_only: bool, point_name: str, units: str, 
                 reg_type: type, attributes: Dict, entity_id: str, 
                 entity_point: str, default_value=None, description: str = ''):
        super().__init__("byte", read_only, point_name, units, description=description)
        self.reg_type = reg_type
        self.attributes = attributes
        self.entity_id = entity_id
        self.entity_point = entity_point
        self.value = None


# =============================================================================
# Home Assistant API Client
# =============================================================================

class HomeAssistantClient:
    """
    Client for interacting with the Home Assistant REST API.
    
    Encapsulates all HTTP communication with Home Assistant, providing
    a clean interface for entity state retrieval and service calls.
    """
    
    def __init__(self, ip_address: str, port: int, access_token: str):
        """
        Initialize the Home Assistant API client.
        
        Args:
            ip_address: Home Assistant server IP address
            port: Home Assistant server port
            access_token: Long-lived access token for authentication
        """
        self.base_url = f"http://{ip_address}:{port}/api"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
    
    def get_entity_state(self, entity_id: str) -> Dict[str, Any]:
        """
        Retrieve the current state and attributes of an entity.
        
        Args:
            entity_id: The entity identifier (e.g., 'light.bedroom')
            
        Returns:
            Dictionary containing state and attributes
            
        Raises:
            Exception: If the API request fails
        """
        url = f"{self.base_url}/states/{entity_id}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            error_msg = (f"Failed to get state for {entity_id}. "
                        f"Status: {response.status_code}, Response: {response.text}")
            _log.error(error_msg)
            raise Exception(error_msg)
    
    def call_service(self, domain: str, service: str, data: Dict[str, Any], 
                    operation_description: str) -> None:
        """
        Call a Home Assistant service.
        
        Args:
            domain: Service domain (e.g., 'light', 'climate')
            service: Service name (e.g., 'turn_on', 'set_temperature')
            data: Service data payload
            operation_description: Human-readable description for logging
            
        Raises:
            Exception: If the service call fails
        """
        url = f"{self.base_url}/services/{domain}/{service}"
        
        try:
            response = requests.post(url, headers=self.headers, json=data)
            if response.status_code == 200:
                _log.info(f"Success: {operation_description}")
            else:
                error_msg = (f"Failed to {operation_description}. "
                           f"Status: {response.status_code}, Response: {response.text}")
                _log.error(error_msg)
                raise Exception(error_msg)
        except requests.RequestException as e:
            error_msg = f"Error during {operation_description}: {e}"
            _log.error(error_msg)
            raise Exception(error_msg)


# =============================================================================
# Device Controllers
# =============================================================================

class DeviceController:
    """Base class for device-specific control logic."""
    
    def __init__(self, client: HomeAssistantClient):
        self.client = client
    
    def supports_entity(self, entity_id: str) -> bool:
        """Check if this controller supports the given entity type."""
        raise NotImplementedError
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """Read a specific point from entity data."""
        raise NotImplementedError
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """Write a value to a specific point."""
        raise NotImplementedError


class LightController(DeviceController):
    """Controller for Home Assistant light entities."""
    
    def supports_entity(self, entity_id: str) -> bool:
        return entity_id.startswith("light.")
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """Read light state or brightness."""
        if entity_point == "state":
            state = entity_data.get("state", "off")
            return DeviceState.ON if state == "on" else DeviceState.OFF
        else:
            return entity_data.get("attributes", {}).get(entity_point, 0)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """Control light state or brightness."""
        if entity_point == "state":
            self._set_light_state(entity_id, value)
        elif entity_point == "brightness":
            self._set_brightness(entity_id, value)
        else:
            raise ValueError(f"Unsupported point '{entity_point}' for light {entity_id}")
    
    def _set_light_state(self, entity_id: str, value: int) -> None:
        """Turn light on or off."""
        if not isinstance(value, int) or value not in [DeviceState.OFF, DeviceState.ON]:
            raise ValueError(f"Light state must be {DeviceState.OFF} or {DeviceState.ON}")
        
        service = "turn_on" if value == DeviceState.ON else "turn_off"
        data = {"entity_id": entity_id}
        self.client.call_service("light", service, data, 
                                f"{service.replace('_', ' ')} {entity_id}")
    
    def _set_brightness(self, entity_id: str, value: int) -> None:
        """Set light brightness (0-255)."""
        if not isinstance(value, int) or not (BRIGHTNESS_MIN <= value <= BRIGHTNESS_MAX):
            raise ValueError(f"Brightness must be between {BRIGHTNESS_MIN} and {BRIGHTNESS_MAX}")
        
        data = {"entity_id": entity_id, "brightness": value}
        self.client.call_service("light", "turn_on", data, 
                                f"set brightness of {entity_id} to {value}")


class ClimateController(DeviceController):
    """Controller for Home Assistant climate/thermostat entities."""
    
    # Map numeric modes to Home Assistant mode strings
    MODE_MAP = {
        ClimateMode.OFF: "off",
        ClimateMode.HEAT: "heat",
        ClimateMode.COOL: "cool",
        ClimateMode.AUTO: "auto"
    }
    
    # Reverse mapping for reading states
    STATE_MAP = {v: k for k, v in MODE_MAP.items()}
    
    def supports_entity(self, entity_id: str) -> bool:
        return entity_id.startswith("climate.")
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """Read climate state or attributes."""
        if entity_point == "state":
            state = entity_data.get("state", "off")
            if state in self.STATE_MAP:
                return self.STATE_MAP[state]
            else:
                raise ValueError(f"Unsupported climate state: {state}")
        else:
            return entity_data.get("attributes", {}).get(entity_point, 0)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """Control climate mode or temperature."""
        if entity_point == "state":
            self._set_mode(entity_id, value)
        elif entity_point == "temperature":
            self._set_temperature(entity_id, value, units)
        else:
            raise ValueError(f"Unsupported point '{entity_point}' for climate {entity_id}")
    
    def _set_mode(self, entity_id: str, mode_value: int) -> None:
        """Set thermostat mode."""
        if mode_value not in self.MODE_MAP:
            valid_modes = list(self.MODE_MAP.keys())
            raise ValueError(f"Climate mode must be one of: {valid_modes}")
        
        mode = self.MODE_MAP[mode_value]
        data = {"entity_id": entity_id, "hvac_mode": mode}
        self.client.call_service("climate", "set_hvac_mode", data,
                                f"set mode of {entity_id} to {mode}")
    
    def _set_temperature(self, entity_id: str, temperature: float, 
                        units: Optional[str] = None) -> None:
        """Set thermostat temperature with optional unit conversion."""
        # Convert Fahrenheit to Celsius if needed
        if units == "C":
            temperature = round((temperature - 32) * 5/9, 1)
            _log.info(f"Converted temperature to {temperature}°C")
        
        data = {"entity_id": entity_id, "temperature": temperature}
        self.client.call_service("climate", "set_temperature", data,
                                f"set temperature of {entity_id} to {temperature}")


class InputBooleanController(DeviceController):
    """Controller for Home Assistant input_boolean entities."""
    
    def supports_entity(self, entity_id: str) -> bool:
        return entity_id.startswith("input_boolean.")
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """Read input boolean state."""
        if entity_point == "state":
            state = entity_data.get("state", "off")
            return DeviceState.ON if state == "on" else DeviceState.OFF
        else:
            return entity_data.get("attributes", {}).get(entity_point, 0)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """Set input boolean state."""
        if entity_point != "state":
            _log.info(f"Only 'state' is writable for input_boolean entities")
            raise ValueError(f"Only 'state' is writable for {entity_id}")
        
        if not isinstance(value, int) or value not in [DeviceState.OFF, DeviceState.ON]:
            raise ValueError(f"Input boolean state must be {DeviceState.OFF} or {DeviceState.ON}")
        
        service = "turn_on" if value == DeviceState.ON else "turn_off"
        data = {"entity_id": entity_id}
        self.client.call_service("input_boolean", service, data,
                                f"{service.replace('_', ' ')} {entity_id}")


class GenericController(DeviceController):
    """Controller for generic read-only entities."""
    
    def supports_entity(self, entity_id: str) -> bool:
        # Generic controller supports all entities not handled by specific controllers
        return True
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """Read generic entity state or attribute."""
        if entity_point == "state":
            return entity_data.get("state", None)
        else:
            return entity_data.get("attributes", {}).get(entity_point, 0)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """Generic entities are typically read-only."""
        raise NotImplementedError(f"Write not supported for generic entity {entity_id}")


class LockController(DeviceController):
    """Controller for Home Assistant lock entities."""
    
    # Map Home Assistant lock states to numeric values
    STATE_MAP = {
        "unlocked": LockState.UNLOCKED,
        "locked": LockState.LOCKED,
        "unlocking": LockState.UNLOCKING,
        "locking": LockState.LOCKING,
        "jammed": LockState.JAMMED,
        "opening": LockState.OPENING,
        "open": LockState.OPEN
    }
    
    def supports_entity(self, entity_id: str) -> bool:
        return entity_id.startswith("lock.")
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """Read lock state or attributes."""
        if entity_point == "state":
            state = entity_data.get("state", "unlocked")
            if state in self.STATE_MAP:
                return self.STATE_MAP[state]
            else:
                _log.warning(f"Unknown lock state '{state}' for {entity_id}, defaulting to unlocked")
                return LockState.UNLOCKED
        else:
            # Read other attributes (changed_by, code_format, etc.)
            return entity_data.get("attributes", {}).get(entity_point, None)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """Control lock state."""
        if entity_point != "state":
            raise ValueError(f"Only 'state' is writable for lock {entity_id}")
        
        if not isinstance(value, int):
            raise ValueError(f"Lock state must be an integer value")
        
        # Handle different lock operations based on the target state
        if value == LockState.LOCKED:
            self._lock(entity_id)
        elif value == LockState.UNLOCKED:
            self._unlock(entity_id)
        elif value == LockState.OPEN:
            self._open(entity_id)
        else:
            raise ValueError(
                f"Lock state must be {LockState.LOCKED} (lock), "
                f"{LockState.UNLOCKED} (unlock), or {LockState.OPEN} (open). "
                f"States LOCKING, UNLOCKING, JAMMED, and OPENING are read-only status indicators."
            )
    
    def _lock(self, entity_id: str) -> None:
        """Lock the lock."""
        data = {"entity_id": entity_id}
        self.client.call_service("lock", "lock", data, f"lock {entity_id}")
    
    def _unlock(self, entity_id: str) -> None:
        """Unlock the lock."""
        data = {"entity_id": entity_id}
        self.client.call_service("lock", "unlock", data, f"unlock {entity_id}")
    
    def _open(self, entity_id: str) -> None:
        """Open (unlatch) the lock."""
        data = {"entity_id": entity_id}
        self.client.call_service("lock", "open", data, f"open {entity_id}")


class NotifyController(DeviceController):
    """
    Controller for Home Assistant notify entities.
    
    Notify entities are stateless and are used to send messages to devices
    or services (SMS, email, push notifications, etc.). The state represents
    the timestamp of the last message sent.
    """
    
    def supports_entity(self, entity_id: str) -> bool:
        return entity_id.startswith("notify.")
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """
        Read notify entity state (timestamp of last message).
        
        Note: Notify entities are essentially stateless from Home Assistant's
        perspective. The state is a timestamp of the last sent message.
        """
        if entity_point == "state":
            # Return the timestamp of the last message sent
            return entity_data.get("state", None)
        else:
            # Read other attributes if any
            return entity_data.get("attributes", {}).get(entity_point, None)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """
        Send a notification message.
        
        For notify entities, 'writing' means sending a message. The value
        should be the message text. An optional title can be included in
        the units parameter as a JSON string.
        
        Args:
            entity_id: The notify entity (e.g., 'notify.mobile_app')
            entity_point: Should be 'message' for sending notifications
            value: The message text to send
            units: Optional JSON string with additional parameters like title
                   Example: '{"title": "Alert"}'
        """
        if entity_point != "message":
            raise ValueError(f"For notify entities, only 'message' point is writable. Got: {entity_point}")
        
        if not isinstance(value, str):
            raise ValueError(f"Message must be a string")
        
        self._send_message(entity_id, value, units)
    
    def _send_message(self, entity_id: str, message: str, 
                     params: Optional[str] = None) -> None:
        """
        Send a notification message.
        
        Args:
            entity_id: The notify entity ID
            message: The message text to send
            params: Optional JSON string containing additional parameters
                   like title, target, data, etc.
        """
        # Extract the service name from entity_id (e.g., 'notify.mobile_app' -> 'mobile_app')
        service_name = entity_id.replace("notify.", "")
        
        # Build the service data payload
        data = {"message": message}
        
        # Parse additional parameters if provided
        if params:
            try:
                import json
                additional_params = json.loads(params)
                
                # Add title if provided
                if "title" in additional_params:
                    data["title"] = additional_params["title"]
                
                # Add target if provided (for targeting specific devices)
                if "target" in additional_params:
                    data["target"] = additional_params["target"]
                
                # Add data if provided (for platform-specific options)
                if "data" in additional_params:
                    data["data"] = additional_params["data"]
                    
            except json.JSONDecodeError:
                _log.warning(f"Could not parse params as JSON: {params}")
        
        # Call the notify service
        self.client.call_service("notify", service_name, data, 
                                f"send notification via {entity_id}")


class TimeController(DeviceController):
    """
    Controller for Home Assistant time input entities.
    
    Time entities allow setting a time value (hours and minutes).
    The value is stored as a string in HH:MM:SS format.
    """
    
    def supports_entity(self, entity_id: str) -> bool:
        return entity_id.startswith("input_datetime.") or entity_id.startswith("time.")
    
    def read_point(self, entity_id: str, entity_point: str, 
                   entity_data: Dict[str, Any]) -> Any:
        """
        Read time entity value.
        
        Returns the time as a string in HH:MM:SS format.
        """
        if entity_point == "state":
            # Time entities store their value as state
            return entity_data.get("state", "00:00:00")
        else:
            # Read other attributes if any
            return entity_data.get("attributes", {}).get(entity_point, None)
    
    def write_point(self, entity_id: str, entity_point: str, 
                   value: Any, units: Optional[str] = None) -> None:
        """
        Set time entity value.
        
        Args:
            entity_id: The time entity (e.g., 'input_datetime.alarm_time')
            entity_point: Should be 'state' for setting the time
            value: Time value as string in format HH:MM:SS or HH:MM
            units: Not used for time entities
        """
        if entity_point != "state":
            raise ValueError(f"For time entities, only 'state' is writable. Got: {entity_point}")
        
        if not isinstance(value, str):
            raise ValueError(f"Time value must be a string in HH:MM:SS or HH:MM format")
        
        self._set_time(entity_id, value)
    
    def _set_time(self, entity_id: str, time_value: str) -> None:
        """
        Set the time value.
        
        Args:
            entity_id: The time entity ID
            time_value: Time string in HH:MM:SS or HH:MM format
        """
        # Validate and normalize time format
        time_value = self._validate_time_format(time_value)
        
        # Determine which service to use based on entity type
        if entity_id.startswith("input_datetime."):
            # For input_datetime entities, use input_datetime.set_datetime service
            data = {
                "entity_id": entity_id,
                "time": time_value
            }
            self.client.call_service("input_datetime", "set_datetime", data,
                                    f"set time for {entity_id} to {time_value}")
        elif entity_id.startswith("time."):
            # For time entities, use time.set_value service
            data = {
                "entity_id": entity_id,
                "time": time_value
            }
            self.client.call_service("time", "set_value", data,
                                    f"set time for {entity_id} to {time_value}")
        else:
            raise ValueError(f"Unsupported time entity type: {entity_id}")
    
    def _validate_time_format(self, time_value: str) -> str:
        """
        Validate and normalize time format.
        
        Accepts HH:MM or HH:MM:SS format.
        Returns normalized time string.
        """
        import re
        
        # Pattern for HH:MM:SS
        pattern_full = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])


# =============================================================================
# Main Interface
# =============================================================================

class Interface(BasicRevert, BaseInterface):
    """
    VOLTTRON Platform Driver interface for Home Assistant.
    
    This interface enables VOLTTRON to interact with Home Assistant devices
    through the REST API, providing read/write access to entity states and
    attributes.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client: Optional[HomeAssistantClient] = None
        self.controllers: List[DeviceController] = []
    
    def configure(self, config_dict: Dict[str, Any], registry_config_str: Any) -> None:
        """
        Configure the interface with connection details and device registry.
        
        Args:
            config_dict: Configuration containing IP, port, and access token
            registry_config_str: Registry configuration defining device points
        """
        # Extract and validate required configuration
        ip_address = config_dict.get("ip_address")
        access_token = config_dict.get("access_token")
        port = config_dict.get("port")
        
        self._validate_config(ip_address, access_token, port)
        
        # Initialize API client
        self.client = HomeAssistantClient(ip_address, port, access_token)
        
        # Initialize device controllers in priority order
        # Specific controllers are checked before generic controller
        self.controllers = [
            LightController(self.client),
            ClimateController(self.client),
            InputBooleanController(self.client),
            LockController(self.client),
            NotifyController(self.client),
            TimeController(self.client),
            GenericController(self.client)  # Fallback for other entities
        ]
        
        # Parse and register device points
        self.parse_config(registry_config_str)
    
    def _validate_config(self, ip_address: Optional[str], access_token: Optional[str], 
                        port: Optional[int]) -> None:
        """Validate required configuration parameters."""
        if not ip_address:
            _log.error("IP address is required")
            raise ValueError("IP address is required")
        if not access_token:
            _log.error("Access token is required")
            raise ValueError("Access token is required")
        if not port:
            _log.error("Port is required")
            raise ValueError("Port is required")
    
    def get_point(self, point_name: str) -> Any:
        """
        Read a single point value from Home Assistant.
        
        Args:
            point_name: The VOLTTRON point name
            
        Returns:
            The current value of the point
        """
        register = self.get_register_by_name(point_name)
        entity_data = self.client.get_entity_state(register.entity_id)
        
        controller = self._get_controller(register.entity_id)
        return controller.read_point(register.entity_id, register.entity_point, entity_data)
    
    def _set_point(self, point_name: str, value: Any) -> Any:
        """
        Write a value to a Home Assistant entity.
        
        Args:
            point_name: The VOLTTRON point name
            value: The value to write
            
        Returns:
            The value that was written (after type conversion)
        """
        register = self.get_register_by_name(point_name)
        
        if register.read_only:
            raise IOError(f"Point '{point_name}' is configured as read-only")
        
        # Convert value to the appropriate type
        typed_value = register.reg_type(value)
        
        # Get the appropriate controller and write the value
        controller = self._get_controller(register.entity_id)
        controller.write_point(register.entity_id, register.entity_point, 
                             typed_value, register.units)
        
        register.value = typed_value
        return typed_value
    
    def _scrape_all(self) -> Dict[str, Any]:
        """
        Read all configured points from Home Assistant.
        
        Returns:
            Dictionary mapping point names to their current values
        """
        result = {}
        all_registers = (self.get_registers_by_type("byte", True) + 
                        self.get_registers_by_type("byte", False))
        
        for register in all_registers:
            try:
                entity_data = self.client.get_entity_state(register.entity_id)
                controller = self._get_controller(register.entity_id)
                
                value = controller.read_point(register.entity_id, 
                                             register.entity_point, 
                                             entity_data)
                register.value = value
                result[register.point_name] = value
                
            except Exception as e:
                _log.error(f"Error reading {register.entity_id}: {e}")
        
        return result
    
    def _get_controller(self, entity_id: str) -> DeviceController:
        """
        Get the appropriate controller for an entity.
        
        Args:
            entity_id: The Home Assistant entity ID
            
        Returns:
            The controller that handles this entity type
        """
        for controller in self.controllers:
            if controller.supports_entity(entity_id):
                return controller
        
        # Should never reach here since GenericController supports all
        raise ValueError(f"No controller found for entity {entity_id}")
    
    def parse_config(self, config_dict: List[Dict[str, Any]]) -> None:
        """
        Parse the registry configuration and create registers.
        
        Args:
            config_dict: List of register definitions
        """
        if not config_dict:
            return
        
        for reg_def in config_dict:
            # Skip entries without an entity ID
            if not reg_def.get('Entity ID'):
                continue
            
            # Extract register parameters
            read_only = str(reg_def.get('Writable', '')).lower() != 'true'
            entity_id = reg_def['Entity ID']
            entity_point = reg_def['Entity Point']
            point_name = reg_def['Volttron Point Name']
            units = reg_def.get('Units', '')
            description = reg_def.get('Notes', '')
            type_name = reg_def.get('Type', 'string')
            reg_type = TYPE_MAPPING.get(type_name, str)
            attributes = reg_def.get('Attributes', {})
            
            # Create and insert register
            register = HomeAssistantRegister(
                read_only=read_only,
                point_name=point_name,
                units=units,
                reg_type=reg_type,
                attributes=attributes,
                entity_id=entity_id,
                entity_point=entity_point,
                default_value=None,
                description=description
            )
            
            self.insert_register(register)

        # Pattern for HH:MM (will add :00 for seconds)
        pattern_short = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])


# =============================================================================
# Main Interface
# =============================================================================

class Interface(BasicRevert, BaseInterface):
    """
    VOLTTRON Platform Driver interface for Home Assistant.
    
    This interface enables VOLTTRON to interact with Home Assistant devices
    through the REST API, providing read/write access to entity states and
    attributes.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client: Optional[HomeAssistantClient] = None
        self.controllers: List[DeviceController] = []
    
    def configure(self, config_dict: Dict[str, Any], registry_config_str: Any) -> None:
        """
        Configure the interface with connection details and device registry.
        
        Args:
            config_dict: Configuration containing IP, port, and access token
            registry_config_str: Registry configuration defining device points
        """
        # Extract and validate required configuration
        ip_address = config_dict.get("ip_address")
        access_token = config_dict.get("access_token")
        port = config_dict.get("port")
        
        self._validate_config(ip_address, access_token, port)
        
        # Initialize API client
        self.client = HomeAssistantClient(ip_address, port, access_token)
        
        # Initialize device controllers in priority order
        # Specific controllers are checked before generic controller
        self.controllers = [
            LightController(self.client),
            ClimateController(self.client),
            InputBooleanController(self.client),
            LockController(self.client),
            NotifyController(self.client),
            GenericController(self.client)  # Fallback for other entities
        ]
        
        # Parse and register device points
        self.parse_config(registry_config_str)
    
    def _validate_config(self, ip_address: Optional[str], access_token: Optional[str], 
                        port: Optional[int]) -> None:
        """Validate required configuration parameters."""
        if not ip_address:
            _log.error("IP address is required")
            raise ValueError("IP address is required")
        if not access_token:
            _log.error("Access token is required")
            raise ValueError("Access token is required")
        if not port:
            _log.error("Port is required")
            raise ValueError("Port is required")
    
    def get_point(self, point_name: str) -> Any:
        """
        Read a single point value from Home Assistant.
        
        Args:
            point_name: The VOLTTRON point name
            
        Returns:
            The current value of the point
        """
        register = self.get_register_by_name(point_name)
        entity_data = self.client.get_entity_state(register.entity_id)
        
        controller = self._get_controller(register.entity_id)
        return controller.read_point(register.entity_id, register.entity_point, entity_data)
    
    def _set_point(self, point_name: str, value: Any) -> Any:
        """
        Write a value to a Home Assistant entity.
        
        Args:
            point_name: The VOLTTRON point name
            value: The value to write
            
        Returns:
            The value that was written (after type conversion)
        """
        register = self.get_register_by_name(point_name)
        
        if register.read_only:
            raise IOError(f"Point '{point_name}' is configured as read-only")
        
        # Convert value to the appropriate type
        typed_value = register.reg_type(value)
        
        # Get the appropriate controller and write the value
        controller = self._get_controller(register.entity_id)
        controller.write_point(register.entity_id, register.entity_point, 
                             typed_value, register.units)
        
        register.value = typed_value
        return typed_value
    
    def _scrape_all(self) -> Dict[str, Any]:
        """
        Read all configured points from Home Assistant.
        
        Returns:
            Dictionary mapping point names to their current values
        """
        result = {}
        all_registers = (self.get_registers_by_type("byte", True) + 
                        self.get_registers_by_type("byte", False))
        
        for register in all_registers:
            try:
                entity_data = self.client.get_entity_state(register.entity_id)
                controller = self._get_controller(register.entity_id)
                
                value = controller.read_point(register.entity_id, 
                                             register.entity_point, 
                                             entity_data)
                register.value = value
                result[register.point_name] = value
                
            except Exception as e:
                _log.error(f"Error reading {register.entity_id}: {e}")
        
        return result
    
    def _get_controller(self, entity_id: str) -> DeviceController:
        """
        Get the appropriate controller for an entity.
        
        Args:
            entity_id: The Home Assistant entity ID
            
        Returns:
            The controller that handles this entity type
        """
        for controller in self.controllers:
            if controller.supports_entity(entity_id):
                return controller
        
        # Should never reach here since GenericController supports all
        raise ValueError(f"No controller found for entity {entity_id}")
    
    def parse_config(self, config_dict: List[Dict[str, Any]]) -> None:
        """
        Parse the registry configuration and create registers.
        
        Args:
            config_dict: List of register definitions
        """
        if not config_dict:
            return
        
        for reg_def in config_dict:
            # Skip entries without an entity ID
            if not reg_def.get('Entity ID'):
                continue
            
            # Extract register parameters
            read_only = str(reg_def.get('Writable', '')).lower() != 'true'
            entity_id = reg_def['Entity ID']
            entity_point = reg_def['Entity Point']
            point_name = reg_def['Volttron Point Name']
            units = reg_def.get('Units', '')
            description = reg_def.get('Notes', '')
            type_name = reg_def.get('Type', 'string')
            reg_type = TYPE_MAPPING.get(type_name, str)
            attributes = reg_def.get('Attributes', {})
            
            # Create and insert register
            register = HomeAssistantRegister(
                read_only=read_only,
                point_name=point_name,
                units=units,
                reg_type=reg_type,
                attributes=attributes,
                entity_id=entity_id,
                entity_point=entity_point,
                default_value=None,
                description=description
            )
            
            self.insert_register(register)

        
        if re.match(pattern_full, time_value):
            return time_value
        elif re.match(pattern_short, time_value):
            # Add seconds if not provided
            return f"{time_value}:00"
        else:
            raise ValueError(
                f"Invalid time format: '{time_value}'. "
                f"Expected HH:MM:SS or HH:MM (e.g., '14:30:00' or '14:30')"
            )


# =============================================================================
# Main Interface
# =============================================================================

class Interface(BasicRevert, BaseInterface):
    """
    VOLTTRON Platform Driver interface for Home Assistant.
    
    This interface enables VOLTTRON to interact with Home Assistant devices
    through the REST API, providing read/write access to entity states and
    attributes.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client: Optional[HomeAssistantClient] = None
        self.controllers: List[DeviceController] = []
    
    def configure(self, config_dict: Dict[str, Any], registry_config_str: Any) -> None:
        """
        Configure the interface with connection details and device registry.
        
        Args:
            config_dict: Configuration containing IP, port, and access token
            registry_config_str: Registry configuration defining device points
        """
        # Extract and validate required configuration
        ip_address = config_dict.get("ip_address")
        access_token = config_dict.get("access_token")
        port = config_dict.get("port")
        
        self._validate_config(ip_address, access_token, port)
        
        # Initialize API client
        self.client = HomeAssistantClient(ip_address, port, access_token)
        
        # Initialize device controllers in priority order
        # Specific controllers are checked before generic controller
        self.controllers = [
            LightController(self.client),
            ClimateController(self.client),
            InputBooleanController(self.client),
            LockController(self.client),
            NotifyController(self.client),
            GenericController(self.client)  # Fallback for other entities
        ]
        
        # Parse and register device points
        self.parse_config(registry_config_str)
    
    def _validate_config(self, ip_address: Optional[str], access_token: Optional[str], 
                        port: Optional[int]) -> None:
        """Validate required configuration parameters."""
        if not ip_address:
            _log.error("IP address is required")
            raise ValueError("IP address is required")
        if not access_token:
            _log.error("Access token is required")
            raise ValueError("Access token is required")
        if not port:
            _log.error("Port is required")
            raise ValueError("Port is required")
    
    def get_point(self, point_name: str) -> Any:
        """
        Read a single point value from Home Assistant.
        
        Args:
            point_name: The VOLTTRON point name
            
        Returns:
            The current value of the point
        """
        register = self.get_register_by_name(point_name)
        entity_data = self.client.get_entity_state(register.entity_id)
        
        controller = self._get_controller(register.entity_id)
        return controller.read_point(register.entity_id, register.entity_point, entity_data)
    
    def _set_point(self, point_name: str, value: Any) -> Any:
        """
        Write a value to a Home Assistant entity.
        
        Args:
            point_name: The VOLTTRON point name
            value: The value to write
            
        Returns:
            The value that was written (after type conversion)
        """
        register = self.get_register_by_name(point_name)
        
        if register.read_only:
            raise IOError(f"Point '{point_name}' is configured as read-only")
        
        # Convert value to the appropriate type
        typed_value = register.reg_type(value)
        
        # Get the appropriate controller and write the value
        controller = self._get_controller(register.entity_id)
        controller.write_point(register.entity_id, register.entity_point, 
                             typed_value, register.units)
        
        register.value = typed_value
        return typed_value
    
    def _scrape_all(self) -> Dict[str, Any]:
        """
        Read all configured points from Home Assistant.
        
        Returns:
            Dictionary mapping point names to their current values
        """
        result = {}
        all_registers = (self.get_registers_by_type("byte", True) + 
                        self.get_registers_by_type("byte", False))
        
        for register in all_registers:
            try:
                entity_data = self.client.get_entity_state(register.entity_id)
                controller = self._get_controller(register.entity_id)
                
                value = controller.read_point(register.entity_id, 
                                             register.entity_point, 
                                             entity_data)
                register.value = value
                result[register.point_name] = value
                
            except Exception as e:
                _log.error(f"Error reading {register.entity_id}: {e}")
        
        return result
    
    def _get_controller(self, entity_id: str) -> DeviceController:
        """
        Get the appropriate controller for an entity.
        
        Args:
            entity_id: The Home Assistant entity ID
            
        Returns:
            The controller that handles this entity type
        """
        for controller in self.controllers:
            if controller.supports_entity(entity_id):
                return controller
        
        # Should never reach here since GenericController supports all
        raise ValueError(f"No controller found for entity {entity_id}")
    
    def parse_config(self, config_dict: List[Dict[str, Any]]) -> None:
        """
        Parse the registry configuration and create registers.
        
        Args:
            config_dict: List of register definitions
        """
        if not config_dict:
            return
        
        for reg_def in config_dict:
            # Skip entries without an entity ID
            if not reg_def.get('Entity ID'):
                continue
            
            # Extract register parameters
            read_only = str(reg_def.get('Writable', '')).lower() != 'true'
            entity_id = reg_def['Entity ID']
            entity_point = reg_def['Entity Point']
            point_name = reg_def['Volttron Point Name']
            units = reg_def.get('Units', '')
            description = reg_def.get('Notes', '')
            type_name = reg_def.get('Type', 'string')
            reg_type = TYPE_MAPPING.get(type_name, str)
            attributes = reg_def.get('Attributes', {})
            
            # Create and insert register
            register = HomeAssistantRegister(
                read_only=read_only,
                point_name=point_name,
                units=units,
                reg_type=reg_type,
                attributes=attributes,
                entity_id=entity_id,
                entity_point=entity_point,
                default_value=None,
                description=description
            )
            
            self.insert_register(register)