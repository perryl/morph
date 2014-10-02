# mainloop/jm.py -- state machine for JSON communication between nodes
#
# Copyright (C) 2012, 2014  Codethink Limited
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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA..


import base64
import fcntl
import json
import logging
import os
import socket
import sys
import yaml

from sm import StateMachine 
from stringbuffer import StringBuffer
from sockbuf import (SocketBuffer, SocketBufferNewData, 
                     SocketBufferEof, SocketError)


class JsonNewMessage(object):

    def __init__(self, msg):
        self.msg = msg

        
class JsonEof(object):

    pass
    
    
class _Close2(object):

    pass


class JsonMachine(StateMachine):

    '''A state machine for sending/receiving JSON messages across TCP.'''

    max_buffer = 16 * 1024

    def __init__(self, conn):
        StateMachine.__init__(self, 'rw')
        self.conn = conn
        self.debug_json = True

    def __repr__(self):
        return '<JsonMachine at 0x%x: socket %s, max_buffer %s>' % \
            (id(self), self.conn, self.max_buffer)

    def setup(self):
        sockbuf = self.sockbuf = SocketBuffer(self.conn, self.max_buffer)
        self.mainloop.add_state_machine(sockbuf)

        self._eof = False
        self.receive_buf = StringBuffer()

        spec = [
            # state, source, event_class, new_state, callback
            ('rw', sockbuf, SocketBufferNewData, 'rw', self._parse),
            ('rw', sockbuf, SocketBufferEof, 'w', self._send_eof),
            ('rw', self, _Close2, None, self._really_close),
            
            ('w', self, _Close2, None, self._really_close),
        ]
        self.add_transitions(spec)
        
    def send(self, msg):
        '''Send a message to the other side.'''
        if self.debug_json:
            logging.debug('JsonMachine: Sending message %s' % repr(msg))
	s = json.dumps(base64.standard_b64encode(yaml.safe_dump(msg)))
        if self.debug_json:
            logging.debug('JsonMachine: As %s' % repr(s))
        self.sockbuf.write('%s\n' % s)
    
    def close(self):
        '''Tell state machine it should shut down.
        
        The state machine will vanish once it has flushed any pending
        writes.
        
        '''
        
        self.mainloop.queue_event(self, _Close2())
        
    def _parse(self, event_source, event):
        data = event.data
        self.receive_buf.add(data)
        if self.debug_json:
            logging.debug('JsonMachine: Received: %s' % repr(data))
        while True:
            line = self.receive_buf.readline()
            if line is None:
                break
            line = line.rstrip()
            if self.debug_json:
                logging.debug('JsonMachine: line: %s' % repr(line))
            msg = yaml.load(base64.standard_b64decode(json.loads(line)))
            self.mainloop.queue_event(self, JsonNewMessage(msg))

    def _send_eof(self, event_source, event):
        self.mainloop.queue_event(self, JsonEof())

    def _really_close(self, event_source, event):
        self.sockbuf.close()
        self._send_eof(event_source, event)

