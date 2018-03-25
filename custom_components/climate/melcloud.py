#!/usr/local/bin/python3

"""
	Author: o0Zz

	ChangeLog:
		Version 1.0: Initial release
	
	Documentation:
		Reverse: http://mgeek.fr/blog/un-peu-de-reverse-engineering-sur-melcloud
		HA climate example: https://github.com/home-assistant/home-assistant/blob/dev/homeassistant/components/climate/demo.py
	
	How to install:
		Copy this file in <config_dir>/custom_components/climate/melcloud.py
		Edit configuration.yaml and add below lines:
		
			climate:
				-platform: melcloud
				email: MY_EMAIL@gmail.com
				password: MY_PASSWORD

		Edit customization.yaml to provide a name to your climate devices.
	
	How to enable logs:
	
			logger:
				default: critical
				logs:
					homeassistant.components.climate.melcloud: debug
	
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

import requests, sys, os, logging, time

#TODO: 
# - Use keep alive to avoid too many reconnection
#	s = requests.Session()
#   s.get(), s.post() instead of requests.get
#
# - Move Post/Get methods in MelCloudAuthentication to centralize error 401

_LOGGER = logging.getLogger(__name__)

try:
	from homeassistant.components.climate import (ClimateDevice, SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE, SUPPORT_OPERATION_MODE, SUPPORT_ON_OFF)
	from homeassistant.const import TEMP_CELSIUS, TEMP_FAHRENHEIT, ATTR_TEMPERATURE
	from homeassistant.helpers.discovery import load_platform
except:
		#Used for standalone runtime (Without HomeAssistant) - Mainly used for debugging purpose
	logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
	class ClimateDevice:
		pass
	
DOMAIN = 'melcloud'
REQUIREMENTS = ['requests']
DEPENDENCIES = []

if sys.version_info[0] < 3:
	raise Exception("Python 3 or a more recent version is required.")
	
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
	
# ---------------------------------------------------------------

class MelCloudDevice:

	def __init__(self, deviceid, buildingid, friendlyname, authentication):
		self._deviceid = deviceid
		self._buildingid = buildingid
		self._friendlyname = friendlyname
		self._authentication = authentication
		self._info_lease_seconds = 60 #Data stay valid during 60s, after that we refresh it
		self._json = None
		self._refresh_device_info()
			
	def __str__(self):
		return str(self._json)
		#return "Name: " + self._friendlyname + " ID: " + str(self._deviceid) + " BuildingID: " + str(self._buildingid)
		#return "Temp: " + str(self.getTemperature()) + ", RoomTemp: " + str(self.getRoomTemperature()) + ", FanSpeed: " + str(self.getFanSpeed()) + ", Mode: " + str(self.getMode()) + ", PowerOn: " + str(self.isPowerOn()) + ", Online: " + str(self.isOnline())

	def _refresh_device_info(self, recursive = 0):
		self._json = None
		self._last_info_time_s = time.time()
		
		if recursive > 1:
			return False
		
		req = requests.get("https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/Get", headers = {'X-MitsContextKey': self._authentication.getContextKey()}, data = {'id': self._deviceid, 'buildingID': self._buildingid})
		
		if req.status_code == 200:
			self._json = req.json()
			return True
		elif req.status_code == 401:
			_LOGGER.error("Device information error 401 (Try to re-login...)")
			if self._authentication.login():
				return self._retrieve_device_info(recursive + 1)
		else:
			_LOGGER.error("Unable to retrieve device information (Invalid status code: " + str(req.status_code) + ")")

		return False
		
	def _is_info_valid(self):
		if self._json == None:
			return self._refresh_device_info()
		
		if (time.time() - self._last_info_time_s) >= self._info_lease_seconds:
			_LOGGER.info("Device info lease timeout, refreshing...")
			return self._refresh_device_info()
			
		return True
		
	def apply(self, recursive = 0):
		if self._json == None:
			_LOGGER.error("Unable to apply device configuration !")
			return False

		if recursive > 1:
			return False

		#EffectiveFlags:
		#Power: 		0x01
		#OperationMode: 0x02
		#Temperature: 	0x04
		#FanSpeed: 		0x08
		
		#Signal melcloud we want to change everything (Even if it't not true, by this way we make sure the configuration is complete)
		self._json["EffectiveFlags"] = 0x0F
		self._json["HasPendingCommand"] = True
		
		req = requests.post("https://app.melcloud.com/Mitsubishi.Wifi.Client/Device/SetAta", headers = {'X-MitsContextKey': self._authentication.getContextKey()}, data = self._json)
		if req.status_code == 200:
			_LOGGER.info("Device configuration successfully applied")
			return True
		elif req.status_code == 401:
			_LOGGER.error("Apply device configuration error 401 (Try to re-login...)")
			if self._authentication.login():
				return self.apply(recursive + 1)
		else:
			_LOGGER.error("Unable to apply device configuration (Invalid status code: " + str(req.status_code) + ")")
			
		return False
	
	def getID(self):
		return self._deviceid
		
	def getFriendlyName(self):
		return self._friendlyname
		
	def getTemperature(self):
		if not self._is_info_valid():
			return 0
				
		return self._json["SetTemperature"]

	def getRoomTemperature(self):
		if not self._is_info_valid():
			return 0
				
		return self._json["RoomTemperature"]
	
	def getFanSpeedMax(self):
		if not self._is_info_valid():
			return 0
				
		return self._json["NumberOfFanSpeeds"]
	
	def getFanSpeed(self): #0 Auto, 1 to NumberOfFanSpeeds
		if not self._is_info_valid():
			return 0
				
		return self._json["SetFanSpeed"]
		
	def getMode(self):
		if not self._is_info_valid():
			return Mode.Auto
			
		return self._json["OperationMode"] #Return class Mode
	
	def isPowerOn(self): #boolean
		if not self._is_info_valid():
			return False
			
		return self._json["Power"]

	def isOnline(self): #boolean
		if not self._is_info_valid():
			return False
			
		return not self._json["Offline"]	
		
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
		
	def getDevicesList(self, recursive = 0):
		devices = []
		
		if recursive > 1:
			return devices

		req = requests.get("https://app.melcloud.com/Mitsubishi.Wifi.Client/User/ListDevices", headers = {'X-MitsContextKey': self._authentication.getContextKey()})
		if req.status_code == 200:
			reply = req.json()
			_LOGGER.debug(reply)
			for entry in reply:
			
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
					
		elif req.status_code == 401:
			_LOGGER.error("Get device list error 401 (Try to re-login...)")
			if self._authentication.login():
				return self.getDevicesList(recursive + 1)
		else:
			_LOGGER.error("Unable to retrieve device list (Status code invalid: " + str(req.status_code) + ")")

		return devices

# ---------------------------------------------------------------

OPERATION_HEAT_STR = 'Heat'
OPERATION_COOL_STR = 'Cool'
OPERATION_FAN_STR = 'Fan'
OPERATION_AUTO_STR = 'Auto'
OPERATION_OFF_STR = 'Off'
OPERATION_DRY_STR = 'Dry'

class MelCloudClimate(ClimateDevice):

	def __init__(self, device):
		self._device = device
		
		self._fan_list = ['Speed Auto', 'Speed 1 (Min)']
		for i in range(2, self._device.getFanSpeedMax()):
			self._fan_list.append('Speed ' + str(i))
		self._fan_list.append('Speed ' + str(self._device.getFanSpeedMax()) + " (Max)")
		
	@property
	def supported_features(self):
		return (SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE | SUPPORT_OPERATION_MODE | SUPPORT_ON_OFF)

	@property
	def should_poll(self):
		return True

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
	def current_operation(self):
		if not self._device.isPowerOn():
			return OPERATION_OFF_STR
		elif self._device.getMode() == Mode.Heat:
			return OPERATION_HEAT_STR
		elif self._device.getMode() == Mode.Cool:
			return OPERATION_COOL_STR
		elif self._device.getMode() == Mode.Dry:
			return OPERATION_DRY_STR
		elif self._device.getMode() == Mode.Fan:
			return OPERATION_FAN_STR
		elif self._device.getMode() == Mode.Auto:
			return OPERATION_AUTO_STR
		
		return "" #Unknown

	@property
	def operation_list(self):
		return [OPERATION_HEAT_STR, OPERATION_COOL_STR, OPERATION_DRY_STR, OPERATION_FAN_STR, OPERATION_AUTO_STR, OPERATION_OFF_STR]

	@property
	def is_on(self):
		return self._device.isPowerOn()

	@property
	def current_fan_mode(self):
		if self._device.getFanSpeed() >= len(self._fan_list):
			return self._fan_list[0]
			
		return self._fan_list[self._device.getFanSpeed()]
		
	@property
	def fan_list(self):
		return self._fan_list

	def set_temperature(self, **kwargs):
		if kwargs.get(ATTR_TEMPERATURE) is not None:
			self._device.setTemperature(kwargs.get(ATTR_TEMPERATURE))
			self._device.apply()
			
		self.schedule_update_ha_state()

	def set_fan_mode(self, fan_mode):
		for i in range(0, len(self._fan_list)):
			if fan_mode == self._fan_list[i]:
				self._device.setFanSpeed(i)
				self._device.apply()
				break
				
		self.schedule_update_ha_state()

	def set_operation_mode(self, operation_mode):
		if operation_mode == OPERATION_OFF_STR:
			self._device.powerOff()
		else:
			self._device.powerOn()
			if operation_mode == OPERATION_HEAT_STR:
				self._device.setMode(Mode.Heat)
			elif operation_mode == OPERATION_COOL_STR:
				self._device.setMode(Mode.Cool)
			elif operation_mode == OPERATION_DRY_STR:
				self._device.setMode(Mode.Dry)
			elif operation_mode == OPERATION_FAN_STR:
				self._device.setMode(Mode.Fan)
			elif operation_mode == OPERATION_AUTO_STR:
				self._device.setMode(Mode.Auto)

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
	
	email = config.get("email")
	password = config.get("password")
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
	
	_LOGGER.debug("melcloud: Component successfully added !")
	return True

# ---------------------------------------------------------------

if __name__ == '__main__':

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

