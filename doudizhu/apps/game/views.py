import json
import logging
from typing import Optional, List, Union, Any

from tornado.escape import json_decode
from tornado.web import authenticated
from tornado.websocket import WebSocketHandler, WebSocketClosedError

from contrib.db import AsyncConnection
from contrib.handlers import RestfulHandler, JwtMixin
from .player import Player
from .protocol import Protocol
from .room import Room
from .storage import Storage


class SocketHandler(WebSocketHandler, JwtMixin):

    def __init__(self, application, request, **kwargs):
        super().__init__(application, request, **kwargs)
        self.db: AsyncConnection = self.application.db
        self.player: Optional[Player] = None

    async def get(self, *args: Any, **kwargs: Any) -> None:
        self.request.headers['origin'] = None
        self.request.headers['Sec-Websocket-Origin'] = None
        await super().get(*args, **kwargs)

    def data_received(self, chunk):
        logging.info('socket data_received')

    def get_current_user(self):
        token = self.get_argument('token', None)
        if token:
            return self.jwt_decode(token)
        cookie = self.get_secure_cookie("user")
        if cookie:
            return json_decode(cookie)
        return None

    @property
    def uid(self) -> int:
        return self.player.uid

    @property
    def room(self) -> Optional[Room]:
        return self.player.room

    @property
    def allow_robot(self) -> bool:
        return self.application.allow_robot

    @authenticated
    def open(self):
        user = self.current_user
        self.player = Storage.find_or_create_player(user['uid'], user['username'])
        self.player.socket = self
        logging.info('SOCKET[%s] OPEN', self.player.uid)

    def on_message(self, message):
        if message == 'ping':
            self._write_message('pong')
        else:
            packet = json.loads(message)
            logging.info('REQ[%d]: %s', self.uid, message)
            self.player.on_message(packet)

    def on_close(self):
        self.player.on_disconnect()
        logging.info('SOCKET[%s] CLOSE', self.player.uid)

    def write_message(self, message: List[Union[Protocol, Any]], binary=False):
        packet = json.dumps(message)
        self._write_message(packet, binary)

    def _write_message(self, message, binary=False):
        if self.ws_connection is None:
            return
        try:
            future = self.ws_connection.write_message(message, binary=binary)
            logging.info('RSP[%d]: %s', self.uid, message)
        except WebSocketClosedError:
            logging.error('WebSockedClosed[%s][%s]', self.uid, message)


class AdminHandler(RestfulHandler):
    required_fields = ('allow_robot',)

    @authenticated
    def get(self):
        if self.current_user['uid'] != 1:
            self.send_error(403, reason='Forbidden')
            return
        self.write({'allow_robot': self.application.allow_robot})

    @authenticated
    def post(self):
        if self.current_user['uid'] != 1:
            self.send_error(403, reason='Forbidden')
            return
        self.application.allow_robot = bool(self.get_body_argument('allow_robot'))
        self.write({'allow_robot': self.application.allow_robot})
