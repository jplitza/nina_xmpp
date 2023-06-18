from sqlalchemy import create_engine, event, Column, DDL, Integer, String
from sqlalchemy.sql import select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.event import listen
from geoalchemy2 import Geometry


Base = declarative_base()


def _load_spatialite(dbapi_conn, connection_record):
    dbapi_conn.enable_load_extension(True)
    dbapi_conn.load_extension('mod_spatialite')


class Registration(Base):
    __tablename__ = 'registration'
    id = Column(Integer, primary_key=True)
    jid = Column(String, index=True, nullable=False)
    point = Column(Geometry(geometry_type='POINT', management=True), nullable=False)


# cannot use UniqueConstraint since the point column is added later on
event.listen(
    Registration.__table__,
    'after_create',
    DDL("CREATE UNIQUE INDEX uq_registration_jid_point on registration(jid, point)"),
)


class Feed(Base):
    __tablename__ = 'feed'
    url = Column(String, primary_key=True)
    last_modified = Column(String)
    etag = Column(String)


class Event(Base):
    __tablename__ = 'event'
    id = Column(String, primary_key=True)


def initialize(database):
    engine = create_engine(database)
    listen(engine, 'connect', _load_spatialite)
    with engine.connect() as conn:
        conn.execute(select(func.InitSpatialMetaData(True, 'WGS84')))
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()
