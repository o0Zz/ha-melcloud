# HomeAssistant - MelCloud

Add to home assistant support for mitsubishi air conditioner (MELCloud)

## Installing

- Create a folder in your home assistant <config_dir>/custom_components/melcloud/
- Copy melcloud.py in <config_dir>/custom_components/melcloud/climate.py


Edit configuration.yaml and add below lines:
	
	climate:
		-platform: melcloud
		email: MY_EMAIL@gmail.com
		password: MY_PASSWORD

## License

This project is licensed under the WTF License