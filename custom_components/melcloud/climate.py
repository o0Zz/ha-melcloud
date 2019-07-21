#!/usr/local/bin/python3

"""
    Author: o0Zz

    ChangeLog:
        Version 1.0: Initial release
    
    Documentation:
        Reverse: http://mgeek.fr/blog/un-peu-de-reverse-engineering-sur-melcloud
        HA climate example: https://github.com/home-assistant/home-assistant/blob/dev/homeassistant/components/climate/demo.py
    
    How to install:
        Copy this file in <config_dir>/custom_components/melcloud/climate.py
        Edit configuration.yaml and add below lines:
        
            climate:
                -platform: melcloud
                email: MY_EMAIL@gmail.com
                password: MY_PASSWORD

        Edit customization.yaml to provide a name to your climate devices.
    
    How to enable logs:
    
            logger:
                default: info
                logs:
                    custom_components.melcloud.climate: debug
    
    Workflow:
        During startup the script will try to login on your account (Email/password)
        If the login step fail, the setup will also fail and this components will be unload by HomeAssistant
        Once login succeeded, we will download the list of all devices available on your melcloud account (This step is done everytime this component is loaded)
        We don't cache any data to be as synchronized as possible, so, on every HomeAssistant startup we will re-download the list and get the most up to date device list.
        Thus, If you want to add a new climate to your HomeAssistant, just restart it.
        
        Once we successfully login, we will retrive the "contextKey" and we will use this auth to all our requests
        If an error 401 occured, it means contextKey has expired, in this case we will re-login
        If any other error occured, we will abort.
    
    License:
                DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE 
                        Version 2, December 2004
        
        Everyone is permitted to copy and distribute verbatim or modified
        copies of this license document, and changing it is allowed as long
        as the name is changed.
                  
                  DO WHAT THE FUCK YOU WANT TO PUBLIC LICENSE
          TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION
          
         0. You just DO WHAT THE FUCK YOU WANT TO.
"""

import requests
import sys
import logging
import time
import json

#TODO: 
# FOLLOW HOME ASSISTANT GUIDLINE
# - Use keep alive to avoid too many reconnection
#   s = requests.Session()
#   s.get(), s.post() instead of requests.get

_LOGGER = logging.getLogger(__name__)

import voluptuous as vol
from homeassistant.components.climate import ClimateDevice, PLATFORM_SCHEMA
from homeassistant.components.climate.const import SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE, SUPPORT_SWING_MODE
from homeassistant.components.climate.const import ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW
from homeassistant.components.climate.const import HVAC_MODE_AUTO, HVAC_MODE_OFF, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY
from homeassistant.const import CONF_PASSWORD, CONF_EMAIL, TEMP_CELSIUS, ATTR_TEMPERATURE
import homeassistant.helpers.config_validation as cv

#class ClimateDevice:
#    pass

# ---------------------------------------------------------------

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_EMAIL): cv.string
})

# ---------------------------------------------------------------

class Language:
    English = 0
    German = 4
    Spanish = 6
    French = 7
    Italian = 19
    
# ---------------------------------------------------------------

class Mode:
    Heat = 1
    Dry = 2
    Cool = 3
    Fan = 7
    Auto = 8

# ---------------------------------------------------------------

class VentilationMode:
    EnergyRecovery = 0
    ByPass = 1
    Auto = 2

# ---------------------------------------------------------------

class DeviceType:
    Conditioner = 0
    Vent = 3

# ---------------------------------------------------------------

class MelCloudAuthentication:
    def __init__(self, email, password, language = Language.English):
        self._email = email
        self._password = password
        self._language = language
        self._contextkey = None

    def isLogin(self):
        return self._contextkey != None
        
    def login(self):
        _LOGGER.debug("Login ...")

        self._contextkey = None
        
        req = requests.post("https://app.melcloud.com/Mitsubishi.Wifi.Client/Login/ClientLogin", data={"Email": self._email ,"Password": self._password, "Language": self._language, "AppVersion": "1.15.3.0", "Persist": False})
        
        if req.status_code == 200:
            reply = req.json()
            if "ErrorId" in reply and reply["ErrorId"] == None:
                self._contextkey = reply["LoginData"]["ContextKey"]
                return True
            else:
                _LOGGER.error("Login/Password invalid ! ")

        else:
            _LOGGER.error("Login status code invalid: " + str(req.status_code))

        return False
        
    def getContextKey(self):
        return self._contextkey
        
    def sendReq(self, method, url, data = None, retry = 0):
        if retry > 1:
            return False, None
        
        req = requests.request(method, url, headers = {'X-MitsContextKey': self.getContextKey()}, data = data)
        
        if req.status_code == 200:
            # _LOGGER.debug(json.dumps(req.json()))
            return True, req.json()
            
        elif req.status_code == 401:
            _LOGGER.error("Unable to URL: '" + str(url) + "', error 401 (Try to re-login...)")
            if self.login():
                return self.sendReq(method, url, data, retry + 1)
        else:
            _LOGGER.error("Unable to retrieve information from URL: '" + str(url) + "' (Invalid status code: " + str(req.status_code) + ")")

        return False
        
# ---------------------------------------------------------------

class MelCloudDevice:

    def __init__(self, deviceid, buildingid, friendlyname, authentication):
        self._deviceid = deviceid
        self._buildingid = buildingid
        self._friendlyname = friendlyname
        self._authentication = authentication
        self._info_lease_seconds = 60 #Data stay valid during 60s, after that we refresh it
        self._json = None
        self._temp_list = []
    
        self._refresh_device_info()
            
    def __str__(self):
        return str(self._json)
        #return "Name: " + self._friendlyname + " ID: " + str(self._deviceid) + " BuildingID: " + str(self._buildingid)
        #return "Temp: " + str(self.getTemperature()) + ", RoomTemp: " + str(self.getRoomTemperature()) + ", FanSpeed: " + str(self.getFanSpeed()) + ", Mode: " + str(self.getMode()) + ", PowerOn: " + str(self.isPowerOn()) + ", Online: " + str(self.isOnline())

    def _refresh_device_info(self):
        self._json = None
        self._last_info_time_s = time.time()

        success, json = self._authentication.sendReq("GET", "https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/Get", data = {'id': self._deviceid, 'buildingID': self._buildingid})
        
        if success:
            self._json = json

            if "RoomTemperature" in self._json:
                self._temp_list.append(self._json["RoomTemperature"])
                self._temp_list = self._temp_list[-10:] #Keep only last 10 temperature

            return True

        return False
    
    def _get_info(self, key, default_value):
        if not self._is_info_valid():
            return default_value
        
        if key not in self._json:
            return default_value
        
        return self._json[key]
    
    def _is_info_valid(self):
        if self._json == None:
            return self._refresh_device_info()
        
        if (time.time() - self._last_info_time_s) >= self._info_lease_seconds:
            _LOGGER.info("Device info lease timeout, refreshing...")
            return self._refresh_device_info()
            
        return True
        
    def apply(self):
        if self._json == None:
            _LOGGER.error("Unable to apply device configuration !")
            return False

        #EffectiveFlags:
        #Power:                0x01
        #OperationMode:        0x02
        #Temperature:        0x04
        #FanSpeed:            0x08
        #VaneVertical:        0x10
        #VaneHorizontal:    0x100
        #Signal melcloud we want to change everything (Even if it't not true, by this way we make sure the configuration is complete)
        self._json["EffectiveFlags"] = 0x1F
        self._json["HasPendingCommand"] = True

        set_api = "SetAta"
        if self._json["DeviceType"] == DeviceType.Vent:
            set_api = "SetErv"
            
        success, json = self._authentication.sendReq("POST", "https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/" + set_api, data = self._json)
        return success

    def getID(self):
        return self._deviceid
        
    def getFriendlyName(self):
        return self._friendlyname

    def getDeviceType(self):
        return self._json["DeviceType"]

    def getTemperature(self):
        return self._get_info("SetTemperature", None)

    def getRoomTemperature(self):
        if not self._is_info_valid():
            return 0
                    
        if len(self._temp_list) == 0:
            return 0 #Avoid div 0
        
        return round((sum(self._temp_list) / len(self._temp_list)), 1)
    
    def getFanSpeedMax(self):
        return self._get_info("NumberOfFanSpeeds", None)
    
    def getFanSpeed(self): #0 Auto, 1 to NumberOfFanSpeeds
        return self._get_info("SetFanSpeed", None)
    
    def getVerticalSwingMode(self): #0 Auto, 1 to NumberOfVane, +1 Swing
        return self._get_info("VaneVertical", None)

    def getHorizontalSwingMode(self): #0 Auto, 1 to NumberOfVane, +1 Swing
        return self._get_info("VaneHorizontal", None)
        
    def getMode(self):
        return self._get_info("OperationMode", Mode.Auto)

    def getVentMode(self):
        return self._get_info("VentilationMode", VentilationMode.Auto)

    def isPowerOn(self): #boolean
        return self._get_info("Power", False)

    def isOnline(self): #boolean
        return self._get_info("Offline", False)

    def setVerticalSwingMode(self, swingMode):
        if not self._is_info_valid():
            _LOGGER.error("Unable to set swing mode: " + str(swingMode))
            return False
            
        self._json["VaneVertical"] = swingMode
        return True

    def setHorizontalSwingMode(self, swingMode):
        if not self._is_info_valid():
            _LOGGER.error("Unable to set swing mode: " + str(swingMode))
            return False
            
        self._json["VaneHorizontal"] = swingMode
        return True

        
    def setTemperature(self, temperature):
        if not self._is_info_valid():
            _LOGGER.error("Unable to set temperature: " + str(temperature))
            return False
            
        self._json["SetTemperature"] = temperature
        return True

    def setFanSpeed(self, speed): #0 Auto, 1 to NumberOfFanSpeeds
        if not self._is_info_valid():
            _LOGGER.error("Unable to set fan speed: " + str(speed))
            return False
            
        self._json["SetFanSpeed"] = speed
        return True
        
    def setMode(self, mode):
        if not self._is_info_valid():
            _LOGGER.error("Unable to set mode: " + str(mode))
            return
            
        self._json["OperationMode"] = mode

    def setVentMode(self, mode):
        if not self._is_info_valid():
            _LOGGER.error("Unable to set mode: " + str(mode))
            return

        self._json["VentilationMode"] = mode

    def powerOn(self):
        if not self._is_info_valid():
            _LOGGER.error("Unable to powerOn")
            return False
            
        self._json["Power"] = True
        return True
        
    def powerOff(self):
        if not self._is_info_valid():
            _LOGGER.error("Unable to powerOff")
            return False
            
        self._json["Power"] = False
        return True

# ---------------------------------------------------------------

class MelCloud:
    def __init__(self, authentication):
        self._authentication = authentication
        
    def getDevicesList(self):
        devices = []
        
        success, json = self._authentication.sendReq("GET", "https://app.melcloud.com/Mitsubishi.Wifi.Client/User/ListDevices")
        if success:
            #_LOGGER.debug(json)
            for entry in json:
            
                #Flat devices
                for device in entry["Structure"]["Devices"]:
                    devices.append( MelCloudDevice(device["DeviceID"], device["BuildingID"], device["DeviceName"], self._authentication) )
                
                #Areas devices
                for areas in entry["Structure"]["Areas"]:
                    for device in areas["Devices"]:
                        devices.append( MelCloudDevice(device["DeviceID"], device["BuildingID"], device["DeviceName"], self._authentication) )
                
                #Floor devices
                for floor in entry["Structure"]["Floors"]:
                    for device in floor["Devices"]:
                        devices.append( MelCloudDevice(device["DeviceID"], device["BuildingID"], device["DeviceName"], self._authentication) )
                    
                    for areas in floor["Areas"]:
                        for device in areas["Devices"]:
                            devices.append( MelCloudDevice(device["DeviceID"], device["BuildingID"], device["DeviceName"], self._authentication) )

        return devices

# ---------------------------------------------------------------

VENT_MODE_ENERGY_RECOVERY = 'energy_recovery'
VENT_MODE_BY_PASS = 'bypass'
VENT_MODE_AUTO = 'auto'
MIN_TEMP = 16
MAX_TEMP = 30

class MelCloudClimate(ClimateDevice):

    def __init__(self, device):
        self._device = device
        
        self._fan_modes = ['Speed Auto', 'Speed 1 (Min)']
        for i in range(2, self._device.getFanSpeedMax()):
            self._fan_modes.append('Speed ' + str(i))
        self._fan_modes.append('Speed ' + str(self._device.getFanSpeedMax()) + " (Max)")
        
        self._swing_modes = ['Auto', 'Top', 'MiddleTop', 'Middle', 'MiddleBottom', 'Bottom', 'Swing']
        self._swing_id = [0, 1, 2, 3, 4, 5, 7]
        
    @property
    def supported_features(self):
        return (SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE | SUPPORT_SWING_MODE)

    @property
    def should_poll(self):
        return True

    def update(self):
        self._device._refresh_device_info()

    @property
    def name(self):
        return "MELCloud " + self._device.getFriendlyName() + " (" + str(self._device.getID()) + ")"

    @property
    def temperature_unit(self):
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        return self._device.getRoomTemperature()

    @property
    def target_temperature(self):
        return self._device.getTemperature()

    @property
    def hvac_mode(self):
        if not self._device.isPowerOn():
            return HVAC_MODE_OFF
            
        if self._device.getDeviceType() == DeviceType.Conditioner:
            if self._device.getMode() == Mode.Heat:
                return HVAC_MODE_HEAT
            elif self._device.getMode() == Mode.Cool:
                return HVAC_MODE_COOL
            elif self._device.getMode() == Mode.Dry:
                return OPERATION_DRY_STR
            elif self._device.getMode() == Mode.Fan:
                return OPERATION_FAN_STR
            elif self._device.getMode() == Mode.Auto:
                return HVAC_MODE_AUTO
                
        elif self._device.getDeviceType() == DeviceType.Vent:
            if self._device.getVentMode() == VentilationMode.EnergyRecovery:
                return VENT_MODE_ENERGY_RECOVERY
            elif self._device.getVentMode() == VentilationMode.ByPass:
                return VENT_MODE_BY_PASS
            elif self._device.getVentMode() == VentilationMode.Auto:
                return VENT_MODE_AUTO
                
        return "" #Unknown

    @property
    def hvac_modes(self):
        if self._device.getDeviceType() == DeviceType.Conditioner:
            return [HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_AUTO, HVAC_MODE_OFF]
        elif self._device.getDeviceType() == DeviceType.Vent:
            return [VENT_MODE_ENERGY_RECOVERY, VENT_MODE_BY_PASS, VENT_MODE_AUTO]

    def set_hvac_mode(self, operation_mode):
        if operation_mode == HVAC_MODE_OFF:
            self._device.powerOff()
        elif self._device.getDeviceType() == DeviceType.Conditioner:
            self._device.powerOn()
            if operation_mode == HVAC_MODE_HEAT:
                self._device.setMode(Mode.Heat)
            elif operation_mode == OPERATION_COOL_STR:
                self._device.setMode(Mode.Cool)
            elif operation_mode == OPERATION_DRY_STR:
                self._device.setMode(Mode.Dry)
            elif operation_mode == OPERATION_FAN_STR:
                self._device.setMode(Mode.Fan)
            elif operation_mode == HVAC_MODE_AUTO:
                self._device.setMode(Mode.Auto)
        elif self._device.getDeviceType() == DeviceType.Vent:
            self._device.powerOn()
            if operation_mode == VENT_OPERATION_ENERGY_SAVING_STR:
                self._device.setVentMode(VentilationMode.EnergyRecovery)
            elif operation_mode == VENT_OPERATION_BY_PASS_STR:
                self._device.setVentMode(VentilationMode.ByPass)
            elif operation_mode == HVAC_MODE_AUTO:
                self._device.setVentMode(VentilationMode.Auto)

        self._device.apply()
        self.schedule_update_ha_state()

    @property
    def fan_mode(self):
        if self._device.getFanSpeed() >= len(self._fan_modes):
            return self._fan_modes[0]
            
        return self._fan_modes[self._device.getFanSpeed()]
        
    @property
    def fan_modes(self):
        return self._fan_modes

    def set_fan_mode(self, fan_mode):
        for i in range(0, len(self._fan_modes)):
            if fan_mode == self._fan_modes[i]:
                self._device.setFanSpeed(i)
                self._device.apply()
                break
                
        self.schedule_update_ha_state()

    @property
    def swing_mode(self):
        for i in range(0, len(self._swing_id)):
            if self._device.getVerticalSwingMode() == self._swing_id[i]:
                return self._swing_modes[i]
                
        return self._swing_modes[0] #Auto

    def set_swing_mode(self, swing_mode):
        for i in range(0, len(self._swing_modes)):
            if swing_mode == self._swing_modes[i]:
                self._device.setVerticalSwingMode(self._swing_id[i])
                self._device.apply()
                break
                
        self.schedule_update_ha_state()

    @property
    def swing_modes(self):
        return self._swing_modes
        
    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return MIN_TEMP

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return MAX_TEMP

    def set_temperature(self, **kwargs):
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            self._device.setTemperature(kwargs.get(ATTR_TEMPERATURE))
            self._device.apply()
            
        self.schedule_update_ha_state()

    def turn_on(self):
        self._device.powerOn()
        self._device.apply()
        self.schedule_update_ha_state()

    def turn_off(self):
        self._device.powerOff()
        self._device.apply()
        self.schedule_update_ha_state()

# ---------------------------------------------------------------

def setup_platform(hass, config, add_devices, discovery_info=None):
    _LOGGER.debug("Adding component: melcloud ...")

    email = config.get(CONF_EMAIL)
    password = config.get(CONF_PASSWORD)
    language = config.get("language", Language.English)

    if email is None:
        _LOGGER.error("melcloud: Invalid email !")
        return False
        
    if password is None:
        _LOGGER.error("melcloud: Invalid password !")
        return False

    mcauth = MelCloudAuthentication(email, password, language)
    if mcauth.login() == False:
        _LOGGER.error("melcloud: Invalid Login/Password  !")
        return False
        
    mc = MelCloud(mcauth)
    
    device_list = []
    
    devices = mc.getDevicesList()
    for device in devices:
        _LOGGER.debug("melcloud: Adding new device: " + device.getFriendlyName())
        device_list.append( MelCloudClimate(device) )
    
    add_devices(device_list)
    
    _LOGGER.debug("melcloud: Component successfully added ! (" + str(len(device_list)) + " device(s) found !)")
    return True

# ---------------------------------------------------------------

if __name__ == '__main__':

    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    if len(sys.argv) < 3:
        print ("Usage: " + sys.argv[0] + " <email> <password>")
        sys.exit(1)

    mcauth = MelCloudAuthentication(sys.argv[1], sys.argv[2])
    if mcauth.login() == False:
        print("Invalid Login/Password  !")
        sys.exit(1)
    
    #mcauth._contextkey = "000000000000000"
    mc = MelCloud(mcauth)
    
    devices = mc.getDevicesList()
    for device in  devices:
        print (device)
        #device.powerOff()
        #device.apply() 

