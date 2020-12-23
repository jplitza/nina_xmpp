import asyncio

from . import NinaXMPP


def main():
    import yaml
    import argparse
    from argparse_logging import add_log_level_argument

    parser = argparse.ArgumentParser()
    parser.add_argument('config_file', type=argparse.FileType('r'))
    add_log_level_argument(parser)
    args = parser.parse_args()

    config = yaml.safe_load(args.config_file)
    args.config_file.close()

    main = NinaXMPP(config)

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main.run())
    finally:
        loop.close()


if __name__ == '__main__':
    main()
