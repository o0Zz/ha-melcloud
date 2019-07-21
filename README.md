# HomeAssistant - MelCloud

Add to home assistant support for mitsubishi air conditioner (MELCloud)

## Installing

- Create a new folder in your home assistant : <config_dir>/custom_components/melcloud/
- Copy everything from GIT/custom_components/melcloud/ to your local folder <config_dir>/custom_components/melcloud/

Edit configuration.yaml and add below lines:
	
	climate:
		-platform: melcloud
		email: MY_EMAIL@gmail.com
		password: MY_PASSWORD

## License

This project is licensed under the WTF License