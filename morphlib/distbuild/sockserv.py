# mainloop/sockserv.py -- socket server state machines
#
# Copyright 2012 Codethink Limited
# All rights reserved.


import logging

from sm import StateMachine
from socketsrc import NewConnection, SocketError, ListeningSocketEventSource


class ListenServer(StateMachine):

    '''Listen for new connections on a port, send events for them.'''

    def __init__(self, addr, port, machine, extra_args=None):
        StateMachine.__init__(self, 'listening')
        self._addr = addr
        self._port = port
        self._machine = machine
        self._extra_args = extra_args or []
        
    def setup(self):
        src = ListeningSocketEventSource(self._addr, self._port)
        self.mainloop.add_event_source(src)

        spec = [
            ('listening', src, NewConnection, 'listening', self.new_conn),
            ('listening', src, SocketError, None, self.report_error),
        ]
        self.add_transitions(spec)

    def new_conn(self, event_source, event):
        logging.debug(
            'ListenServer: Creating new %s using %s and %s' %
                (repr(self._machine),
                 repr(event.connection),
                 repr(self._extra_args)))
        m = self._machine(event.connection, *self._extra_args)
        self.mainloop.add_state_machine(m)

    def report_error(self, event_source, event):
        logging.error(str(event))

