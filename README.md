# NINA XMPP bot

XMPP bot that sends messages from the German NINA official warning app.

Checks the official JSON files every once in a while (configurable in the config
file) for changes and sends new warnings to registered users based on the
coordinates the entered.

## Install

(tested on Linux Mint 20.2)

1. Clone the repository

`git clone https://github.com/jplitza/nina_xmpp.git`

2. Install dependencies

`sudo pip3 install aioxmpp httpx shapely geoalchemy2 argparse_logging

sudo apt-get install libsqlite3-mod-spatialite
`

3. Build

`python3 setup.py build`

4. Configure

adapt config.yml to your needs

`cp config.sample.yml config.yml`

5. Run

`nina_xmpp config.yml`

## Usage

Chat with the JID specified in the config to register yourself for warnings:

```
< help
> register
>     Register to messages regarding a coordinate
> unregister
>     Unregister from messages regarding a coordinate
> list
>     List active registrations
> help
>     Show available commands

< list
> No active registrations.

< register 52.51704, 13.38792
> Successfully registered to coordinates 52.51704, 13.38792
```

Now you will receive warnings for the center of Berlin when they happen.

You can register to multiple coordinates.

## Hosted instance

If you don't want to host this yourself, feel free to use my instance at
`nina@litza.de` - no warrenties whatsoever.
