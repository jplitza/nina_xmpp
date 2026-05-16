FROM python:3.11-slim AS builder

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

FROM python:3.11-slim

RUN apt-get -y update && apt-get install -y --no-install-recommends libsqlite3-mod-spatialite && apt-get clean

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/nina_xmpp /usr/local/bin/nina_xmpp

ENTRYPOINT ["/usr/local/bin/nina_xmpp"]
