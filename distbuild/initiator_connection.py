# distbuild/initiator_connection.py -- communicate with initiator
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


import logging

import distbuild


class InitiatorDisconnect(object):

    def __init__(self, id):
        self.id = id


class _Close(object):

    def __init__(self, event_source):
        self.event_source = event_source


class InitiatorConnection(distbuild.StateMachine):

    '''Communicate with a single initiator.

    When a developer runs 'morph distbuild' and connects to the controller,
    the ListenServer object on the controller creates an InitiatorConnection.

    This state machine communicates with the build initiator, relaying and
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
        self.initiator_name = conn.remotename()

    def __repr__(self):
        return '<InitiatorConnection at 0x%x: remote %s>' % (id(self),
                self.initiator_name)

    def setup(self):
        self.jm = distbuild.JsonMachine(self.conn)
        self.mainloop.add_state_machine(self.jm)

        self.our_ids = set()
        
        spec = [
            # state, source, event_class, new_state, callback
            ('idle', self.jm, distbuild.JsonNewMessage, 'idle', 
                self._handle_msg),
            ('idle', self.jm, distbuild.JsonEof, 'closing', self._disconnect),
            ('idle', distbuild.BuildController, distbuild.BuildFinished,
                'idle', self._send_build_finished_message),
            ('idle', distbuild.BuildController, distbuild.BuildFailed,
                'idle', self._send_build_failed_message),
            ('idle', distbuild.BuildController, distbuild.BuildProgress, 
                'idle', self._send_build_progress_message),
            ('idle', distbuild.BuildController, distbuild.BuildStepStarted, 
                'idle', self._send_build_step_started_message),
            ('idle', distbuild.BuildController,
                distbuild.BuildStepAlreadyStarted, 'idle',
                self._send_build_step_already_started_message),
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

        logging.debug('InitiatorConnection: from %s: %r', self.initiator_name,
                event.msg)

        msg_handler = {
            'build-request': self._handle_build_request,
            'list-requests': self._handle_list_requests,
            'build-cancel': self._handle_build_cancel,
            'build-status': self._handle_build_status,
        }
        try:
            msg_handler[event.msg['type']](event)
        except (KeyError, ValueError) as ex:
            logging.error('Invalid message from initiator: %s: exception %s',
                           event.msg, ex)

    def _handle_build_request(self, event):
        if event.msg.get('protocol_version') != distbuild.protocol.VERSION:
            msg = distbuild.message('build-failed',
                id=event.msg['id'],
                reason=('Protocol version mismatch between server & initiator:'
                        ' distbuild network uses distbuild protocol version %i'
                        ', but client uses version %i.' % (
                        distbuild.protocol.VERSION,
                        event.msg.get('protocol_version'))))
            self.jm.send(msg)
            self._log_send(msg)
            return
        new_id = self._idgen.next()
        self.our_ids.add(new_id)
        self._route_map.add(event.msg['id'], new_id)
        event.msg['id'] = new_id
        build_controller = distbuild.BuildController(
            self, event.msg, self.artifact_cache_server,
            self.morph_instance)
        self.mainloop.add_state_machine(build_controller)
        self.mainloop.store_state_machine(build_controller)

    def _handle_list_requests(self, event):
        requests = self.mainloop.state_machines_of_type(
                   distbuild.BuildController)
        output_msg = []
        output_msg.append('%s distbuild requests(s) currently in progress' %
                          len(requests))
        for build in requests:
            output_msg.append('Build request ID: %s\n  Initiator: %s\n  Repo: '
                              '%s\n  Ref: %s\n  Component: %s'
                              % (build.get_request()['id'],
                              build.get_initiator_connection().initiator_name,
                              build.get_request()['repo'],
                              build.get_request()['ref'],
                              build.get_request()['morphology']))
        msg = distbuild.message('list-request-output',
                                message=('\n\n'.join(output_msg)))
        self.jm.send(msg)

    def _handle_build_cancel(self, event):
        requests = self.mainloop.state_machines_of_type(
                   distbuild.BuildController)
        for build in requests:
            if build.get_request()['id'] == event.msg['id']:
                self.mainloop.queue_event(InitiatorConnection,
                                          InitiatorDisconnect(event.msg['id']))
                self.mainloop.queue_event(distbuild.WorkerBuildQueuer,
                                          distbuild.WorkerCancelPending(
                                              event.msg['id']))
                self.mainloop.queue_event(distbuild.BuildController,
                                          distbuild.BuildCancel(
                                              event.msg['id']))
                msg = distbuild.message('build-cancel-output', message=(
                                        'Cancelling build request with ID %s' %
                                        event.msg['id']))
                self.jm.send(msg)
                break
        else:
            msg = distbuild.message('build-cancel-output', message=('Given '
                                    'build-request ID does not match any '
                                    'running build IDs.'))
            self.jm.send(msg)

    def _handle_build_status(self, event):
        requests = self.mainloop.state_stored_requests(
                   distbuild.BuildController)
        for build in requests:
            if build.get_request()['id'] == event.msg['id']:
                msg = distbuild.message('build-status-output', message=(
                                        build.get_status_message))
                self.jm.send(msg)
                break
        else:
            msg = distbuild.message('build-status-output', message=('Given '
                                    'build-request ID does not match any '
                                    'recent build IDs.'))
            self.jm.send(msg)

    def _disconnect(self, event_source, event):
        for id in self.our_ids:
            logging.debug('InitiatorConnection: %s: InitiatorDisconnect(%s)',
                    self.initiator_name, str(id))
            self.mainloop.queue_event(InitiatorConnection,
                                      InitiatorDisconnect(id))
        self.mainloop.queue_event(self, _Close(event_source))

    def _close(self, event_source, event):
        logging.debug('InitiatorConnection: %s: closing: %s',
                      self.initiator_name, repr(event.event_source))

        event.event_source.close()

    def _handle_result(self, event_source, event):
        '''Handle result from helper.'''

        if event.msg['id'] in self.our_ids:
            logging.debug(
                'InitiatorConnection: received result: %s', repr(event.msg))
            self.jm.send(event.msg)

    def _log_send(self, msg):
        logging.debug(
            'InitiatorConnection: sent to %s: %r', self.initiator_name, msg)

    def _send_build_finished_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-finished',
                id=self._route_map.get_incoming_id(event.id),
                urls=event.urls)
            self._route_map.remove(event.id)
            self.our_ids.remove(event.id)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_failed_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-failed',
                id=self._route_map.get_incoming_id(event.id),
                reason=event.reason)
            self._route_map.remove(event.id)
            self.our_ids.remove(event.id)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_progress_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-progress',
                id=self._route_map.get_incoming_id(event.id),
                message=event.message_text)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_step_started_message(self, event_source, event):
        logging.debug('InitiatorConnection: build_step_started: '
            'id=%s step_name=%s worker_name=%s' %
            (event.id, event.step_name, event.worker_name))
        if event.id in self.our_ids:
            msg = distbuild.message('step-started',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name,
                worker_name=event.worker_name)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_step_already_started_message(self, event_source, event):
        logging.debug('InitiatorConnection: build_step_already_started: '
            'id=%s step_name=%s worker_name=%s' % (event.id, event.step_name,
                event.worker_name))

        if event.id in self.our_ids:
            msg = distbuild.message('step-already-started',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name,
                worker_name=event.worker_name)
            self.jm.send(msg)
            self._log_send(msg)

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
            self._log_send(msg)

    def _send_build_step_finished_message(self, event_source, event):
        logging.debug('heard built step finished: event.id: %s our_ids: %s'
            % (str(event.id), str(self.our_ids)))
        if event.id in self.our_ids:
            msg = distbuild.message('step-finished',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_step_failed_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('step-failed',
                id=self._route_map.get_incoming_id(event.id),
                step_name=event.step_name)
            self.jm.send(msg)
            self._log_send(msg)

