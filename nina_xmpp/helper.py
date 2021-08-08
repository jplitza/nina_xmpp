import re
from datetime import datetime, date
from shapely.geometry import Point


def parse_area(area, ndigits):
    lon, lat = (
        round(float(x), ndigits)
        for x in re.split(r'[, ]+', area, 1)
    )
    return Point(lat, lon)


def reformat_date(isodate):
    d = datetime.fromisoformat(isodate)
    return d.strftime(
        '%d.%m.%Y %H:%M'
        if d.date() != date.today()
        else '%H:%M'
    )
