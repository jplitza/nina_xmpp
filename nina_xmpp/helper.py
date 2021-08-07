import re
from datetime import datetime, date
from shapely.geometry import Point


def parse_area(area):
    # XXX: Limit granularity?
    return Point(*map(float, reversed(re.split(r'[, ]+', area, 1))))


def reformat_date(isodate):
    d = datetime.fromisoformat(isodate)
    return d.strftime(
        '%d.%m.%Y %H:%M'
        if d.date() != date.today()
        else '%H:%M'
    )
