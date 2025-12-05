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


import random
from math import pi
import json
import sys
from platform_driver.interfaces import BaseInterface, BaseRegister, BasicRevert
from volttron.platform.agent import utils
from volttron.platform.vip.agent import Agent
import logging
import requests
from requests import get

_log = logging.getLogger(__name__)
type_mapping = {"string": str,
                "int": int,
                "integer": int,
                "float": float,
                "bool": bool,
                "boolean": bool}

# Device state constants - eliminates magic numbers
class DeviceState:
    """Constants for device states"""
    OFF = 0
    ON = 1
    UNLOCKED = 0
    LOCKED = 1

class ThermostatMode:
    """Constants for thermostat modes"""
    OFF = 0
    HEAT = 2
    COOL = 3
    AUTO = 4

class LawnMowerActivity:
    """Constants for lawn mower activities"""
    DOCKED = 0
    MOWING = 1
    PAUSED = 2
    RETURNING = 3
    ERROR = 4

class HomeAssistantRegister(BaseRegister):
    def __init__(self, read_only, pointName, units, reg_type, attributes, entity_id, entity_point, default_value=None,
                 description=''):
        super(HomeAssistantRegister, self).__init__("byte", read_only, pointName, units, description='')
        self.reg_type = reg_type
        self.attributes = attributes
        self.entity_id = entity_id
        self.value = None
        self.entity_point = entity_point


def _post_method(url, headers, data, operation_description):
    err = None
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            _log.info(f"Success: {operation_description}")
        else:
            err = f"Failed to {operation_description}. Status code: {response.status_code}. " \
                  f"Response: {response.text}"

    except requests.RequestException as e:
        err = f"Error when attempting - {operation_description} : {e}"
    if err:
        _log.error(err)
        raise Exception(err)


class Interface(BasicRevert, BaseInterface):
    def __init__(self, **kwargs):
        super(Interface, self).__init__(**kwargs)
        self.point_name = None
        self.ip_address = None
        self.access_token = None
        self.port = None
        self.units = None

    def configure(self, config_dict, registry_config_str):
        self.ip_address = config_dict.get("ip_address", None)
        self.access_token = config_dict.get("access_token", None)
        self.port = config_dict.get("port", None)

        # Check for None values
        if self.ip_address is None:
            _log.error("IP address is not set.")
            raise ValueError("IP address is required.")
        if self.access_token is None:
            _log.error("Access token is not set.")
            raise ValueError("Access token is required.")
        if self.port is None:
            _log.error("Port is not set.")
            raise ValueError("Port is required.")

        self.parse_config(registry_config_str)

    def _get_headers(self):
        """
        Get standard headers for Home Assistant API requests.
        
        Returns:
            dict: Headers with authorization and content type
        """
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _call_service(self, domain, service, entity_id, extra_data=None):
        """
        Generic method to call Home Assistant services.
        Eliminates code duplication across all device control methods.
        
        Args:
            domain (str): Service domain (e.g., 'light', 'lock', 'fan')
            service (str): Service name (e.g., 'turn_on', 'lock', 'set_percentage')
            entity_id (str): The entity ID to control
            extra_data (dict, optional): Additional data to include in payload
        """
        url = f"http://{self.ip_address}:{self.port}/api/services/{domain}/{service}"
        headers = self._get_headers()
        payload = {"entity_id": entity_id}
        
        if extra_data:
            payload.update(extra_data)
        
        _post_method(url, headers, payload, f"{service} {entity_id}")

    def get_point(self, point_name):
        register = self.get_register_by_name(point_name)

        entity_data = self.get_entity_data(register.entity_id)
        if register.point_name == "state":
            result = entity_data.get("state", None)
            return result
        else:
            value = entity_data.get("attributes", {}).get(f"{register.point_name}", 0)
            return value

    def _set_point(self, point_name, value):
        register = self.get_register_by_name(point_name)
        if register.read_only:
            raise IOError(
                "Trying to write to a point configured read only: " + point_name)
        register.value = register.reg_type(value)  # setting the value
        entity_point = register.entity_point
        # Changing lights values in home assistant based off of register value.
        if "light." in register.entity_id:
            if entity_point == "state":
                if isinstance(register.value, int) and register.value in [DeviceState.OFF, DeviceState.ON]:
                    if register.value == DeviceState.ON:
                        self.turn_on_lights(register.entity_id)
                    elif register.value == DeviceState.OFF:
                        self.turn_off_lights(register.entity_id)
                else:
                    error_msg = f"State value for {register.entity_id} should be an integer value of 1 or 0"
                    _log.info(error_msg)
                    raise ValueError(error_msg)

            elif entity_point == "brightness":
                if isinstance(register.value, int) and 0 <= register.value <= 255:  # Make sure its int and within range
                    self.change_brightness(register.entity_id, register.value)
                else:
                    error_msg = "Brightness value should be an integer between 0 and 255"
                    _log.error(error_msg)
                    raise ValueError(error_msg)
            else:
                error_msg = f"Unexpected point_name {point_name} for register {register.entity_id}"
                _log.error(error_msg)
                raise ValueError(error_msg)

        elif "input_boolean." in register.entity_id:
            if entity_point == "state":
                if isinstance(register.value, int) and register.value in [DeviceState.OFF, DeviceState.ON]:
                    if register.value == DeviceState.ON:
                        self.set_input_boolean(register.entity_id, "on")
                    elif register.value == DeviceState.OFF:
                        self.set_input_boolean(register.entity_id, "off")
                else:
                    error_msg = f"State value for {register.entity_id} should be an integer value of 1 or 0"
                    _log.info(error_msg)
                    raise ValueError(error_msg)
            else:
                _log.info(f"Currently, input_booleans only support state")

        # Changing thermostat values.
        elif "climate." in register.entity_id:
            if entity_point == "state":
                if isinstance(register.value, int) and register.value in [ThermostatMode.OFF, ThermostatMode.HEAT, 
                                                           ThermostatMode.COOL, ThermostatMode.AUTO]:
                    if register.value == ThermostatMode.OFF:
                        self.change_thermostat_mode(entity_id=register.entity_id, mode="off")
                    elif register.value == ThermostatMode.HEAT:
                        self.change_thermostat_mode(entity_id=register.entity_id, mode="heat")
                    elif register.value == ThermostatMode.COOL:
                        self.change_thermostat_mode(entity_id=register.entity_id, mode="cool")
                    elif register.value == ThermostatMode.AUTO:
                        self.change_thermostat_mode(entity_id=register.entity_id, mode="auto")
                else:
                    error_msg = f"Climate state should be an integer value of 0, 2, 3, or 4"
                    _log.error(error_msg)
                    raise ValueError(error_msg)
            elif entity_point == "temperature":
                self.set_thermostat_temperature(entity_id=register.entity_id, temperature=register.value)

            else:
                error_msg = f"Currently set_point is supported only for thermostats state and temperature {register.entity_id}"
                _log.error(error_msg)
                raise ValueError(error_msg)

        # Enable lock/unlock control via state attribute
        elif "lock." in register.entity_id:
            if entity_point == "state":
                # Validate that value is 0 (unlock) or 1 (lock)
                if isinstance(register.value, int) and register.value in [DeviceState.UNLOCKED, DeviceState.LOCKED]:
                    if register.value == DeviceState.LOCKED:
                        self.lock_device(register.entity_id)
                    elif register.value == DeviceState.UNLOCKED:
                        self.unlock_device(register.entity_id)
                else:
                    error_msg = f"State value for {register.entity_id} should be an integer: " \
                                f"0 (unlocked) or 1 (locked). Received: {register.value}"
                    _log.error(error_msg)
                    raise ValueError(error_msg)
            else:
                error_msg = f"Lock devices only support state control (lock/unlock). " \
                            f"Cannot set '{entity_point}' attribute."
                _log.error(error_msg)
                raise ValueError(error_msg)

        # Fan device support
        elif "fan." in register.entity_id:
            if entity_point == "state":
                # Control fan on/off
                if isinstance(register.value, int) and register.value in [DeviceState.OFF, DeviceState.ON]:
                    if register.value == DeviceState.ON:
                        self.turn_on_fan(register.entity_id)
                    elif register.value == DeviceState.OFF:
                        self.turn_off_fan(register.entity_id)
                else:
                    error_msg = f"State value for {register.entity_id} should be 0 (off) or 1 (on)"
                    _log.error(error_msg)
                    raise ValueError(error_msg)
            
            elif entity_point == "percentage":
                # Control fan speed (0-100%)
                if isinstance(register.value, (int, float)) and 0 <= register.value <= 100:
                    self.set_fan_percentage(register.entity_id, int(register.value))
                else:
                    error_msg = f"Percentage value for {register.entity_id} should be between 0-100"
                    _log.error(error_msg)
                    raise ValueError(error_msg)
            
            else:
                error_msg = f"Fan devices support 'state' and 'percentage' attributes only"
                _log.error(error_msg)
                raise ValueError(error_msg)

        # Lawn mower device support
        elif "lawn_mower." in register.entity_id:
            if entity_point == "activity":
                # Control lawn mower activity
                valid_activities = [LawnMowerActivity.DOCKED, LawnMowerActivity.MOWING, 
                                   LawnMowerActivity.PAUSED, LawnMowerActivity.RETURNING]
                if isinstance(register.value, int) and register.value in valid_activities:
                    if register.value == LawnMowerActivity.MOWING:
                        self.start_mowing(register.entity_id)
                    elif register.value == LawnMowerActivity.DOCKED:
                        self.dock_lawn_mower(register.entity_id)
                    elif register.value == LawnMowerActivity.PAUSED:
                        self.pause_lawn_mower(register.entity_id)
                    elif register.value == LawnMowerActivity.RETURNING:
                        # Returning is a state, not a command, so we use dock
                        self.dock_lawn_mower(register.entity_id)
                else:
                    error_msg = f"Activity value for {register.entity_id} should be " \
                                f"{LawnMowerActivity.DOCKED} (dock), {LawnMowerActivity.MOWING} (mowing), " \
                                f"{LawnMowerActivity.PAUSED} (pause), or {LawnMowerActivity.RETURNING} (return)"
                    _log.error(error_msg)
                    raise ValueError(error_msg)
            else:
                error_msg = f"Lawn mower devices currently support 'activity' attribute only"
                _log.error(error_msg)
                raise ValueError(error_msg)

        else:
            error_msg = f"Unsupported entity_id: {register.entity_id}. " \
                        f"Currently set_point is supported only for thermostats and lights"
            _log.error(error_msg)
            raise ValueError(error_msg)
        return register.value

    def get_entity_data(self, point_name):
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        # the /states grabs current state AND attributes of a specific entity
        url = f"http://{self.ip_address}:{self.port}/api/states/{point_name}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()  # return the json attributes from entity
        else:
            error_msg = f"Request failed with status code {response.status_code}, Point name: {point_name}, " \
                        f"response: {response.text}"
            _log.error(error_msg)
            raise Exception(error_msg)

    def _scrape_all(self):
        result = {}
        read_registers = self.get_registers_by_type("byte", True)
        write_registers = self.get_registers_by_type("byte", False)

        for register in read_registers + write_registers:
            entity_id = register.entity_id
            entity_point = register.entity_point
            try:
                entity_data = self.get_entity_data(entity_id)  # Using Entity ID to get data
                if "climate." in entity_id:  # handling thermostats.
                    if entity_point == "state":
                        state = entity_data.get("state", None)
                        # Giving thermostat states an equivalent number.
                        if state == "off":
                            register.value = 0
                            result[register.point_name] = 0
                        elif state == "heat":
                            register.value = 2
                            result[register.point_name] = 2
                        elif state == "cool":
                            register.value = 3
                            result[register.point_name] = 3
                        elif state == "auto":
                            register.value = 4
                            result[register.point_name] = 4
                        else:
                            error_msg = f"State {state} from {entity_id} is not yet supported"
                            _log.error(error_msg)
                            ValueError(error_msg)
                    # Assigning attributes
                    else:
                        attribute = entity_data.get("attributes", {}).get(f"{entity_point}", 0)
                        register.value = attribute
                        result[register.point_name] = attribute
                # handling light states
                elif "light." or "input_boolean." in entity_id: # Checks for lights or input bools since they have the same states.
                    if entity_point == "state":
                        state = entity_data.get("state", None)
                        # Converting light states to numbers.
                        if state == "on":
                            register.value = 1
                            result[register.point_name] = 1
                        elif state == "off":
                            register.value = 0
                            result[register.point_name] = 0
                    else:
                        attribute = entity_data.get("attributes", {}).get(f"{entity_point}", 0)
                        register.value = attribute
                        result[register.point_name] = attribute
                
                # handling lock states
                elif "lock." in entity_id:
                    if entity_point == "state":
                        state = entity_data.get("state", None)
                        # Converting lock states to numbers
                        if state == "locked":
                            register.value = 1
                            result[register.point_name] = 1
                        elif state == "unlocked":
                            register.value = 0
                            result[register.point_name] = 0
                        else:
                            # Handle transitional states (locking, unlocking, jammed, etc.)
                            _log.warning(f"Lock {entity_id} is in transitional state: {state}")
                            register.value = state
                            result[register.point_name] = state
                    else:
                        # Handle other lock attributes if needed
                        attribute = entity_data.get("attributes", {}).get(f"{entity_point}", 0)
                        register.value = attribute
                        result[register.point_name] = attribute

                # handling fan states
                elif "fan." in entity_id:
                    if entity_point == "state":
                        state = entity_data.get("state", None)
                        # Converting fan states to numbers
                        if state == "on":
                            register.value = 1
                            result[register.point_name] = 1
                        elif state == "off":
                            register.value = 0
                            result[register.point_name] = 0
                        else:
                            _log.warning(f"Unknown fan state '{state}' for {entity_id}")
                            register.value = state
                            result[register.point_name] = state
                    elif entity_point == "percentage":
                        # Get fan speed percentage
                        percentage = entity_data.get("attributes", {}).get("percentage", 0)
                        register.value = percentage
                        result[register.point_name] = percentage
                    else:
                        # Other fan attributes
                        attribute = entity_data.get("attributes", {}).get(f"{entity_point}", 0)
                        register.value = attribute
                        result[register.point_name] = attribute
                
                # handling lawn mower activities
                elif "lawn_mower." in entity_id:
                    if entity_point == "activity":
                        activity = entity_data.get("state", None)
                        # Convert lawn mower activities to numbers
                        # mowing=1, docked=0, paused=2, returning=3, error=4
                        if activity == "mowing":
                            register.value = 1
                            result[register.point_name] = 1
                        elif activity == "docked":
                            register.value = 0
                            result[register.point_name] = 0
                        elif activity == "paused":
                            register.value = 2
                            result[register.point_name] = 2
                        elif activity == "returning":
                            register.value = 3
                            result[register.point_name] = 3
                        elif activity == "error":
                            register.value = 4
                            result[register.point_name] = 4
                            _log.error(f"Lawn mower {entity_id} is in error state")
                        else:
                            _log.warning(f"Unknown lawn mower activity '{activity}' for {entity_id}")
                            register.value = activity
                            result[register.point_name] = activity
                    else:
                        # Other lawn mower attributes
                        attribute = entity_data.get("attributes", {}).get(f"{entity_point}", 0)
                        register.value = attribute
                        result[register.point_name] = attribute

                else:  # handling all devices that are not thermostats or light states
                    if entity_point == "state":

                        state = entity_data.get("state", None)
                        register.value = state
                        result[register.point_name] = state
                    # Assigning attributes
                    else:
                        attribute = entity_data.get("attributes", {}).get(f"{entity_point}", 0)
                        register.value = attribute
                        result[register.point_name] = attribute
            except Exception as e:
                _log.error(f"An unexpected error occurred for entity_id: {entity_id}: {e}")

        return result

    def parse_config(self, config_dict):

        if config_dict is None:
            return
        for regDef in config_dict:

            if not regDef['Entity ID']:
                continue

            read_only = str(regDef.get('Writable', '')).lower() != 'true'
            entity_id = regDef['Entity ID']
            entity_point = regDef['Entity Point']
            self.point_name = regDef['Volttron Point Name']
            self.units = regDef['Units']
            description = regDef.get('Notes', '')
            default_value = ("Starting Value")
            type_name = regDef.get("Type", 'string')
            reg_type = type_mapping.get(type_name, str)
            attributes = regDef.get('Attributes', {})
            register_type = HomeAssistantRegister

            register = register_type(
                read_only,
                self.point_name,
                self.units,
                reg_type,
                attributes,
                entity_id,
                entity_point,
                default_value=default_value,
                description=description)

            if default_value is not None:
                self.set_default(self.point_name, register.value)

            self.insert_register(register)

    def turn_off_lights(self, entity_id):
        """Turn off the specified light."""
        self._call_service("light", "turn_off", entity_id)

    def turn_on_lights(self, entity_id):
        """Turn on the specified light."""
        self._call_service("light", "turn_on", entity_id)

    def change_brightness(self, entity_id, value):
        """Change brightness of the light (0-255)."""
        self._call_service("light", "turn_on", entity_id, {"brightness": value})

    def change_thermostat_mode(self, entity_id, mode):
        """Change thermostat HVAC mode."""
        if not entity_id.startswith("climate."):
            _log.error(f"{entity_id} is not a valid thermostat entity ID.")
            return
        self._call_service("climate", "set_hvac_mode", entity_id, {"hvac_mode": mode})

    def set_thermostat_temperature(self, entity_id, temperature):
        """Set thermostat temperature."""
        if not entity_id.startswith("climate."):
            _log.error(f"{entity_id} is not a valid thermostat entity ID.")
            return
        
        # Convert temperature if needed
        if self.units == "C":
            temperature = round((temperature - 32) * 5/9, 1)
            _log.info(f"Converted temperature to {temperature}C")
        
        self._call_service("climate", "set_temperature", entity_id, {"temperature": temperature})

    def set_input_boolean(self, entity_id, state):
        """Set input boolean state."""
        service = 'turn_on' if state == 'on' else 'turn_off'
        self._call_service("input_boolean", service, entity_id)
    
    def lock_device(self, entity_id):
        """Lock the specified lock device."""
        self._call_service("lock", "lock", entity_id)

    def unlock_device(self, entity_id):
        """Unlock the specified lock device."""
        self._call_service("lock", "unlock", entity_id)

    def turn_on_fan(self, entity_id):
        """Turn on the specified fan device."""
        self._call_service("fan", "turn_on", entity_id)

    def turn_off_fan(self, entity_id):
        """Turn off the specified fan device."""
        self._call_service("fan", "turn_off", entity_id)

    def set_fan_percentage(self, entity_id, percentage):
        """Set the speed percentage of the fan (0-100%)."""
        self._call_service("fan", "set_percentage", entity_id, {"percentage": percentage})

    def start_mowing(self, entity_id):
        """Start or resume the mowing task."""
        self._call_service("lawn_mower", "start_mowing", entity_id)

    def dock_lawn_mower(self, entity_id):
        """Stop the lawn mower and return to dock."""
        self._call_service("lawn_mower", "dock", entity_id)

    def pause_lawn_mower(self, entity_id):
        """Pause the lawn mower during current operation."""
        self._call_service("lawn_mower", "pause", entity_id)
