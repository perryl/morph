# -*- coding: utf-8 -*-
# distbuild/build_controller.py -- control the steps for one build
#
# Copyright © 2012, 2014-2015  Codethink Limited
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
import httplib
import traceback
import urllib
import urlparse
import json

import distbuild


# Artifact build states
UNKNOWN = 'unknown'
UNBUILT = 'not-built'
BUILDING = 'building'
BUILT = 'built'


class _Start(object): pass
class _Annotated(object): pass
class _Built(object): pass


class _GotGraph(object):

    def __init__(self, artifact):
        self.artifact = artifact


class BuildStarted(object):

    def __init__(self, id):
        self.id = id


class BuildCancel(object):

    def __init__(self, id):
        self.id = id


class BuildFinished(object):

    def __init__(self, request_id, urls):
        self.id = request_id
        self.urls = urls


class BuildFailed(object):

    def __init__(self, request_id, reason):
        self.id = request_id
        self.reason = reason


class BuildProgress(object):

    def __init__(self, request_id, message_text):
        self.id = request_id
        self.message_text = message_text


class GraphingStarted(object):

    def __init__(self, id):
        self.id = id


class GraphingFinished(object):

    def __init__(self, id):
        self.id = id


class CacheState(object):

    def __init__(self, id, unbuilt, total):
        self.id = id
        self.unbuilt = unbuilt
        self.total = total


class BuildStepStarted(object):

    def __init__(self, request_id, step_name, worker_name):
        self.id = request_id
        self.step_name = step_name
        self.worker_name = worker_name


class BuildStepAlreadyStarted(BuildStepStarted):

    def __init__(self, request_id, step_name, worker_name):
        super(BuildStepAlreadyStarted, self).__init__(
            request_id, step_name, worker_name)


class BuildOutput(object):

    def __init__(self, request_id, step_name, stdout, stderr):
        self.id = request_id
        self.step_name = step_name
        self.stdout = stdout
        self.stderr = stderr


class BuildStepFinished(object):

    def __init__(self, request_id, step_name):
        self.id = request_id
        self.step_name = step_name


class BuildStepFailed(object):

    def __init__(self, request_id, step_name):
        self.id = request_id
        self.step_name = step_name



class _Abort(object):
    
    pass


def build_step_name(artifact):
    '''Return user-comprehensible name for a given artifact.'''
    return artifact.source_name


def map_build_graph(artifact, callback, components=[]):
    """Run callback on each artifact in the build graph and return result.

    If components is given, then only look at the components given and
    their dependencies. Also, return a list of the components after they
    have had callback called on them.

    """
    result = []
    mapped_components = []
    done = set()
    if components:
        queue = list(components)
    else:
        queue = [artifact]
    while queue:
        a = queue.pop()
        if a not in done:
            result.append(callback(a))
            queue.extend(a.dependencies)
            done.add(a)
            if a in components:
                mapped_components.append(a)
    return result, mapped_components


def find_artifacts(components, artifact):
    found = []
    for a in artifact.walk():
        if a.name in components:
            found.append(a)
    return found


class BuildController(distbuild.StateMachine):

    '''Control one build-request fulfillment.
    
    The initiator sends a build-request message, which causes the 
    InitiatorConnection to instantiate this class to control the steps
    needed to fulfill the request. This state machine builds the
    build graph to determine all the artifacts that need building, then
    builds anything that is not cached.

    '''

    _idgen = distbuild.IdentifierGenerator('BuildController')

    def __init__(self, initiator_connection, build_request_message,
                 artifact_cache_server, morph_instance):
        distbuild.crash_point()
        distbuild.StateMachine.__init__(self, 'init')
        self._initiator_connection = initiator_connection
        self._request = build_request_message
        self._artifact_cache_server = artifact_cache_server
        self._morph_instance = morph_instance
        self._helper_id = None
        self.debug_transitions = False
        self.debug_graph_state = False
        self._debug_build_output = False
        self.allow_detach = build_request_message['allow_detach']

        self.db = distbuild.BuildRequestDB(
                      build_request_message['distbuild_database'],
                      build_request_message['age_max'])
        self.db.add_request(status='graphing',
                            initiator_hostname=self._initiator_connection,
                            **self._request)


    def __repr__(self):
        return '<BuildController at 0x%x, request-id %s>' % (id(self),
                self._request['id'])

    def get_initiator_connection(self):
        return self._initiator_connection

    def get_request(self):
        return self._request

    def update_build_status(self, status, artifact=''):
        new = (status, artifact)
        self.db.update_request_status(self._request['id'], new)

    def setup(self):
        distbuild.crash_point()

        spec = [
            # state, source, event_class, new_state, callback
            ('init', self, _Start, 'graphing', self._start_graphing),
            ('init', distbuild.InitiatorConnection,
                distbuild.InitiatorDisconnect, 'init',
                self._maybe_notify_initiator_disconnected),
            ('init', distbuild.InitiatorConnection,
                distbuild.CancelRequest, 'init',
                self._maybe_notify_build_cancelled),
            ('init', self, _Abort, None, None),


            ('graphing', distbuild.HelperRouter, distbuild.HelperOutput,
                'graphing', self._maybe_collect_graph),
            ('graphing', distbuild.HelperRouter, distbuild.HelperResult,
                'graphing', self._maybe_finish_graph),
            ('graphing', self, _GotGraph,
                'annotating', self._start_annotating),
            ('graphing', self, BuildFailed, None, None),
            ('graphing', distbuild.InitiatorConnection,
                distbuild.CancelRequest, 'graphing',
                self._maybe_notify_build_cancelled),
            ('graphing', distbuild.InitiatorConnection,
                distbuild.InitiatorDisconnect, 'graphing',
                self._maybe_notify_initiator_disconnected),
            ('graphing', self, _Abort, None, None),

            ('annotating', distbuild.HelperRouter, distbuild.HelperResult,
                'annotating', self._maybe_handle_cache_response),
            ('annotating', self, BuildFailed, None, None),
            ('annotating', self, _Annotated, 'building', 
                self._start_building),
            ('annotating', distbuild.InitiatorConnection,
                distbuild.CancelRequest, 'annotating',
                self._maybe_notify_build_cancelled),
            ('annotating', distbuild.InitiatorConnection,
                distbuild.InitiatorDisconnect, 'annotating',
                self._maybe_notify_initiator_disconnected),
            ('annotating', self, _Abort, None, None),

            # The exact WorkerConnection that is doing our building changes
            # from build to build. We must listen to all messages from all
            # workers, and choose whether to change state inside the callback.
            # (An alternative would be to manage a set of temporary transitions
            # specific to WorkerConnection instances that our currently
            # building for us, but the state machines are not intended to
            # behave that way).

            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildStepStarted, 'building',
                self._maybe_relay_build_step_started),
            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildOutput, 'building',
                self._maybe_relay_build_output),
            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildCaching, 'building',
                self._maybe_relay_build_caching),
            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildStepAlreadyStarted, 'building',
                self._maybe_relay_build_step_already_started),
            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildWaiting, 'building',
                self._maybe_relay_build_waiting_for_worker),
            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildFinished, 'building',
                self._maybe_check_result_and_queue_more_builds),
            ('building', distbuild.WorkerConnection,
                distbuild.WorkerBuildFailed, 'building',
                self._maybe_notify_build_failed),
            ('building', self, _Abort, None, None),
            ('building', self, _Built, None, self._notify_build_done),
            ('building', distbuild.InitiatorConnection,
                distbuild.CancelRequest, 'building',
                self._maybe_notify_build_cancelled),
            ('building', distbuild.InitiatorConnection,
                distbuild.InitiatorDisconnect, 'building',
                self._maybe_notify_initiator_disconnected),
        ]
        self.add_transitions(spec)
    
        self.mainloop.queue_event(self, _Start())

    def fail(self, reason):
        logging.error(reason)
        message = BuildFailed(self._request['id'], reason)

        # The message is sent twice so that it can be matched both by state
        # transitions listening for this specific controller instance, and by
        # state transitions listening for messages from the BuildController
        # class that then filter the message based on the request ID field.
        self.mainloop.queue_event(self, message)
        self.mainloop.queue_event(BuildController, message)

    def _request_command_execution(self, argv, request_id):
        '''Tell the controller's distbuild-helper to run a command.'''
        hrs = self.mainloop.state_machines_of_type(distbuild.HelperRouter)
        if len(hrs) == 0:
            self.fail('No distbuild-helper process running on controller!')

        msg = distbuild.message('exec-request',
            id=request_id,
            argv=argv,
            stdin_contents='')
        req = distbuild.HelperRequest(msg)
        self.mainloop.queue_event(distbuild.HelperRouter, req)

    def _start_graphing(self, event_source, event):
        distbuild.crash_point()

        logging.info('Start constructing build graph')
        self._artifact_data = distbuild.StringBuffer()
        self._artifact_error = distbuild.StringBuffer()
        argv = [
            self._morph_instance,
            'calculate-build-graph',
            '--quiet',
            self._request['repo'],
            self._request['ref'],
            self._request['morphology'],
        ]
        if 'original_ref' in self._request:
            argv.append(self._request['original_ref'])

        self._helper_id = self._idgen.next()
        self._request_command_execution(argv, self._helper_id)

        self.mainloop.queue_event(BuildController,
                                  GraphingStarted(self._request['id']))

    def _maybe_collect_graph(self, event_source, event):
        distbuild.crash_point()

        if event.msg['id'] == self._helper_id:
            self._artifact_data.add(event.msg['stdout'])
            self._artifact_error.add(event.msg['stderr'])

    def _maybe_finish_graph(self, event_source, event):
        distbuild.crash_point()

        def notify_success(artifact):
            logging.debug('Graph is finished')

            self.mainloop.queue_event(BuildController,
                                      GraphingFinished(self._request['id']))

            self.mainloop.queue_event(self, _GotGraph(artifact))

        if event.msg['id'] == self._helper_id:
            self._helper_id = None

            error_text = self._artifact_error.peek()
            if event.msg['exit'] != 0 or error_text:
                self.fail(error_text)

            if event.msg['exit'] != 0:
                return
            
            text = self._artifact_data.peek()
            try:
                artifact = distbuild.decode_artifact_reference(text)
            except ValueError as e:
                logging.error(traceback.format_exc())
                self.fail('Failed to compute build graph: %s' % e)
                return

            notify_success(artifact)

    def _start_annotating(self, event_source, event):
        distbuild.crash_point()

        self._artifact = event.artifact
        names = self._request['component_names']
        self._components = find_artifacts(names, self._artifact)
        not_found = []
        for component in names:
            found_names = [c.source_name for c in self._components]
            if component not in found_names:
                logging.debug('Failed to find %s in build graph'
                              % component)
                not_found.append(component)
        if not_found:
            self.fail('Some of the requested components are not in %s: %s'
                      % (self._artifact.name, ', '.join(not_found)))
        self._helper_id = self._idgen.next()
        artifact_names = []

        def set_state_and_append(artifact):
            artifact.state = UNKNOWN
            artifact_names.append(artifact.basename())

        _, self._components = map_build_graph(self._artifact,
                                              set_state_and_append,
                                              self._components)

        url = urlparse.urljoin(self._artifact_cache_server, '/1.0/artifacts')
        msg = distbuild.message('http-request',
            id=self._helper_id,
            url=url,
            headers={'Content-type': 'application/json'},
            body=json.dumps(artifact_names),
            method='POST')

        request = distbuild.HelperRequest(msg)
        self.mainloop.queue_event(distbuild.HelperRouter, request)
        logging.debug('Made cache request for state of artifacts '
            '(helper id: %s)' % self._helper_id)

    def _maybe_handle_cache_response(self, event_source, event):
        def set_status(artifact):
            is_in_cache = cache_state[artifact.basename()]
            artifact.state = BUILT if is_in_cache else UNBUILT

        if self._helper_id != event.msg['id']:
            return    # this event is not for us

        logging.debug('Got cache response: %s' % repr(event.msg))

        http_status_code = event.msg['status']

        if http_status_code != httplib.OK:
            self.fail('Failed to annotate build graph: HTTP request to %s got '
                      '%d: %s' % (self._artifact_cache_server,
                                  http_status_code, event.msg['body']))
            return

        cache_state = json.loads(event.msg['body'])
        _, self._components = map_build_graph(self._artifact, set_status,
                                              self._components)
        self.mainloop.queue_event(self, _Annotated())

        unbuilt = set()
        for c in self._components:
            unbuilt.update([a for a in c.walk() if a.state == UNBUILT])
        unbuilt = len(unbuilt) or len([a for a in self._artifact.walk()
                                       if a.state == UNBUILT])
        total = set()
        for c in self._components:
            total.update([a for a in c.walk()])
        total = len(total) or len([a for _ in self._artifact.walk()])

        cache_state_msg = CacheState(self._request['id'], unbuilt, total)
        self.mainloop.queue_event(BuildController, cache_state_msg)

        if total == 0:
            logging.info('There seems to be nothing to build')
            self.mainloop.queue_event(self, _Built())

    def _find_artifacts_that_are_ready_to_build(self):
        def is_ready_to_build(artifact):
            return (artifact.state == UNBUILT and
                    all(a.state == BUILT
                        for a in artifact.dependencies))

        artifacts, _ = map_build_graph(self._artifact, lambda a: a,
                                       self._components)
        return [a for a in artifacts if is_ready_to_build(a)]

    def _build_complete(self):
        if not self._components:
            if self._artifact.state == BUILT:
                logging.info('Requested artifact is built')
                self.mainloop.queue_event(self, _Built())
                return True
        else:
            if not any(c.state != BUILT for c in self._components):
                logging.info('Requested components are built')
                self.mainloop.queue_event(self, _Built())
                return True
        return False

    def _start_building(self, event_source, event):
        if self._build_complete():
            return

        self.mainloop.queue_event(BuildController,
                                  BuildStarted(self._request['id']))
        self._queue_worker_builds(event_source, event)

    def _queue_worker_builds(self, event_source, event):
        distbuild.crash_point()

        if self._build_complete():
            return

        logging.debug('Queuing more worker-builds to run')
        if self.debug_graph_state:
            logging.debug('Current state of build graph nodes:')
            for a, _ in map_build_graph(self._artifact,
                                        lambda a: a, self._components):
                logging.debug('  %s state is %s' % (a.name, a.state))
                if a.state != BUILT:
                    for dep in a.dependencies:
                        logging.debug(
                            '    depends on %s which is %s' %
                                (dep.name, dep.state))

        while True:
            ready = self._find_artifacts_that_are_ready_to_build()

            if len(ready) == 0:
                logging.debug('No new artifacts queued for building')
                break

            artifact = ready[0]

            logging.debug(
                'Requesting worker-build of %s (%s)' %
                    (artifact.name, artifact.cache_key))
            request = distbuild.WorkerBuildRequest(artifact,
                                                   self._request['id'])
            self.mainloop.queue_event(distbuild.WorkerBuildQueuer, request)

            artifact.state = BUILDING
            if artifact.kind == 'chunk':
                # Chunk artifacts are not built independently
                # so when we're building any chunk artifact
                # we're also building all the chunk artifacts
                # in this source
                for a in ready:
                    if a.cache_key == artifact.cache_key:
                        a.state = BUILDING

    def _maybe_notify_initiator_disconnected(self, event_source, event):
        if event.id != self._request['id']:
            logging.debug('Heard initiator disconnect with event id %s '
                          'but our request id is %s',
                          event.id, self._request['id'])
            return  # not for us

        logging.debug("BuildController %r: initiator id %s disconnected",
            self, event.id)

        if self.allow_detach:
            logging.debug('Detaching from client; build continuing remotely.')
        else:
            self.mainloop.queue_event(BuildController, distbuild.CancelRequest)

    def _maybe_notify_build_cancelled(self, event_source, event):
        if event.id != self._request['id']:
            logging.debug('Heard initiator cancel request with event id %s '
                          'but our request id is %s',
                          event.id, self._request['id'])
            return  # not for us

        logging.debug("BuildController %r: initiator id %s cancelled",
            self, event.id)

        self.update_build_status('cancelled')
        cancel_pending = distbuild.WorkerCancelPending(event.id)
        self.mainloop.queue_event(distbuild.WorkerBuildQueuer,
                                  cancel_pending)

        cancel = BuildCancel(event.id)
        self.mainloop.queue_event(BuildController, cancel)

        self.mainloop.queue_event(self, _Abort())

    def _maybe_relay_build_waiting_for_worker(self, event_source, event):
        if event.initiator_id != self._request['id']:
            return # not for us

        artifact = self._find_artifact(event.artifact_cache_key)
        if artifact is None:
            # This is not the event you are looking for.
            return

        self.update_build_status('waiting')
        progress = BuildProgress(
            self._request['id'],
            'Ready to build %s: waiting for a worker to become available'
            % artifact.name)
        self.mainloop.queue_event(BuildController, progress)

    def _maybe_relay_build_step_started(self, event_source, event):
        distbuild.crash_point()
        if self._request['id'] not in event.initiators:
            return # not for us

        logging.debug(
            'BC: _relay_build_step_started: %s' % event.artifact_cache_key)

        artifact = self._find_artifact(event.artifact_cache_key)
        if artifact is None:
            # This is not the event you are looking for.
            return

        logging.debug('BC: got build step started: %s' % artifact.name)
        self.update_build_status('building', artifact.name)
        started = BuildStepStarted(
            self._request['id'], build_step_name(artifact), event.worker_name)
        self.mainloop.queue_event(BuildController, started)
        logging.debug('BC: emitted %s' % repr(started))

    def _maybe_relay_build_step_already_started(self, event_source, event):
        if event.initiator_id != self._request['id']:
            return  # not for us

        artifact = self._find_artifact(event.artifact_cache_key)

        logging.debug('BC: got build step already started: %s' % artifact.name)
        self.update_build_status('building', artifact.name)
        started = BuildStepAlreadyStarted(
            self._request['id'], build_step_name(artifact), event.worker_name)
        self.mainloop.queue_event(BuildController, started)
        logging.debug('BC: emitted %s' % repr(started))

    def _maybe_relay_build_output(self, event_source, event):
        distbuild.crash_point()
        if self._request['id'] not in event.msg['ids']:
            return # not for us

        if self._debug_build_output:
            logging.debug('BC: got output: %s' % repr(event.msg))

        artifact = self._find_artifact(event.artifact_cache_key)
        logging.debug('BC: got artifact: %s' % repr(artifact))
        if artifact is None:
            # This is not the event you are looking for.
            return

        output = BuildOutput(
            self._request['id'], build_step_name(artifact),
            event.msg['stdout'], event.msg['stderr'])
        self.mainloop.queue_event(BuildController, output)

        if self._debug_build_output:
            logging.debug('BC: queued %s' % repr(output))

    def _maybe_relay_build_caching(self, event_source, event):
        distbuild.crash_point()

        if self._request['id'] not in event.initiators:
            return # not for us

        artifact = self._find_artifact(event.artifact_cache_key)
        if artifact is None:
            # This is not the event you are looking for.
            return

        progress = BuildProgress(
            self._request['id'],
            'Transferring %s to shared artifact cache' % artifact.name)
        self.mainloop.queue_event(BuildController, progress)

    def _find_artifact(self, cache_key):
        artifacts, _ = map_build_graph(self._artifact, lambda a: a,
                                       self._components)
        wanted = [a for a in artifacts if a.cache_key == cache_key]
        if wanted:
            return wanted[0]
        else:
            return None
            
    def _maybe_check_result_and_queue_more_builds(self, event_source, event):
        distbuild.crash_point()
        if self._request['id'] not in event.msg['ids']:
            return # not for us

        artifact = self._find_artifact(event.artifact_cache_key)
        if artifact is None:
            # This is not the event you are looking for.
            return

        logging.debug(
            'Got build result for %s: %s', artifact.name, repr(event.msg))

        finished = BuildStepFinished(
            self._request['id'], build_step_name(artifact))
        self.mainloop.queue_event(BuildController, finished)

        artifact.state = BUILT

        def set_state(a):
            if a.cache_key == artifact.cache_key:
                a.state = BUILT

        if artifact.kind == 'chunk':
            # Building a single chunk artifact
            # yields all chunk artifacts for the given source
            # so we set the state of this source's artifacts
            # to BUILT
            _, self._components = map_build_graph(self._artifact, set_state,
                                                  self._components)

        self._queue_worker_builds(None, event)

    def _maybe_notify_build_failed(self, event_source, event):
        distbuild.crash_point()

        if self._request['id'] not in event.msg['ids']:
            return  # not for us

        artifact = self._find_artifact(event.artifact_cache_key)

        if artifact is None:
            logging.error(
                'BuildController %r: artifact %s is not in our build graph!',
                self, artifact)
            # We abort the build in this case on the grounds that something is
            # very wrong internally, and it's best for the initiator to receive
            # an error than to be left hanging.
            self.mainloop.queue_event(self, _Abort())

        logging.info(
            'Build step failed for %s: %s', artifact.name, repr(event.msg))

        step_failed = BuildStepFailed(
            self._request['id'], build_step_name(artifact))
        self.mainloop.queue_event(BuildController, step_failed)

        self.fail('Building failed for %s' % artifact.name)
        self.update_build_status('failed', artifact.name)

        # Cancel any jobs waiting to be executed, since there is no point
        # running them if this build has failed, it would just waste
        # resources
        cancel_pending = distbuild.WorkerCancelPending(
            self._request['id'])
        self.mainloop.queue_event(distbuild.WorkerBuildQueuer, cancel_pending)

        # Cancel any currently executing jobs for the above reasons, since
        # this build will fail and we can't decide whether these jobs will
        # be of use to any other build
        cancel = BuildCancel(self._request['id'])
        self.mainloop.queue_event(BuildController, cancel)

        self.mainloop.queue_event(self, _Abort())

    def _notify_build_done(self, event_source, event):
        distbuild.crash_point()

        logging.debug('Notifying initiator of successful build')
        self.update_build_status('finished')
        baseurl = urlparse.urljoin(
            self._artifact_cache_server, '/1.0/artifacts')
        urls = []
        for c in self._components:
            name = ('%s.%s.%s' %
                (c.cache_key,
                 c.kind,
                 c.name))
            urls.append('%s?filename=%s' % (baseurl, urllib.quote(name)))
        if not self._components:
            name = ('%s.%s.%s' %
                (self._artifact.cache_key,
                 self._artifact.kind,
                 self._artifact.name))
            urls.append('%s?filename=%s' % (baseurl, urllib.quote(name)))

        finished = BuildFinished(self._request['id'], urls)
        self.mainloop.queue_event(BuildController, finished)
