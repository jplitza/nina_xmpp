# NINA XMPP bot

XMPP bot that sends messages from the German NINA official warning app.

Checks the official JSON files every once in a while (configurable in the config
file) for changes and sends new warnings to registered users based on the
coordinates the entered.

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
