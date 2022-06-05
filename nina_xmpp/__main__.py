import asyncio
import logging
import logging.handlers

from argparse_logging import add_log_level_argument, LoggingAction

from . import NinaXMPP


class LogHandler(LoggingAction):
    def configure(self, path):
        if path:
            logging.getLogger().addHandler(
                logging.handlers.SysLogHandler(address=path)
            )


def add_log_handler_argument(parser, option_string="--syslog"):
    return parser.add_argument(
        option_string,
        help="Enable logging to syslog at given address",
        metavar="ADDRESS",
        type=str,
        action=LogHandler,
    )


def main():
    import yaml
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('config_file', type=argparse.FileType('r'))
    add_log_level_argument(parser)
    add_log_handler_argument(parser)
    args = parser.parse_args()

    config = yaml.safe_load(args.config_file)
    args.config_file.close()

    main = NinaXMPP(config)

    asyncio.run(main.run())


if __name__ == '__main__':
    main()
