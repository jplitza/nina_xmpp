import re
from shapely.geometry import Point


# Source: https://stackoverflow.com/a/47969823
def deref_multi(data, keys):
    try:
        return deref_multi(data[keys[0]], keys[1:]) if keys else data
    except KeyError:
        return None


def parse_area(area):
    # XXX: Limit granularity?
    return Point(*map(float, reversed(re.split(r'[, ]+', area, 1))))
