# distbuild/initiator.py -- state machine for the initiator
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


import cliapp
import itertools
import logging
import os
import uuid
import time

import distbuild


class _Finished(object):

    def __init__(self, msg):
        self.msg = msg


class _Failed(object):

    def __init__(self, msg):
        self.msg = msg


def create_build_directory(prefix='build'):
    '''Create a new directory to store build logs.

    The directory will be named build-0, unless that directory already exists,
    in which case it will be named build-1, and so on.

    '''
    for i in itertools.count():
        path = '%s-%02i' % (prefix, i)
        if not os.path.exists(path):
            os.mkdir(path)
            return path


class Initiator(distbuild.StateMachine):

    def __init__(self, cm, conn, app, repo_name, ref, morphology,
                 original_ref, component_names):
        distbuild.StateMachine.__init__(self, 'waiting')
        self._cm = cm
        self._conn = conn
        self._app = app
        self._repo_name = repo_name
        self._ref = ref
        self._morphology = morphology
        self._original_ref = original_ref
        self._component_names = component_names
        self._partial = False
        if self._component_names:
            self._partial = True
        self._step_outputs = {}
        self.debug_transitions = False

        if app.settings['initiator-step-output-dir'] == '':
            self._step_output_dir = create_build_directory()
        else:
            self._step_output_dir = app.settings['initiator-step-output-dir']

    def setup(self):
        distbuild.crash_point()

        self._jm = distbuild.JsonMachine(self._conn)
        self.mainloop.add_state_machine(self._jm)
        logging.debug('initiator: _jm=%s' % repr(self._jm))
        
        spec = [
            # state, source, event_class, new_state, callback
            ('waiting', self._jm, distbuild.JsonEof, None, self._terminate),
            ('waiting', self._jm, distbuild.JsonNewMessage, 'waiting',
                self._handle_json_message),
            ('waiting', self, _Finished, None, self._succeed),
            ('waiting', self, _Failed, None, self._fail),
        ]
        self.add_transitions(spec)

        msg_uuid = uuid.uuid4().hex

        self._app.status(
            msg='Requesting build of %(repo)s %(ref)s %(morph)s',
            repo=self._repo_name,
            ref=self._ref,
            morph=self._morphology)
        msg = distbuild.message('build-request',
            id=msg_uuid,
            repo=self._repo_name,
            ref=self._ref,
            morphology=self._morphology,
            original_ref=self._original_ref,
            component_names=self._component_names,
            partial=self._partial,
            protocol_version=distbuild.protocol.VERSION
        )
        self._jm.send(msg)
        logging.debug('Initiator: sent to controller: %s', repr(msg))

    def _handle_json_message(self, event_source, event):
        distbuild.crash_point()

        logging.debug('Initiator: from controller: %s' % repr(event.msg))

        handlers = {
            'build-finished': self._handle_build_finished_message,
            'build-failed': self._handle_build_failed_message,
            'build-progress': self._handle_build_progress_message,
            'step-started': self._handle_step_started_message,
            'step-already-started': self._handle_step_already_started_message,
            'step-output': self._handle_step_output_message,
            'step-finished': self._handle_step_finished_message,
            'step-failed': self._handle_step_failed_message,
        }
        
        handler = handlers[event.msg['type']]
        handler(event.msg)

    def _handle_build_finished_message(self, msg):
        self.mainloop.queue_event(self, _Finished(msg))

    def _handle_build_failed_message(self, msg):
        self.mainloop.queue_event(self, _Failed(msg))

    def _handle_build_progress_message(self, msg):
        self._app.status(msg='Progress: %(msgtext)s', msgtext=msg['message'])

    def _open_output(self, msg):
        assert msg['step_name'] not in self._step_outputs
        if self._step_output_dir:
            filename = os.path.join(self._step_output_dir,
                                    'build-step-%s.log' % msg['step_name'])
        else:
            filename = '/dev/null'
        f = open(filename, 'a')
        self._step_outputs[msg['step_name']] = f

    def _close_output(self, msg):
        self._step_outputs[msg['step_name']].close()
        del self._step_outputs[msg['step_name']]

    def _get_output(self, msg):
        return self._step_outputs[msg['step_name']]

    def _write_status_to_build_log(self, f, status):
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + status + '\n')
        f.flush()

    def _handle_step_already_started_message(self, msg):
        status = '%s is already building on %s' % (
            msg['step_name'], msg['worker_name'])
        self._app.status(msg=status)

        self._open_output(msg)
        self._write_status_to_build_log(self._get_output(msg), status)

    def _handle_step_started_message(self, msg):
        status = 'Started building %s on %s' % (
            msg['step_name'], msg['worker_name'])
        self._app.status(msg=status)

        self._open_output(msg)
        self._write_status_to_build_log(self._get_output(msg), status)

    def _handle_step_output_message(self, msg):
        step_name = msg['step_name']
        if step_name in self._step_outputs:
            f = self._get_output(msg)
            f.write(msg['stdout'])
            f.write(msg['stderr'])
            f.flush()
        else:
            logging.warning(
                'Got step-output message for unknown step: %s' % repr(msg))

    def _handle_step_finished_message(self, msg):
        step_name = msg['step_name']
        if step_name in self._step_outputs:
            status = 'Finished building %s' % step_name
            self._app.status(msg=status)

            self._write_status_to_build_log(self._get_output(msg), status)
            self._close_output(msg)
        else:
            logging.warning(
                'Got step-finished message for unknown step: %s' % repr(msg))

    def _handle_step_failed_message(self, msg):
        step_name = msg['step_name']
        if step_name in self._step_outputs:
            status = 'Build of %s failed.' % step_name
            self._app.status(msg=status)

            self._write_status_to_build_log(self._get_output(msg), status)
            self._close_output(msg)
        else:
            logging.warning(
                'Got step-failed message for unknown step: %s' % repr(msg))

    def _succeed(self, event_source, event):
        self.mainloop.queue_event(self._cm, distbuild.StopConnecting())
        self._jm.close()
        logging.info('Build finished OK')
        
        urls = event.msg['urls']
        if urls:
            for url in urls:
                self._app.status(msg='Artifact: %(url)s', url=url)
        else:
            self._app.status(
                msg='Controller did not give us any artifact URLs.')

    def _fail(self, event_source, event):
        self.mainloop.queue_event(self._cm, distbuild.StopConnecting())
        self._jm.close()
        raise cliapp.AppException(
            'Failed to build %s %s %s: %s' % 
                (self._repo_name, self._ref, self._morphology, 
                 event.msg['reason']))

    def _terminate(self, event_source, event):
        self.mainloop.queue_event(self._cm, distbuild.StopConnecting())
        self._jm.close()

    def handle_cancel(self):
        # Note in each build-step.log file that the initiator cancelled: this
        # makes it easier to tell whether a build was aborted due to a bug or
        # dropped connection, or if the user cancelled with CTRL+C / SIGINT.

        for f in self._step_outputs.itervalues():
            self._write_status_to_build_log(f, 'Initiator cancelled')
            f.close()

        self._step_outputs = {}


class InitiatorListJobs(distbuild.StateMachine):

    def __init__(self, cm, conn, app):
        distbuild.StateMachine.__init__(self, 'waiting')
        self._cm = cm
        self._conn = conn
        self._app = app

    def setup(self):
        distbuild.crash_point()

        self._jm = distbuild.JsonMachine(self._conn)
        self.mainloop.add_state_machine(self._jm)
        logging.debug('initiator: _jm=%s' % repr(self._jm))

        spec = [
            # state, source, event_class, new_state, callback
            ('waiting', self._jm, distbuild.JsonEof, None, self._terminate),
            ('waiting', self._jm, distbuild.JsonNewMessage, None,
                self._handle_json_message),
        ]
        self.add_transitions(spec)

        msg_uuid = uuid.uuid4().hex

        self._app.status(msg='Requesting currently running distbuilds.')
        msg = distbuild.message('list-requests',
            id=msg_uuid,
        )
        self._jm.send(msg)
        logging.debug('Initiator: sent to controller: %s', repr(msg))

    def _handle_json_message(self, event_source, event):
        distbuild.crash_point()

        logging.debug('Initiator: from controller: %s', str(event.msg))

        handlers = {
            'list-request-output': self._handle_list_request_output,
        }

        handler = handlers[event.msg['type']]
        handler(event.msg)

    def _handle_list_request_output(self, msg):
        self._app.status(msg=str(msg['message']))
        self.mainloop.queue_event(self._cm, distbuild.StopConnecting())
        self._jm.close()

    def _terminate(self, event_source, event):
        self.mainloop.queue_event(self._cm, distbuild.StopConnecting())
        self._jm.close()
