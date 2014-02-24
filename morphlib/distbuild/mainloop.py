# mainloop/mainloop.py -- select-based main loop
#
# Copyright 2012 Codethink Limited.
# All rights reserved.


import fcntl
import logging
import os
import select


class MainLoop(object):

    '''A select-based main loop.
    
    The main loop watches a set of file descriptors wrapped in 
    EventSource objects, and when something happens with them,
    asks the EventSource objects to create events, which it then
    feeds into user-supplied state machines. The state machines
    can create further events, which are processed further.
    
    When nothing is happening, the main loop sleeps in the
    select.select call.
    
    '''

    def __init__(self):
        self._machines = []
        self._sources = []
        self._events = []
        self.dump_filename = None
        
    def add_state_machine(self, machine):
        logging.debug('MainLoop.add_state_machine: %s' % machine)
        machine.mainloop = self
        machine.setup()
        self._machines.append(machine)
        if self.dump_filename:
            filename = '%s%s.dot' % (self.dump_filename, 
                                     machine.__class__.__name__)
            machine.dump_dot(filename)
        
    def remove_state_machine(self, machine):
        logging.debug('MainLoop.remove_state_machine: %s' % machine)
        self._machines.remove(machine)
    
    def add_event_source(self, event_source):
        logging.debug('MainLoop.add_event_source: %s' % event_source)
        self._sources.append(event_source)
    
    def remove_event_source(self, event_source):
        logging.debug('MainLoop.remove_event_source: %s' % event_source)
        self._sources.remove(event_source)
    
    def _setup_select(self):
        r = []
        w = []
        x = []
        timeout = None

        self._sources = [s for s in self._sources if not s.is_finished()]
        
        for event_source in self._sources:
            sr, sw, sx, st = event_source.get_select_params()
            r.extend(sr)
            w.extend(sw)
            x.extend(sx)
            if timeout is None:
                timeout = st
            elif st is not None:
                timeout = min(timeout, st)

        return r, w, x, timeout

    def _run_once(self):
        r, w, x, timeout = self._setup_select()
        assert r or w or x or timeout is not None
        r, w, x = select.select(r, w, x, timeout)

        for event_source in self._sources:
            if event_source.is_finished():
                self.remove_event_source(event_source)
            else:
                for event in event_source.get_events(r, w, x):
                    self.queue_event(event_source, event)

        for event_source, event in self._dequeue_events():
            for machine in self._machines[:]:
                for new_event in machine.handle_event(event_source, event):
                    self.queue_event(event_source, new_event)
                if machine.state is None:
                    self.remove_state_machine(machine)

    def run(self):
        '''Run the main loop.
        
        The main loop terminates when there are no state machines to
        run anymore.
        
        '''

        logging.debug('MainLoop starts')
        while self._machines:
            self._run_once()
        logging.debug('MainLoop ends')

    def queue_event(self, event_source, event):
        '''Add an event to queue of events to be processed.'''
        
        self._events.append((event_source, event))

    def _dequeue_events(self):
        while self._events:
            event_queue, event = self._events.pop(0)
            yield event_queue, event

