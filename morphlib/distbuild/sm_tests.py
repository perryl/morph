# distbuild/sm_tests.py -- unit tests for state machine abstraction
#
# Copyright 2012 Codethink Limited.
# All rights reserved.


import unittest

import distbuild


class DummyEventSource(object):

    pass
    
    
class DummyEvent(object):

    pass


class StateMachineTests(unittest.TestCase):

    def setUp(self):
        self.sm = distbuild.StateMachine('init')
        self.sm.distbuild = None
        self.sm.setup()
        self.event_source = DummyEventSource()
        self.event = DummyEvent()
        self.event_sources = []
        self.events = []
        self.callback_result = None
    
    def callback(self, event_source, event):
        self.event_sources.append(event_source)
        self.events.append(event)
        return self.callback_result
    
    def test_ignores_event_when_there_are_no_transitions(self):
        new_events = self.sm.handle_event(self.event_source, self.event)
        self.assertEqual(new_events, [])
        self.assertEqual(self.event_sources, [])
        self.assertEqual(self.events, [])

    def test_ignores_event_when_no_transition_matches(self):
        spec = [
            ('init', self.event_source, str, 'init', self.callback),
        ]
        self.sm.add_transitions(spec)
        new_events = self.sm.handle_event(self.event_source, self.event)
        self.assertEqual(new_events, [])
        self.assertEqual(self.event_sources, [])
        self.assertEqual(self.events, [])

    def test_handles_lack_of_callback_ok(self):
        spec = [
            ('init', self.event_source, DummyEvent, 'init', None),
        ]
        self.sm.add_transitions(spec)
        new_events = self.sm.handle_event(self.event_source, self.event)
        self.assertEqual(new_events, [])
        self.assertEqual(self.event_sources, [])
        self.assertEqual(self.events, [])

    def test_calls_registered_callback_for_right_event(self):
        spec = [
            ('init', self.event_source, DummyEvent, 'init', self.callback),
        ]
        self.sm.add_transitions(spec)
        new_events = self.sm.handle_event(self.event_source, self.event)
        self.assertEqual(new_events, [])
        self.assertEqual(self.event_sources, [self.event_source])
        self.assertEqual(self.events, [self.event])

    def test_handle_converts_nonlist_to_list(self):
        self.callback_result = ('foo', 'bar')

        spec = [
            ('init', self.event_source, DummyEvent, 'init', self.callback),
        ]
        self.sm.add_transitions(spec)
        new_events = self.sm.handle_event(self.event_source, self.event)
        self.assertEqual(new_events, ['foo', 'bar'])
        self.assertEqual(self.event_sources, [self.event_source])
        self.assertEqual(self.events, [self.event])

