import asyncio
import logging
import signal

import aioxmpp
import aioxmpp.dispatcher
import httpx
from shapely.geometry import Polygon, MultiPolygon
from geoalchemy2.shape import to_shape, from_shape
from sqlalchemy.orm.exc import NoResultFound

from .db import Event, Feed, Registration, initialize as init_db
from .html import strip_html
from .helper import parse_area, deref_multi


class NinaXMPP:
    commands = ('register', 'unregister', 'list', 'help')

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = init_db(config['database'])

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
            update_feeds_task = asyncio.create_task(self.update_feeds_task())
            await self.make_sigint_event().wait()
            update_feeds_task.cancel()

        try:
            await update_feeds_task
        except asyncio.CancelledError:
            pass

    def make_sigint_event(self):
        event = asyncio.Event()
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(
            signal.SIGINT,
            event.set,
        )
        return event

    def message_received(self, msg):
        if not msg.body:
            return

        reply = aioxmpp.Message(
            to=msg.from_,
            type_=aioxmpp.MessageType.CHAT,
        )

        body = msg.body.any()
        for cmd in self.commands:
            if body == cmd or body.startswith(cmd + ' '):
                reply.body[None] = getattr(self, cmd)(
                    str(msg.from_.bare()),
                    body[len(cmd) + 1:],
                )
                self.client.enqueue(reply)
                return

    async def update_feeds_task(self):
        self.logger.debug('Started update feeds task')
        while True:
            await self.update_feeds()
            self.logger.debug(
                'Finished updating feeds, sleeping for '
                f'{self.config["check_interval"]}s'
            )
            await asyncio.sleep(self.config['check_interval'])

    async def update_feeds(self):
        async with httpx.AsyncClient(trust_env=False) as http_client:
            for url in self.config['feeds']:
                try:
                    feed = self.db.query(Feed).filter_by(url=url).one()
                except NoResultFound:
                    self.logger.info(f'Updating feed {url} for the first time')
                    feed = Feed(url=url)
                    headers = {}
                else:
                    self.logger.info(
                        f'Updating feed {url} (last modified: {feed.last_modified}'
                    )
                    headers = {
                        'If-Modified-Since': feed.last_modified,
                        'If-None-Match': feed.etag,
                    }
                response = await http_client.get(url, headers=headers)

                if response.status_code == httpx.codes.OK:
                    feed.last_modified = response.headers['Last-Modified']
                    feed.etag = response.headers['ETag']
                    self.db.add(feed)
                    self.send_updates_for_feed(response.json())

        self.db.commit()

    def send_updates_for_feed(self, feed):
        for event in feed:
            if not self.db.query(Event).filter_by(id=event['identifier']).one_or_none():
                self.logger.debug(f'Found new event {event["identifier"]}')
                self.send_updates_for_event(event)
                self.db.add(Event(id=event['identifier']))

    def send_updates_for_event(self, event):
        for area in event['info'][0]['area']:
            # convert string polygons to shapely MultiPolygon
            try:
                area['multipolygon'] = MultiPolygon(
                    Polygon(
                        list(map(float, point.split(',', 1)))
                        for point in polygon.split(' ')
                        if point != '-1.0,-1.0'
                    )
                    for polygon in area['polygon']
                    if ' ' in polygon
                )
            except ValueError:
                self.logger.warn(
                    'Event %s has invalid polygon',
                    event['identifier'],
                )
                return

        for area in event['info'][0]['area']:
            jid_query = self.db.query(Registration.jid).filter(
                Registration.point.ST_Within(from_shape(area['multipolygon']))
            )
            for jid, in jid_query:
                self.logger.debug(
                    'Event %s matched for JID %s',
                    event['identifier'],
                    jid,
                )
                self.send_update(aioxmpp.JID.fromstr(jid), event)

    def send_update(self, jid, event):
        msg = aioxmpp.Message(
            to=jid,
            type_=aioxmpp.MessageType.CHAT,
        )
        msg.body[None] = '\n'.join(filter(None, [
            strip_html(deref_multi(event['info'][0], x) or '') for x in (
                ['headline'],
                ['description'],
                ['instruction'],
                ['area', 0, 'areaDesc'],
                ['effective'],
                ['expires']
            )
        ]))
        self.client.enqueue(msg)

    def register(self, jid, area):
        'Register to messages regarding a coordinate'

        if not area:
            return 'No coordinates given'

        try:
            point = parse_area(area)
        except (TypeError, ValueError):
            return 'Invalid coordinates: {}'.format(area)
        else:
            self.db.add(Registration(
                jid=jid,
                point=str(point),
            ))
            self.db.commit()

            return 'Successfully registered to coordinates {0.y} {0.x}'.format(point)

    def unregister(self, jid, area):
        'Unregister from messages regarding a coordinate'

        if not area:
            return 'No coordinates given'

        try:
            point = parse_area(area)
        except (TypeError, ValueError):
            return 'Invalid coordinates: {}'.format(area)
        else:
            try:
                registration = self.db.query(Registration).filter_by(
                    jid=jid,
                    point=str(point),
                ).one()
            except NoResultFound:
                return 'Not registered to coordinates {0.y}, {0.x}'.format(point)
            else:
                self.db.delete(registration)
                self.db.commit()
                return 'Successfully unregistered from coordinates {0.y}, {0.x}'.format(point)

    def list(self, jid, _):
        'List active registrations'

        return '\n'.join(
            '{0.y}, {0.x}'.format(to_shape(point))
            for point,
            in self.db.query(Registration.point).filter_by(jid=jid)
        ) or 'No active registrations.'

    def help(self, jid, _):
        'Show available commands'

        cmds = [(cmd, getattr(self, cmd).__doc__) for cmd in self.commands]
        return '\n'.join(f'{cmd}\n    {doc}' for cmd, doc in cmds)
