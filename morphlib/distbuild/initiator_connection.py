# distbuild/initiator_connection.py -- communicate with initiator
#
# Copyright (C) 2014  Codethink Limited
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


import logging

import distbuild


class InitiatorDisconnect(object):

    def __init__(self, id):
        self.id = id


class _Close(object):

    def __init__(self, event_source):
        self.event_source = event_source


class InitiatorConnection(distbuild.StateMachine):

    '''Communicate with the initiator.
    
    This state machine communicates with the initiator, relaying and
    translating messages from the initiator to the rest of the controller's
    state machines, and vice versa.

    '''
    
    _idgen = distbuild.IdentifierGenerator('InitiatorConnection')
    _route_map = distbuild.RouteMap()

    def __init__(self, conn, artifact_cache_server, morph_instance):
        distbuild.StateMachine.__init__(self, 'idle')
        self.conn = conn
        self.artifact_cache_server = artifact_cache_server
        self.morph_instance = morph_instance

    def setup(self):
        self.jm = distbuild.JsonMachine(self.conn)
        self.mainloop.add_state_machine(self.jm)

        self.our_ids = set()
        
        spec = [
            ('idle', self.jm, distbuild.JsonNewMessage, 'idle', 
                self._handle_msg),
            ('idle', self.jm, distbuild.JsonEof, 'closing', self._disconnect),
            ('idle', distbuild.BuildController, distbuild.BuildFinished,
                'idle', self._send_build_finished_message),
            ('idle', distbuild.BuildController, distbuild.BuildFailed,
                'idle', self._send_build_failed_message),
            ('idle', distbuild.BuildController, distbuild.BuildProgress, 
                'idle', self._send_build_progress_message),
            ('idle', distbuild.BuildController, distbuild.BuildSteps, 
                'idle', self._send_build_steps_message),
            ('idle', distbuild.BuildController, distbuild.BuildStepStarted, 
                'idle', self._send_build_step_started_message),
            ('idle', distbuild.BuildController, distbuild.BuildOutput, 
                'idle', self._send_build_output_message),
            ('idle', distbuild.BuildController, distbuild.BuildStepFinished,
                'idle', self._send_build_step_finished_message),
            ('idle', distbuild.BuildController, distbuild.BuildStepFailed, 
                'idle', self._send_build_step_failed_message),
            ('closing', self, _Close, None, self._close),
        ]
        self.add_transitions(spec)
        
    def _handle_msg(self, event_source, event):
        '''Handle message from initiator.'''
        
        logging.debug(
            'InitiatorConnection: from initiator: %s', repr(event.msg))
            
        if event.msg['type'] == 'build-request':
            new_id = self._idgen.next()
            self.our_ids.add(new_id)
            self._route_map.add(event.msg['id'], new_id)
            event.msg['id'] = new_id
            build_controller = distbuild.BuildController(
                event.msg, self.artifact_cache_server, self.morph_instance)
            self.mainloop.add_state_machine(build_controller)

    def _disconnect(self, event_source, event):
        for id in self.our_ids:
            logging.debug('InitiatorConnection: InitiatorDisconnect(%s)'
                          % str(id))
            self.mainloop.queue_event(InitiatorConnection,
                                      InitiatorDisconnect(id))
        # TODO should this clear our_ids?
        self.mainloop.queue_event(self, _Close(event_source))

    def _close(self, event_source, event):
        logging.debug('InitiatorConnection: closing: %s',
                      repr(event.event_source))

        event.event_source.close()

    def _handle_result(self, event_source, event):
        '''Handle result from helper.'''

        if event.msg['id'] in self.our_ids:
            logging.debug(
                'InitiatorConnection: received result: %s', repr(event.msg))
            self.jm.send(event.msg)

    def _send_build_finished_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-finished',
                id=self._route_map.get_incoming_id(event.id),
                urls=event.urls)
            self._route_map.remove(event.id)
            self.our_ids.remove(event.id)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_failed_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-failed',
                id=self._route_map.get_incoming_id(event.id),
                reason=event.reason)
            self._route_map.remove(event.id)
            self.our_ids.remove(event.id)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_progress_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-progress',
                id=self._route_map.get_incoming_id(event.id),
                message=event.message_text)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_steps_message(self, event_source, event):
    
        def make_step_dict(artifact):
            return {
                'name': distbuild.build_step_name(artifact),
                'build-depends': [
                    distbuild.build_step_name(x)
                    for x in artifact.dependencies
                ]
            }
            
        if event.id in self.our_ids:
            step_names = distbuild.map_build_graph(
                event.artifact, make_step_dict)
            msg = distbuild.message('build-steps',
                id=self._route_map.get_incoming_id(event.id),
                steps=step_names)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_step_started_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('step-started',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name,
                worker_name=event.worker_name)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_output_message(self, event_source, event):
        logging.debug('InitiatorConnection: build_output: '
            'id=%s stdout=%s stderr=%s' % 
            (repr(event.id), repr(event.stdout), repr(event.stderr)))
        if event.id in self.our_ids:
            msg = distbuild.message('step-output',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name,
                stdout=event.stdout,
                stderr=event.stderr)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_step_finished_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('step-finished',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

    def _send_build_step_failed_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('step-failed',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name)
            self.jm.send(msg)
            logging.debug(
                'InitiatorConnection: sent to initiator: %s', repr(msg))

