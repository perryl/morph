# mainloop/sm.py -- state machine abstraction
#
# Copyright 2012 Codethink Limited.
# All rights reserved.


import logging
import re


classnamepat = re.compile(r"<class '(?P<name>.*)'>")


class StateMachine(object):

    '''A state machine abstraction.
    
    The caller may specify call backs for events coming from specific
    event sources. An event source might, for example, be a socket
    file descriptor, and the event might be incoming data from the
    socket. The callback would then process the data, perhaps by
    collecting it into a buffer and parsing out messages from it.
    
    A callback gets the event source and event as arguments. It returns
    the new state, and a list of new events to 
    
    A callback may return or yield new events, which will be handled
    eventually. They may or may not be handled in order.
    
    There can only be one callback for one state, source, and event
    class combination.
    
    States are represented by unique objects, e.g., strings containing
    the names of the states. When a machine wants to stop, it sets its
    state to None.
    
    '''
    
    def __init__(self, initial_state):
        self._transitions = {}
        self.state = self._initial_state = initial_state
        self.debug_transitions = False

    def setup(self):
        '''Set up machine for execution.
        
        This is called when the machine is added to the main loop.
        
        '''
        
    def _key(self, state, event_source, event_class):
        return (state, event_source, event_class)

    def add_transition(self, state, source, event_class, new_state, callback):
        '''Add a transition to the state machine.
        
        When the state machine is in the given state, and an event of
        a given type comes from a given source, move the state machine
        to the new state and call the callback function.
        
        '''

        key = self._key(state, source, event_class)
        assert key not in self._transitions, \
            'Transition %s already registered' % str(key)
        self._transitions[key] = (new_state, callback)

    def add_transitions(self, specification):
        '''Add many transitions.
        
        The specification is a list of transitions. 
        Each transition is a tuple of the arguments given to
        ``add_transition``.
        
        '''
        
        for t in specification:
            self.add_transition(*t)
    
    def handle_event(self, event_source, event):
        '''Handle a given event.
        
        Return list of new events to handle.
        
        '''

        key = self._key(self.state, event_source, event.__class__)
        if key not in self._transitions:
            if self.debug_transitions: # pragma: no cover
                prefix = '%s: handle_event: ' % self.__class__.__name__
                logging.debug(prefix + 'not relevant for us: %s' % repr(event))
                logging.debug(prefix + 'key: %s', repr(key))
                logging.debug(prefix + 'state: %s', repr(self.state))
            return []

        new_state, callback = self._transitions[key]
        if self.debug_transitions: # pragma: no cover
            logging.debug(
                '%s: state change %s -> %s callback=%s' % 
                    (self.__class__.__name__, self.state, new_state, 
                     str(callback)))
        self.state = new_state
        if callback is not None:
            ret = callback(event_source, event)
            if ret is None:
                return []
            else:
                return list(ret)
        else:
            return []
            
    def dump_dot(self, filename): # pragma: no cover
        '''Write a Graphviz DOT file for the state machine.'''

        with open(filename, 'w') as f:
            f.write('digraph %s {\n' % self._classname(self.__class__))
            first = True
            for key in self._transitions:
                state, src, event_class = key
                if first:
                    f.write('"START" -> "%s" [label=""];\n' %
                            self._initial_state)
                    first = False

                new_state, callback = self._transitions[key]
                if new_state is None:
                    new_state = 'END'
                f.write('"%s" -> "%s" [label="%s"];\n' %
                        (state, new_state, self._classname(event_class)))
            f.write('}\n')

    def _classname(self, klass): # pragma: no cover
        s = str(klass)
        m = classnamepat.match(s)
        if m:
            return m.group('name').split('.')[-1]
        else:
            return s

