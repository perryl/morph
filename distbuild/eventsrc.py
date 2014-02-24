# mainloop/eventsrc.py -- interface for event sources
#
# Copyright 2012 Codethink Limited.
# All rights reserved.


class EventSource(object):

    '''A source of events for state machines.
    
    This is a base class.
    
    An event source watches one file descriptor, and returns events
    related to it. The events may vary depending on the file descriptor.
    The actual watching is done using select.select.
    
    '''
    
    def get_select_params(self):
        '''Return parameters to use for select for this event source.
        
        Three lists of file descriptors, and a timeout are returned.
        The three lists and the timeout are used as arguments to the 
        select.select function, though they may be manipulated and
        combined with return values from other event sources.
        
        '''
        
        return [], [], [], None

    def get_events(self, r, w, x):
        '''Return events related to this file descriptor.
        
        The arguments are the return values of select.select.
        
        '''
        
        return []

    def is_finished(self):
        '''Is this event source finished?
        
        It's finished if it won't ever return any new events.
        
        '''
        
        return False

