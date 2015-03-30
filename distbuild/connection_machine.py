# distbuild/connection_machine.py -- state machine for connecting to server
#
# Copyright (C) 2012, 2014-2015  Codethink Limited
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.


import errno
import logging
import socket

import distbuild


class Reconnect(object):

    pass
    
    
class StopConnecting(object):

    def __init__(self, exception=None):
        self.exception = exception

class ConnectError(object):

    def __init__(self, exception):
        self.exception = exception


class ProxyEventSource(object):

    '''Proxy event sources that may come and go.'''

    def __init__(self):
        self.event_source = None

    def get_select_params(self):
        if self.event_source:
            return self.event_source.get_select_params()
        else:
            return [], [], [], None
            
    def get_events(self, r, w, x):
        if self.event_source:
            return self.event_source.get_events(r, w, x)
        else:
            return []
            
    def is_finished(self):
        return False


class ConnectionMachine(distbuild.StateMachine):

    def __init__(self, addr, port, machine, extra_args,
                 reconnect_interval=1, max_retries=float('inf')):
        super(ConnectionMachine, self).__init__('connecting')
        self._addr = addr
        self._port = port
        self._machine = machine
        self._extra_args = extra_args
        self._socket = None
        self._reconnect_interval = reconnect_interval
        self._numof_retries = 0
        self._max_retries = max_retries

    def setup(self):
        self._sock_proxy = ProxyEventSource()
        self.mainloop.add_event_source(self._sock_proxy)
        self._start_connect()
        
        self._timer = distbuild.TimerEventSource(self._reconnect_interval)
        self.mainloop.add_event_source(self._timer)

        spec = [
            # state, source, event_class, new_state, callback
            ('connecting', self._sock_proxy, distbuild.SocketWriteable,
                'connected', self._connect),
            ('connecting', self, StopConnecting, None, self._stop),
            ('connected', self, Reconnect, 'connecting', self._reconnect),
            ('connected', self, ConnectError, 'timeout', self._start_timer),
            ('connected', self, StopConnecting, None, self._stop),
            ('timeout', self._timer, distbuild.Timer, 'connecting',
                self._reconnect),
            ('timeout', self, StopConnecting, None, self._stop),
        ]
        self.add_transitions(spec)
        
    def _start_connect(self):
        logging.debug(
            'ConnectionMachine: connecting to %s:%s' % 
                (self._addr, self._port))
        self._socket = distbuild.create_socket()
        distbuild.set_nonblocking(self._socket)
        try:
            self._socket.connect((self._addr, self._port))
        except socket.error as e:
            if e.errno != errno.EINPROGRESS:
                raise socket.error(
                    "%s (attempting connection to distbuild controller "
                    "at %s:%s)" % (e, self._addr, self._port))

        src = distbuild.SocketEventSource(self._socket)
        self._sock_proxy.event_source = src
        
    def _connect(self, event_source, event):
        try:
            self._socket.connect((self._addr, self._port))
        except socket.error as e:
            logging.error(
                'Failed to connect to %s:%s: %s' % 
                    (self._addr, self._port, str(e)))

            if self._numof_retries < self._max_retries:
                self.mainloop.queue_event(self, ConnectError(e))
            else:
                self.mainloop.queue_event(self, StopConnecting(e))

            return
        self._sock_proxy.event_source = None
        logging.info('Connected to %s:%s' % (self._addr, self._port))
        m = self._machine(self, self._socket, *self._extra_args)
        self.mainloop.add_state_machine(m)
        self._socket = None

    def _reconnect(self, event_source, event):
        logging.info('Reconnecting to %s:%s' % (self._addr, self._port))
        self._numof_retries += 1

        if self._socket is not None:
            self._socket.close()
        self._timer.stop()
        self._start_connect()

    def _stop(self, event_source, event):
        logging.info(
            'Stopping connection attempts to %s:%s' % (self._addr, self._port))
        self.mainloop.remove_event_source(self._timer)
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _start_timer(self, event_source, event):
        self._timer.start()

        self._sock_proxy.event_source.close()
        self._sock_proxy.event_source = None

class InitiatorConnectionMachine(ConnectionMachine):

    def __init__(self, app, addr, port, machine, extra_args,
                 reconnect_interval, max_retries):

        self.cm = super(InitiatorConnectionMachine, self)
        self.cm.__init__(addr, port, machine, extra_args,
                         reconnect_interval, max_retries)

        self.app = app

    def get_addr(self):
        return self._addr

    def get_port(self):
        return self._port

    def _connect(self, event_source, event):
        self.app.status(msg='Connecting to %s:%s' % (self._addr, self._port))
        self.cm._connect(event_source, event)

    def _stop(self, event_source, event):
        if event.exception:
            self.app.status(msg="Couldn't connect to %s:%s: %s" %
                            (self._addr, self._port, event.exception.strerror))

        self.cm._stop(event_source, event)

    def _start_timer(self, event_source, event):
        self.app.status(msg="Couldn't connect to %s:%s: %s" %
                        (self._addr, self._port, event.exception.strerror))
        self.app.status(msg="Retrying in %d seconds" %
                        self._reconnect_interval)

        self.cm._start_timer(event_source, event)
