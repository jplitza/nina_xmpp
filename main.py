#!/usr/bin/python3

import asyncio
import html
import logging
import re
import signal
from typing import NamedTuple

import aioxmpp
import aioxmpp.dispatcher
import httpx
from shapely.geometry import Point, Polygon, MultiPolygon


def strip_html(text):
    return html.unescape(re.sub('<[^<]+?>', '', text))


class Registration(NamedTuple):
    jid: aioxmpp.JID
    point: Point = None
    area: str = ''

    def is_in_area(self, area):
        if self.area:
            return self.area in area['areaDesc']
        elif self.point:
            return self.point.within(area['multipolygon'])
        else:
            return False


class NinaXMPP:
    def __init__(self, config):
        self.config = config
        self.feed_cache = {}
        self.registrations = set()
        self.seen_identifiers = set()
        self.logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        self.client = aioxmpp.PresenceManagedClient(
            aioxmpp.JID.fromstr(self.config['xmpp']['jid']),
            aioxmpp.make_security_layer(self.config['xmpp']['password']),
        )

        async with self.client.connected():
            message_dispatcher = self.client.summon(
                aioxmpp.dispatcher.SimpleMessageDispatcher
            )
            message_dispatcher.register_callback(
                aioxmpp.MessageType.CHAT,
                None,
                self.message_received,
            )
            await self.update_feeds()
            await self.make_sigint_event().wait()

    def schedule_update_feeds(self):
        asyncio.get_event_loop().call_later(
            self.config['check_interval'],
            self.update_feeds,
        )

    def make_sigint_event(self):
        event = asyncio.Event()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(
            signal.SIGINT,
            event.set,
        )
        return event

    def message_received(self, msg):
        cmds = ['register', 'unregister']
        if not msg.body:
            return

        body = msg.body.any()
        for cmd in cmds:
            if body == cmd or body.startswith(cmd + ' '):
                getattr(self, cmd)(msg.from_, body[len(cmd) + 1:])
                return

    async def update_feeds(self):
        self.schedule_update_feeds()

        async with httpx.AsyncClient() as http_client:
            for feed in self.config['feeds']:
                try:
                    cached_headers = self.feed_cache[feed].headers
                except KeyError:
                    headers = {}
                else:
                    headers = {
                        'If-Modified-Since': cached_headers['Last-Modified'],
                        'If-None-Match': cached_headers['ETag'],
                    }
                response = await http_client.get(feed, headers=headers)

                if response.status_code == httpx.codes.OK:
                    self.feed_cache[feed] = response
                    self.send_updates_for_feed(feed)

    def send_updates_for_feed(self, feed):
        for event in self.feed_cache[feed].json():
            if event['identifier'] not in self.seen_identifiers:
                self.send_updates_for_event(event)
                self.seen_identifiers.add(event['identifier'])

    def send_updates_for_event(self, event):
        for area in event['info'][0]['area']:
            # convert string polygons to shapely MultiPolygon
            try:
                area['multipolygon'] = MultiPolygon(
                    Polygon(
                        list(map(float, point.split(',', 1)))
                        for point in polygon.split(' ')
                    )
                    for polygon in area['polygon']
                )
            except ValueError:
                self.logger.info(
                    'Event %s has invalid polygon',
                    event['identifier'],
                )

        for registration in self.registrations:
            for area in event['info'][0]['area']:
                if registration.is_in_area(area):
                    self.send_update(registration.jid, event)
                    break  # into registrations loop

    def send_update(self, jid, event):
        msg = aioxmpp.Message(
            to=jid,
            type_=aioxmpp.MessageType.CHAT,
        )
        msg.body[None] = '\n'.join(map(strip_html, (
            event['info'][0]['headline'],
            event['info'][0]['description'],
        )))
        self.client.enqueue(msg)

    @staticmethod
    def _area_to_registration(jid, area):
        coords = re.match(r'^(\d+\.\d+),\s*(\d+\.\d+)$', area)
        if coords:
            return Registration(
                jid=jid.bare(),
                point=Point(float(coords[1]), float(coords[2])),
            )
        else:
            return Registration(
                jid=jid.bare(),
                area=area,
            )

    def register(self, jid, area):
        registration = self._area_to_registration(jid, area)
        self.logger.debug('Adding registration %r', registration)
        self.registrations.add(registration)

        msg = aioxmpp.Message(
            to=jid,
            type_=aioxmpp.MessageType.CHAT,
        )
        msg.body[None] = "Successfully registered to area {}".format(area)
        self.client.enqueue(msg)

    def unregister(self, jid, area):
        msg = aioxmpp.Message(
            to=jid,
            type_=aioxmpp.MessageType.CHAT,
        )
        registration = self._area_to_registration(jid, area)
        self.logger.debug('Adding registration %r', registration)
        try:
            self.registrations.remove(registration)
        except KeyError:
            body = "Not registered to area {}"
        else:
            body = "Successfully unregistered from area {}"

        msg.body[None] = body.format(area)
        self.client.enqueue(msg)


if __name__ == '__main__':
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
