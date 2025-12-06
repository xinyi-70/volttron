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

import json
import logging
import os
import sys

import gevent
import pytest

# Ensure platform_driver package is importable for direct handler testing
CURRENT_DIR = os.path.dirname(__file__)
PLATFORM_DRIVER_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PLATFORM_DRIVER_ROOT not in sys.path:
    sys.path.insert(0, PLATFORM_DRIVER_ROOT)

from platform_driver.interfaces.home_assistant import (
    DeviceState,
    HomeAssistantRegister,
    Interface,
    LawnMowerActivity,
    ThermostatMode,
)
from volttron.platform.agent.known_identities import (
    PLATFORM_DRIVER,
    CONFIGURATION_STORE,
)
from volttron.platform import get_services_core
from volttron.platform.agent import utils
from volttron.platform.keystore import KeyStore
from volttrontesting.utils.platformwrapper import PlatformWrapper

utils.setup_logging()
logger = logging.getLogger(__name__)

# To run these tests, create a helper toggle named volttrontest in your Home Assistant instance.
# This can be done by going to Settings > Devices & services > Helpers > Create Helper > Toggle
HOMEASSISTANT_TEST_IP = ""
ACCESS_TOKEN = ""
PORT = ""

skip_msg = "Some configuration variables are not set. Check HOMEASSISTANT_TEST_IP, ACCESS_TOKEN, and PORT"
# Integration-only skip marker
integration_skip = pytest.mark.skipif(
    not (HOMEASSISTANT_TEST_IP and ACCESS_TOKEN and PORT),
    reason=skip_msg
)

HOMEASSISTANT_DEVICE_TOPIC = "devices/home_assistant"


# Get the point which will should be off
@integration_skip
def test_get_point(volttron_instance, config_store):
    expected_values = 0
    agent = volttron_instance.dynamic_agent
    result = agent.vip.rpc.call(PLATFORM_DRIVER, 'get_point', 'home_assistant', 'bool_state').get(timeout=20)
    assert result == expected_values, "The result does not match the expected result."


# The default value for this fake light is 3. If the test cannot reach out to home assistant,
# the value will default to 3 making the test fail.
@integration_skip
def test_data_poll(volttron_instance: PlatformWrapper, config_store):
    expected_values = [{'bool_state': 0}, {'bool_state': 1}]
    agent = volttron_instance.dynamic_agent
    result = agent.vip.rpc.call(PLATFORM_DRIVER, 'scrape_all', 'home_assistant').get(timeout=20)
    assert result in expected_values, "The result does not match the expected result."


# Turn on the light. Light is automatically turned off every 30 seconds to allow test to turn
# it on and receive the correct value.
@integration_skip
def test_set_point(volttron_instance, config_store):
    expected_values = {'bool_state': 1}
    agent = volttron_instance.dynamic_agent
    agent.vip.rpc.call(PLATFORM_DRIVER, 'set_point', 'home_assistant', 'bool_state', 1)
    gevent.sleep(10)
    result = agent.vip.rpc.call(PLATFORM_DRIVER, 'scrape_all', 'home_assistant').get(timeout=20)
    assert result == expected_values, "The result does not match the expected result."


@pytest.fixture(scope="module")
def config_store(volttron_instance, platform_driver):
    """Configure platform driver and home_assistant registry for integration tests."""
    capabilities = [{"edit_config_store": {"identity": PLATFORM_DRIVER}}]
    volttron_instance.add_capabilities(volttron_instance.dynamic_agent.core.publickey, capabilities)

    registry_config = "homeassistant_test.json"
    registry_obj = [{
        "Entity ID": "input_boolean.volttrontest",
        "Entity Point": "state",
        "Volttron Point Name": "bool_state",
        "Units": "On / Off",
        "Units Details": "off: 0, on: 1",
        "Writable": True,
        "Starting Value": 3,
        "Type": "int",
        "Notes": "lights hallway"
    }]

    volttron_instance.dynamic_agent.vip.rpc.call(CONFIGURATION_STORE,
                                                 "manage_store",
                                                 PLATFORM_DRIVER,
                                                 registry_config,
                                                 json.dumps(registry_obj),
                                                 config_type="json")
    gevent.sleep(2)
    # driver config
    driver_config = {
        "driver_config": {"ip_address": HOMEASSISTANT_TEST_IP, "access_token": ACCESS_TOKEN, "port": PORT},
        "driver_type": "home_assistant",
        "registry_config": f"config://{registry_config}",
        "timezone": "US/Pacific",
        "interval": 30,
    }

    volttron_instance.dynamic_agent.vip.rpc.call(CONFIGURATION_STORE,
                                                 "manage_store",
                                                 PLATFORM_DRIVER,
                                                 HOMEASSISTANT_DEVICE_TOPIC,
                                                 json.dumps(driver_config),
                                                 config_type="json"
                                                 )
    gevent.sleep(2)

    yield platform_driver

    print("Wiping out store.")
    volttron_instance.dynamic_agent.vip.rpc.call(CONFIGURATION_STORE, "manage_delete_store", PLATFORM_DRIVER)
    gevent.sleep(0.1)


@pytest.fixture(scope="module")
def platform_driver(volttron_instance):
    # Start the platform driver agent which would in turn start the bacnet driver
    platform_uuid = volttron_instance.install_agent(
        agent_dir=get_services_core("PlatformDriverAgent"),
        config_file={
            "publish_breadth_first_all": False,
            "publish_depth_first": False,
            "publish_breadth_first": False,
        },
        start=True,
    )
    gevent.sleep(2)  # wait for the agent to start and start the devices
    assert volttron_instance.is_agent_running(platform_uuid)
    yield platform_uuid

    volttron_instance.stop_agent(platform_uuid)
    if not volttron_instance.debug_mode:
        volttron_instance.remove_agent(platform_uuid)


# -------- Unit-style tests for Home Assistant handler/scraper logic --------

def _make_register(entity_id, volttron_point, entity_point, reg_type=int, writable=True):
    """Helper to create a HomeAssistantRegister."""
    return HomeAssistantRegister(
        read_only=not writable,
        pointName=volttron_point,
        units="",
        reg_type=reg_type,
        attributes={},
        entity_id=entity_id,
        entity_point=entity_point,
        default_value=None,
        description="",
    )


def _interface_with_register(register):
    iface = Interface()
    iface.insert_register(register)
    return iface


def test_set_point_routes_light_state(monkeypatch):
    reg = _make_register("light.kitchen", "light_state", "state")
    iface = _interface_with_register(reg)
    called = {}
    monkeypatch.setattr(iface, "turn_on_lights", lambda eid: called.setdefault("on", eid))
    monkeypatch.setattr(iface, "turn_off_lights", lambda eid: called.setdefault("off", eid))

    iface._set_point("light_state", DeviceState.ON)
    assert called.get("on") == "light.kitchen"


def test_set_point_invalid_brightness_raises():
    reg = _make_register("light.kitchen", "light_brightness", "brightness")
    iface = _interface_with_register(reg)
    with pytest.raises(ValueError):
        iface._set_point("light_brightness", 300)


def test_set_point_fan_percentage(monkeypatch):
    reg = _make_register("fan.living_room", "fan_pct", "percentage")
    iface = _interface_with_register(reg)
    called = {}
    monkeypatch.setattr(iface, "set_fan_percentage", lambda eid, pct: called.setdefault("pct", (eid, pct)))
    iface._set_point("fan_pct", 55)
    assert called.get("pct") == ("fan.living_room", 55)


def test_set_point_lock_and_lawn_mower(monkeypatch):
    lock_reg = _make_register("lock.front_door", "lock_state", "state")
    mower_reg = _make_register("lawn_mower.yard", "mow_activity", "activity")
    iface = Interface()
    iface.insert_register(lock_reg)
    iface.insert_register(mower_reg)

    calls = {}
    monkeypatch.setattr(iface, "lock_device", lambda eid: calls.setdefault("lock", eid))
    monkeypatch.setattr(iface, "unlock_device", lambda eid: calls.setdefault("unlock", eid))
    monkeypatch.setattr(iface, "dock_lawn_mower", lambda eid: calls.setdefault("dock", eid))
    monkeypatch.setattr(iface, "start_mowing", lambda eid: calls.setdefault("mow", eid))

    iface._set_point("lock_state", DeviceState.LOCKED)
    iface._set_point("mow_activity", LawnMowerActivity.MOWING)
    iface._set_point("mow_activity", LawnMowerActivity.RETURNING)

    assert calls.get("lock") == "lock.front_door"
    assert calls.get("mow") == "lawn_mower.yard"
    assert calls.get("dock") == "lawn_mower.yard"


def test_set_point_unsupported_entity():
    reg = _make_register("sensor.unknown", "sensor_state", "state")
    iface = _interface_with_register(reg)
    with pytest.raises(ValueError):
        iface._set_point("sensor_state", 1)


def test_scrape_light_and_lock_mapping():
    light_reg = _make_register("light.kitchen", "light_state", "state")
    lock_reg = _make_register("lock.front_door", "lock_state", "state")
    iface = Interface()
    iface.insert_register(light_reg)
    iface.insert_register(lock_reg)

    light_data = {"state": "on", "attributes": {}}
    lock_data = {"state": "locked", "attributes": {}}

    iface._scrape_light(light_reg, light_data)
    iface._scrape_lock(lock_reg, lock_data)

    assert light_reg.value == DeviceState.ON
    assert lock_reg.value == DeviceState.LOCKED


def test_scrape_climate_maps_modes_and_temperature():
    reg_state = _make_register("climate.hvac", "hvac_state", "state")
    reg_temp = _make_register("climate.hvac", "hvac_temp", "temperature")
    iface = Interface()
    iface.insert_register(reg_state)
    iface.insert_register(reg_temp)

    state_data = {"state": "cool", "attributes": {}}
    temp_data = {"state": "cool", "attributes": {"temperature": 72}}

    iface._scrape_climate(reg_state, state_data)
    iface._scrape_climate(reg_temp, temp_data)

    assert reg_state.value == ThermostatMode.COOL
    assert reg_temp.value == 72


def test_handle_and_scrape_input_boolean(monkeypatch):
    reg = _make_register("input_boolean.volttrontest", "bool_state", "state")
    iface = _interface_with_register(reg)
    called = {}
    monkeypatch.setattr(iface, "set_input_boolean", lambda eid, state: called.setdefault("state", (eid, state)))

    iface._set_point("bool_state", DeviceState.ON)
    assert called.get("state") == ("input_boolean.volttrontest", "on")

    data = {"state": "off", "attributes": {}}
    iface._scrape_input_boolean(reg, data)
    assert reg.value == DeviceState.OFF


def test_scrape_fan_state_and_percentage():
    reg_state = _make_register("fan.living", "fan_state", "state")
    reg_pct = _make_register("fan.living", "fan_pct", "percentage")
    iface = Interface()
    iface.insert_register(reg_state)
    iface.insert_register(reg_pct)

    data = {"state": "on", "attributes": {"percentage": 70}}
    iface._scrape_fan(reg_state, data)
    iface._scrape_fan(reg_pct, data)

    assert reg_state.value == DeviceState.ON
    assert reg_pct.value == 70


def test_scrape_lawn_mower_mapping_unknown_and_error(caplog):
    reg = _make_register("lawn_mower.yard", "mow_activity", "activity")
    iface = Interface()
    iface.insert_register(reg)

    iface._scrape_lawn_mower(reg, {"state": "mowing", "attributes": {}})
    assert reg.value == LawnMowerActivity.MOWING

    iface._scrape_lawn_mower(reg, {"state": "error", "attributes": {}})
    assert reg.value == LawnMowerActivity.ERROR

    iface._scrape_lawn_mower(reg, {"state": "unknown", "attributes": {}})
    assert reg.value == "unknown"


def test_scrape_default_and_all_dispatch(monkeypatch):
    light_reg = _make_register("light.kitchen", "light_state", "state")
    fan_reg = _make_register("fan.living", "fan_pct", "percentage")
    sensor_reg = _make_register("sensor.temp", "temp_state", "state")
    broken_reg = _make_register("sensor.broken", "broken_state", "state")

    iface = Interface()

    registers = [light_reg, fan_reg, sensor_reg, broken_reg]

    def fake_get_regs(byte_type, read_only):
        # return all registers regardless of read_only for simplicity
        return registers

    monkeypatch.setattr(iface, "get_registers_by_type", fake_get_regs)

    def fake_get_entity_data(entity_id):
        if entity_id == "light.kitchen":
            return {"state": "on", "attributes": {}}
        if entity_id == "fan.living":
            return {"state": "off", "attributes": {"percentage": 40}}
        if entity_id == "sensor.temp":
            return {"state": "ok", "attributes": {"unit": "C"}}
        if entity_id == "sensor.broken":
            raise Exception("boom")
        return {}

    monkeypatch.setattr(iface, "get_entity_data", fake_get_entity_data)

    result = iface._scrape_all()

    # light mapped to ON, fan percentage captured, sensor uses default path, broken omitted
    assert result["light_state"] == DeviceState.ON
    assert result["fan_pct"] == 40
    assert result["temp_state"] == "ok"
    assert "broken_state" not in result
