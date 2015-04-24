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
import getpass
import socket

import distbuild

PROTOCOL_VERSION_MISMATCH_RESPONSE = (
    'Protocol version mismatch between server and initiator: '
    'distbuild network uses distbuild protocol version %s, '
    'but client uses version %s.'
)

class InitiatorDisconnect(object):

    def __init__(self, id):
        self.id = id


class CancelRequest(object):

    def __init__(self, id, user):
        self.id = id
        self.user = user


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
        self._debug_build_output = False
        self.who = '%s@%s' % (getpass.getuser(), socket.gethostname())

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
            ('idle', self.jm, distbuild.JsonError, 'closing',
                self._disconnect),
            ('idle', self.jm, distbuild.JsonEof, 'closing', self._disconnect),
            ('idle', distbuild.BuildController, distbuild.BuildFinished,
                'idle', self._send_build_finished_message),
            ('idle', distbuild.BuildController, distbuild.BuildFailed,
                'idle', self._send_build_failed_message),
            ('idle', distbuild.BuildController, distbuild.BuildProgress, 
                'idle', self._send_build_progress_message),
            ('idle', distbuild.BuildController, distbuild.GraphingStarted,
                'idle', self._send_graphing_started_message),
            ('idle', distbuild.BuildController, distbuild.GraphingFinished,
                'idle', self._send_graphing_finished_message),
            ('idle', distbuild.BuildController, distbuild.CacheState,
                'idle', self._send_cache_state_message),
            ('idle', distbuild.BuildController, distbuild.BuildCancel,
                'idle', self._send_build_cancelled_message),
            ('idle', distbuild.BuildController, distbuild.BuildStepStarted, 
                'idle', self._send_build_step_started_message),
            ('idle', distbuild.BuildController, distbuild.BuildStarted,
                'idle', self._send_build_started_message),
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

        protocol_version = event.msg.get('protocol_version')
        msg_type = event.msg.get('type')

        if (protocol_version == distbuild.protocol.VERSION
            and msg_type in msg_handler
            and distbuild.protocol.is_valid_message(event.msg)):
            try:
                msg_handler[msg_type](event)
            except Exception:
                logging.exception('Error handling msg: %s', event.msg)
        else:
            response = 'Bad request'

            if (protocol_version is not None
                and protocol_version != distbuild.protocol.VERSION):
                # Provide hint to possible cause of bad request
                response += ('\n' + PROTOCOL_VERSION_MISMATCH_RESPONSE %
                                (distbuild.protocol.VERSION, protocol_version))

            logging.info('Invalid message from initiator: %s', event.msg)
            self._refuse_build_request(event.msg, response)

    def _refuse_build_request(self, build_request_message, reason):
        '''Send an error message back to the initiator.

        In order for this to be understood by all versions of Morph, we use the
        'build-failed' message. Morph initiators ignore any messages they don't
        understand right now, so will hang forever without giving feedback if
        we ignore the request without sending 'build-failed'.

        '''
        # If there was no 'id' in the incoming request, we send a fake one in
        # the hope that initiator still does the right thing.
        response_id = build_request_message.get('id', '000')
        msg = distbuild.message('build-failed', id=response_id, reason=reason)
        self.jm.send(msg)
        self._log_send(msg)

    def _handle_build_request(self, event):
        new_id = self._idgen.next()
        self.our_ids.add(new_id)
        self._route_map.add(event.msg['id'], new_id)
        event.msg['id'] = new_id
        build_controller = distbuild.BuildController(
            self, event.msg, self.artifact_cache_server,
            self.morph_instance)
        self.mainloop.add_state_machine(build_controller)
        self.mainloop.build_info.append(build_controller.build_info)

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
        msg = distbuild.message('request-output',
                                message=('\n\n'.join(output_msg)))
        self.jm.send(msg)

    def _handle_build_cancel(self, event):
        requests = self.mainloop.state_machines_of_type(
                                                    distbuild.BuildController)
        for build in requests:
            if build.get_request()['id'] == event.msg['id']:
                self.mainloop.queue_event(InitiatorConnection,
                                          CancelRequest(event.msg['id'],
                                          event.msg['user']))
                msg = distbuild.message('request-output', message=(
                                        'Cancelling build request with ID %s' %
                                        event.msg['id']))
                self.jm.send(msg)
                break
        else:
            msg = distbuild.message('request-output', message=('Given '
                                    'build-request ID does not match any '
                                    'running build IDs.'))
            self.jm.send(msg)

    def _handle_build_status(self, event):
        for build_info in self.mainloop.build_info:
            if build_info['id'] == event.msg['id']:
                msg = distbuild.message('request-output',
                    message=('\nBuild request ID: %s\n  System build: %s\n  '
                             'Build status: %s' % (build_info['id'],
                                                   build_info['morphology'],
                                                   build_info['status'])))

                self.jm.send(msg)
                break
        else:
            msg = distbuild.message('request-output', message=('Given '
                                    'build-request ID does not match any '
                                    'recent build IDs (the status information '
                                    'for this build may have expired).'))
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

    def _send_build_termination_event_msg(self, event, msg_type, **kwargs):
        if event.id in self.our_ids:
            msg= distbuild.message(msg_type,
                                id=self._route_map.get_incoming_id(event.id),
                                **kwargs)
            self._route_map.remove(event.id)
            self.our_ids.remove(event.id)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_finished_message(self, event_source, event):
        self._send_build_termination_event_msg(event, 'build-finished',
                                               urls=event.urls)

    def _send_build_cancelled_message(self, event_source, event):
        self._send_build_termination_event_msg(event, 'build-cancelled',
                                               user=event.user)

    def _send_build_failed_message(self, event_source, event):
        self._send_build_termination_event_msg(event, 'build-failed',
                                               reason=event.reason)

    def _send_build_progress_message(self, event_source, event):
        if event.id in self.our_ids:
            msg = distbuild.message('build-progress',
                id=self._route_map.get_incoming_id(event.id),
                message=event.message_text)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_build_started_message(self, event_source, event):
        logging.debug('InitiatorConnection: build_started: id=%s', event.id)

        if event.id in self.our_ids:
            msg = distbuild.message('build-started', id=event.id)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_graphing_started_message(self, event_source, event):
        logging.debug('InitiatorConnection: graphing_started: id=%s', event.id)

        if event.id in self.our_ids:
            msg = distbuild.message('graphing-started', id=event.id)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_graphing_finished_message(self, event_source, event):
        logging.debug('InitiatorConnection: graphing_finished: id=%s',
                      event.id)

        if event.id in self.our_ids:
            msg = distbuild.message('graphing-finished', id=event.id)
            self.jm.send(msg)
            self._log_send(msg)

    def _send_cache_state_message(self, event_source, event):
        logging.debug('InitiatorConnection: cache_state: id=%s', event.id)

        if event.id in self.our_ids:
            msg = distbuild.message('cache-state',
                                    id=event.id,
                                    unbuilt=event.unbuilt,
                                    total=event.total)
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
        if self._debug_build_output:
            logging.debug('InitiatorConnection: build_output: '
                          'id=%s stdout=%s stderr=%s' %
                          (repr(event.id), repr(event.stdout),
                           repr(event.stderr)))
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

