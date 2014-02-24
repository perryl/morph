# mainloop/jm.py -- state machine for JSON communication between nodes
#
# Copyright 2012 Codethink Limited.
# All rights reserved.


import fcntl
import json
import logging
import os
import socket
import sys

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
        self.debug_json = False
        
    def setup(self):
        sockbuf = self.sockbuf = SocketBuffer(self.conn, self.max_buffer)
        self.mainloop.add_state_machine(sockbuf)

        self._eof = False
        self.receive_buf = StringBuffer()

        spec = [
            ('rw', sockbuf, SocketBufferNewData, 'rw', self._parse),
            ('rw', sockbuf, SocketBufferEof, 'w', self._send_eof),
            ('rw', self, _Close2, None, self._really_close),
            
            ('w', self, _Close2, None, self._really_close),
        ]
        self.add_transitions(spec)
        
    def send(self, msg):
        '''Send a message to the other side.'''
        self.sockbuf.write('%s\n' % json.dumps(msg))
    
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
            msg = json.loads(line)
            self.mainloop.queue_event(self, JsonNewMessage(msg))

    def _send_eof(self, event_source, event):
        self.mainloop.queue_event(self, JsonEof())

    def _really_close(self, event_source, event):
        self.sockbuf.close()
        self._send_eof(event_source, event)

