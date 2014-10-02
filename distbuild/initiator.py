# distbuild/initiator.py -- state machine for the initiator
#
# Copyright (C) 2012, 2014  Codethink Limited
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


import cliapp
import logging
import os
import random
import sys

import distbuild


class _Finished(object):

    def __init__(self, msg):
        self.msg = msg


class _Failed(object):

    def __init__(self, msg):
        self.msg = msg


class Initiator(distbuild.StateMachine):

    def __init__(self, cm, conn, app, repo_name, ref, morphology):
        distbuild.StateMachine.__init__(self, 'waiting')
        self._cm = cm
        self._conn = conn
        self._app = app
        self._repo_name = repo_name
        self._ref = ref
        self._morphology = morphology
        self._steps = None
        self._step_outputs = {}
        self._step_output_dir = app.settings['initiator-step-output-dir']
        self.debug_transitions = False

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

        random_id = random.randint(0, 2**32-1)

        self._app.status(
            msg='Requesting build of %(repo)s %(ref)s %(morph)s',
            repo=self._repo_name,
            ref=self._ref,
            morph=self._morphology)
        msg = distbuild.message('build-request',
            id=random_id,
            repo=self._repo_name,
            ref=self._ref,
            morphology=self._morphology
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
            'build-steps': self._handle_build_steps_message,
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

    def _handle_build_steps_message(self, msg):
        self._steps = msg['steps']
        self._app.status(
            msg='Build steps in total: %(steps)d',
            steps=len(self._steps))

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

    def _handle_step_already_started_message(self, msg):
        self._app.status(
            msg='%s is already building on %s' % (msg['step_name'],
                msg['worker_name']))
        self._open_output(msg)

    def _handle_step_started_message(self, msg):
        self._app.status(
            msg='Started building %(step_name)s on %(worker_name)s',
            step_name=msg['step_name'],
            worker_name=msg['worker_name'])
        self._open_output(msg)

    def _handle_step_output_message(self, msg):
        step_name = msg['step_name']
        if step_name in self._step_outputs:
            f = self._step_outputs[step_name]
            f.write(msg['stdout'])
            f.write(msg['stderr'])
            f.flush()
        else:
            logging.warning(
                'Got step-output message for unknown step: %s' % repr(msg))

    def _handle_step_finished_message(self, msg):
        step_name = msg['step_name']
        if step_name in self._step_outputs:
            self._app.status(
                msg='Finished building %(step_name)s',
                step_name=step_name)
            self._close_output(msg)
        else:
            logging.warning(
                'Got step-finished message for unknown step: %s' % repr(msg))

    def _handle_step_failed_message(self, msg):
        step_name = msg['step_name']
        if step_name in self._step_outputs:
            self._app.status(
                msg='Build failed: %(step_name)s',
                step_name=step_name)
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

