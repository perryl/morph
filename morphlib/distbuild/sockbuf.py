# mainloop/sockbuf.py -- a buffering, non-blocking socket I/O state machine
#
# Copyright 2012 Codethink Limited
# All rights reserved.


import logging


'''A buffering, non-blocking I/O state machine for sockets.

The state machine is given an open socket. It reads from the socket,
and writes to it, when it can do so without blocking. A maximum size
for the read buffer can be set: the state machine will stop reading
if the buffer becomes full. This avoids the problem of an excessively
large buffer.

The state machine generates events to indicate that the buffer contains
data or that the end of the file for reading has been reached. An event
is also generated if there is an error while doing I/O with the socket.

* SocketError: an error has occurred
* SocketBufferNewData: socket buffer has received new data; the data
  is available as the ``data`` attribute
* SocketBufferEof: socket buffer has reached EOF for reading, but
  still writes anything in the write buffer (or anything that gets added
  to the write buffer)
* SocketBufferClosed: socket is now closed

The state machine starts shutting down when ``close`` method is called,
but continues to operate in write-only mode until the write buffer has
been emptied.

'''


from socketsrc import (SocketError, SocketReadable, SocketWriteable,
                       SocketEventSource)
from sm import StateMachine
from stringbuffer import StringBuffer


class SocketBufferNewData(object):

    '''Socket buffer has received new data.'''

    def __init__(self, data):
        self.data = data


class SocketBufferEof(object):

    '''Socket buffer has reached end of file when reading.
    
    Note that the socket buffer may still be available for writing.
    However, no more new data will be read.
    
    '''


class SocketBufferClosed(object):

    '''Socket buffer has closed its socket.'''

        
class _Close(object): pass
class _WriteBufferIsEmpty(object): pass
class _WriteBufferNotEmpty(object): pass

        
        
class SocketBuffer(StateMachine):

    def __init__(self, sock, max_buffer):
        StateMachine.__init__(self, 'reading')

        self._sock = sock
        self._max_buffer = max_buffer

    def setup(self):        
        src = self._src = SocketEventSource(self._sock)
        src.stop_writing() # We'll start writing when we need to.
        self.mainloop.add_event_source(src)

        self._wbuf = StringBuffer()

        spec = [
            ('reading', src, SocketReadable, 'reading', self._fill),
            ('reading', self, _WriteBufferNotEmpty, 'rw', 
                self._start_writing),
            ('reading', self, SocketBufferEof, 'idle', None),
            ('reading', self, _Close, None, self._really_close),
            
            ('rw', src, SocketReadable, 'rw', self._fill),
            ('rw', src, SocketWriteable, 'rw', self._flush),
            ('rw', self, _WriteBufferIsEmpty, 'reading', self._stop_writing),
            ('rw', self, SocketBufferEof, 'w', None),
            ('rw', self, _Close, 'wc', None),
            
            ('idle', self, _WriteBufferNotEmpty, 'w', self._start_writing),
            ('idle', self, _Close, None, self._really_close),
            
            ('w', src, SocketWriteable, 'w', self._flush),
            ('w', self, _WriteBufferIsEmpty, 'idle', self._stop_writing),

            ('wc', src, SocketWriteable, 'wc', self._flush),
            ('wc', self, _WriteBufferIsEmpty, None, self._really_close),
        ]
        self.add_transitions(spec)

    def write(self, data):
        '''Put data into write queue.'''
        
        was_empty = len(self._wbuf) == 0
        self._wbuf.add(data)
        if was_empty and len(self._wbuf) > 0:
            self._start_writing(None, None)
            self.mainloop.queue_event(self, _WriteBufferNotEmpty())

    def close(self):
        '''Tell state machine to terminate.'''
        self.mainloop.queue_event(self, _Close())

    def _report_error(self, event_source, event):
        logging.error(str(event))

    def _fill(self, event_source, event):
        try:
            data = event.sock.read(self._max_buffer)
        except (IOError, OSError), e:
            return [SocketError(event.sock, e)]

        if data:
            self.mainloop.queue_event(self, SocketBufferNewData(data))
        else:
            event_source.stop_reading()
            self.mainloop.queue_event(self, SocketBufferEof())

    def _really_close(self, event_source, event):
        self._src.close()
        self.mainloop.queue_event(self, SocketBufferClosed())

    def _flush(self, event_source, event):
        max_write = 1024**2
        data = self._wbuf.read(max_write)
        try:
            n = event.sock.write(data)
        except (IOError, OSError), e:
            return [SocketError(event.sock, e)]
        self._wbuf.remove(n)
        if len(self._wbuf) == 0:
            self.mainloop.queue_event(self, _WriteBufferIsEmpty())

    def _start_writing(self, event_source, event):
        self._src.start_writing()

    def _stop_writing(self, event_source, event):
        self._src.stop_writing()

