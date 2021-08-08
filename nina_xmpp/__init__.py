import asyncio
import gettext
import logging
import math
import os
import signal

import aioxmpp
import aioxmpp.dispatcher
import httpx
from shapely.geometry import Polygon, MultiPolygon
from geoalchemy2.shape import to_shape, from_shape
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from .db import Event, Feed, Registration, initialize as init_db
from .html import strip_html
from .helper import parse_area, reformat_date


localedir = os.path.join(os.path.dirname(__file__), "locale")
translate = gettext.translation(__package__, localedir, fallback=True)
_ = translate.gettext

SQRT2 = math.sqrt(2)


class NinaXMPP:
    commands = ('register', 'unregister', 'feeds', 'list', 'help')

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
        cbody = body.casefold()
        for cmd in self.commands:
            ccmd = cmd.casefold()
            if cbody == ccmd or cbody.startswith(ccmd + ' '):
                reply.body[None] = getattr(self, cmd)(
                    str(msg.from_.bare()),
                    body[len(cmd) + 1:],
                )
                self.client.enqueue(reply)
                return
        else:
            reply.body[None] = _(
                'I did not understand your request. '
                'Type "help" for a list of available commands'
            )
            self.client.enqueue(reply)

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
                headers = {}
                try:
                    feed = self.db.query(Feed).filter_by(url=url).one()
                except NoResultFound:
                    self.logger.info(f'Updating feed {url} for the first time')
                    feed = Feed(url=url)
                else:
                    self.logger.info(
                        f'Updating feed {url} (last modified: {feed.last_modified})'
                    )
                    if feed.last_modified:
                        headers['If-Modified-Since'] = feed.last_modified
                    if feed.etag:
                        headers['If-None-Match'] = feed.etag
                response = await http_client.get(url, headers=headers)

                if response.status_code == httpx.codes.OK:
                    feed.last_modified = response.headers.get('Last-Modified')
                    feed.etag = response.headers.get('ETag')
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

        matches = {}
        for area in event['info'][0]['area']:
            jid_query = self.db.query(Registration.jid).filter(
                Registration.point.ST_Distance(from_shape(area['multipolygon']))
                <= SQRT2 * 10 ** (-self.config['coordinate_digits'])
            )
            for jid, in jid_query:
                self.logger.debug(
                    'Event %s matched for JID %s',
                    event['identifier'],
                    jid,
                )
                matches.setdefault(jid, []).append(area)

        for jid, areas in matches.items():
            jid_registrations = self.db.query(Registration).filter_by(jid=jid).count()
            self.send_update(
                aioxmpp.JID.fromstr(jid),
                event,
                areas if jid_registrations > 1 else [],
            )

    def send_update(self, jid, event, areas):
        lines = [', '.join(area['areaDesc'] for area in areas)]
        lines += [
            event['info'][0].get(x, '') for x in (
                'headline',
                'description',
                'instruction',
            )
        ]
        for info in ('effective', 'expires'):
            if info not in event['info'][0]:
                continue

            lines += ['%s: %s' % (
                _(info.capitalize()),
                reformat_date(event['info'][0][info]),
            )]

        msg = aioxmpp.Message(
            to=jid,
            type_=aioxmpp.MessageType.CHAT,
        )
        msg.body[None] = strip_html('\n'.join(filter(None, lines)))
        self.client.enqueue(msg)

    def register(self, jid, area):
        'Register to messages regarding a coordinate'

        if not area:
            return _('No coordinates given')

        try:
            point = parse_area(area, self.config['coordinate_digits'])
        except (TypeError, ValueError):
            return _('Invalid coordinates: {}').format(area)
        else:
            self.db.add(Registration(
                jid=jid,
                point=str(point),
            ))
            try:
                self.db.commit()

                ret = _('Successfully registered to coordinates {0.y}, {0.x}').format(point)
                if self.db.query(Registration).filter_by(jid=jid).count() == 1:
                    return '\n'.join((
                        ret,
                        self.config['welcome_message'].format(**self.config)
                    ))
                else:
                    return ret
            except IntegrityError:
                self.db.rollback()
                return _('Already registerd to coordinates {0.y}, {0.x}').format(point)

    def unregister(self, jid, area):
        'Unregister from messages regarding a coordinate, or "unregister all"'

        if not area:
            return _('No coordinates given')

        if area == 'all':
            count = self.db.query(Registration).filter_by(jid=jid).delete()
            if count == 0:
                return _('No registrations found, none unregistered.')
            else:
                self.db.commit()
                return translate.ngettext(
                    'Successfully unregistered from {} coordinate',
                    'Successfully unregistered from {} coordinates',
                    count
                ).format(count)

        try:
            point = parse_area(area, self.config['coordinate_digits'])
        except (TypeError, ValueError):
            return _('Invalid coordinates: {}').format(area)
        else:
            try:
                registration = self.db.query(Registration).filter_by(
                    jid=jid,
                    point=str(point),
                ).one()
            except NoResultFound:
                return _('Not registered to coordinates {0.y}, {0.x}').format(point)
            else:
                self.db.delete(registration)
                self.db.commit()
                return _('Successfully unregistered from coordinates {0.y}, {0.x}').format(point)

    def list(self, jid, arg):
        'List active registrations'

        return '\n'.join(
            '{0.y}, {0.x}'.format(to_shape(point))
            for point,
            in self.db.query(Registration.point).filter_by(jid=jid)
        ) or _('No active registrations')

    def help(self, jid, arg):
        'Show available commands'

        return '\n'.join([
            '{cmd}\n    {doc}'.format(
                cmd=cmd,
                doc=_(getattr(self, cmd).__doc__)
            ) for cmd in self.commands
        ] + [
            _('This bot is operated by {}').format(self.config['owner_jid'])
        ])

    def feeds(self, jid, arg):
        'Show list of feeds with last update timestamp'

        feeds = []
        for url in self.config['feeds']:
            try:
                feed = self.db.query(Feed).filter_by(url=url).one()
                last_modified = feed.last_modified
            except NoResultFound:
                last_modified = 'never'
            feeds.append(_('{url} (last updated: {last_modified})').format(
                url=url,
                last_modified=last_modified,
            ))
        return '\n'.join(feeds)
