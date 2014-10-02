# distbuild/build_controller.py -- control the steps for one build
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

class _AnnotationFailed(object):

    def __init__(self, http_status_code, error_msg):
        self.http_status_code = http_status_code
        self.error_msg = error_msg

class _GotGraph(object):

    def __init__(self, artifact):
        self.artifact = artifact


class _GraphFailed(object):

    pass


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


class BuildSteps(object):

    def __init__(self, request_id, artifact):
        self.id = request_id
        self.artifact = artifact


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
    return artifact.name


def map_build_graph(artifact, callback):
    result = []
    done = set()
    queue = [artifact]
    while queue:
        a = queue.pop()
        if a not in done:
            result.append(callback(a))
            queue.extend(a.source.dependencies)
            done.add(a)
    return result


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

    def __repr__(self):
        return '<BuildController at 0x%x, request-id %s>' % (id(self),
                self._request['id'])

    def setup(self):
        distbuild.crash_point()

        spec = [
            # state, source, event_class, new_state, callback
            ('init', self, _Start, 'graphing', self._start_graphing),
            ('init', self._initiator_connection,
                distbuild.InitiatorDisconnect, None, None),

            ('graphing', distbuild.HelperRouter, distbuild.HelperOutput,
                'graphing', self._maybe_collect_graph),
            ('graphing', distbuild.HelperRouter, distbuild.HelperResult,
                'graphing', self._maybe_finish_graph),
            ('graphing', self, _GotGraph,
                'annotating', self._start_annotating),
            ('graphing', self, _GraphFailed, None, None),
            ('graphing', self._initiator_connection,
                distbuild.InitiatorDisconnect, None, None),

            ('annotating', distbuild.HelperRouter, distbuild.HelperResult,
                'annotating', self._maybe_handle_cache_response),
            ('annotating', self, _AnnotationFailed, None,
                self._notify_annotation_failed),
            ('annotating', self, _Annotated, 'building', 
                self._queue_worker_builds),
            ('annotating', self._initiator_connection,
                distbuild.InitiatorDisconnect, None, None),

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
                distbuild.InitiatorDisconnect, 'building',
                self._maybe_notify_initiator_disconnected),
        ]
        self.add_transitions(spec)
    
        self.mainloop.queue_event(self, _Start())

    def _start_graphing(self, event_source, event):
        distbuild.crash_point()

        logging.info('Start constructing build graph')
        self._artifact_data = distbuild.StringBuffer()
        self._artifact_error = distbuild.StringBuffer()
        argv = [
            self._morph_instance,
            'serialise-artifact',
            '--quiet',
            self._request['repo'],
            self._request['ref'],
            self._request['morphology'],
        ]
        msg = distbuild.message('exec-request',
            id=self._idgen.next(),
            argv=argv,
            stdin_contents='')
        self._helper_id = msg['id']
        req = distbuild.HelperRequest(msg)
        self.mainloop.queue_event(distbuild.HelperRouter, req)
        
        progress = BuildProgress(self._request['id'], 'Computing build graph')
        self.mainloop.queue_event(BuildController, progress)

    def _maybe_collect_graph(self, event_source, event):
        distbuild.crash_point()

        if event.msg['id'] == self._helper_id:
            self._artifact_data.add(event.msg['stdout'])
            self._artifact_error.add(event.msg['stderr'])

    def _maybe_finish_graph(self, event_source, event):
        distbuild.crash_point()

        def notify_failure(msg_text):
            logging.error('Graph creation failed: %s' % msg_text)
            
            failed = BuildFailed(
                self._request['id'], 
                'Failed to compute build graph: %s' % msg_text)
            self.mainloop.queue_event(BuildController, failed)
            
            self.mainloop.queue_event(self, _GraphFailed())

        def notify_success(artifact):
            logging.debug('Graph is finished')

            progress = BuildProgress(
                self._request['id'], 'Finished computing build graph')
            self.mainloop.queue_event(BuildController, progress)
            
            build_steps = BuildSteps(self._request['id'], artifact)
            self.mainloop.queue_event(BuildController, build_steps)

            self.mainloop.queue_event(self, _GotGraph(artifact))

        if event.msg['id'] == self._helper_id:
            self._helper_id = None

            error_text = self._artifact_error.peek()
            if event.msg['exit'] != 0 or error_text:
                notify_failure('Problem with serialise-artifact: %s'
                    % error_text)

            if event.msg['exit'] != 0:
                return
            
            text = self._artifact_data.peek()
            try:
                artifact = distbuild.deserialise_artifact(text)
            except ValueError, e:
                logging.error(traceback.format_exc())
                notify_failure(str(e))
                return

            notify_success(artifact)

    def _start_annotating(self, event_source, event):
        distbuild.crash_point()

        self._artifact = event.artifact
        self._helper_id = self._idgen.next()
        artifact_names = []

        def set_state_and_append(artifact):
            artifact.state = UNKNOWN
            artifact_names.append(artifact.basename())

        map_build_graph(self._artifact, set_state_and_append)

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
        error_msg = event.msg['body']

        if http_status_code != httplib.OK:
            logging.debug('Cache request failed with status: %s'
                % event.msg['status'])
            self.mainloop.queue_event(self,
                _AnnotationFailed(http_status_code, error_msg))
            return

        cache_state = json.loads(event.msg['body'])
        map_build_graph(self._artifact, set_status)
        self.mainloop.queue_event(self, _Annotated())

        count = sum(map_build_graph(self._artifact,
                    lambda a: 1 if a.state == UNBUILT else 0))

        progress = BuildProgress(
            self._request['id'],
            'Need to build %d artifacts' % count)
        self.mainloop.queue_event(BuildController, progress)

        if count == 0:
            logging.info('There seems to be nothing to build')
            self.mainloop.queue_event(self, _Built())

    def _find_artifacts_that_are_ready_to_build(self):
        def is_ready_to_build(artifact):
            return (artifact.state == UNBUILT and
                    all(a.state == BUILT
                        for a in artifact.source.dependencies))

        return [a 
                for a in map_build_graph(self._artifact, lambda a: a)
                if is_ready_to_build(a)]

    def _queue_worker_builds(self, event_source, event):
        distbuild.crash_point()

        if self._artifact.state == BUILT:
            logging.info('Requested artifact is built')
            self.mainloop.queue_event(self, _Built())
            return

        logging.debug('Queuing more worker-builds to run')
        if self.debug_graph_state:
            logging.debug('Current state of build graph nodes:')
            for a in map_build_graph(self._artifact, lambda a: a):
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
                    (artifact.name, artifact.source.cache_key))
            request = distbuild.WorkerBuildRequest(artifact,
                                                   self._request['id'])
            self.mainloop.queue_event(distbuild.WorkerBuildQueuer, request)

            artifact.state = BUILDING
            if artifact.source.morphology['kind'] == 'chunk':
                # Chunk artifacts are not built independently
                # so when we're building any chunk artifact
                # we're also building all the chunk artifacts
                # in this source
                for a in ready:
                    if a.source == artifact.source:
                        a.state = BUILDING


    def _maybe_notify_initiator_disconnected(self, event_source, event):
        if event.id != self._request['id']:
            logging.debug('Heard initiator disconnect with event id %d '
                          'but our request id is %d',
                          event.id, self._request['id'])
            return  # not for us

        logging.debug("BuildController %r: initiator id %s disconnected",
            self, event.id)

        cancel_pending = distbuild.WorkerCancelPending(event.id)
        self.mainloop.queue_event(distbuild.WorkerBuildQueuer, cancel_pending)

        cancel = BuildCancel(event.id)
        self.mainloop.queue_event(BuildController, cancel)

        self.mainloop.queue_event(self, _Abort)

    def _maybe_relay_build_waiting_for_worker(self, event_source, event):
        if event.initiator_id != self._request['id']:
            return # not for us

        artifact = self._find_artifact(event.artifact_cache_key)
        if artifact is None:
            # This is not the event you are looking for.
            return

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
        started = BuildStepStarted(
            self._request['id'], build_step_name(artifact), event.worker_name)
        self.mainloop.queue_event(BuildController, started)
        logging.debug('BC: emitted %s' % repr(started))

    def _maybe_relay_build_step_already_started(self, event_source, event):
        if event.initiator_id != self._request['id']:
            return  # not for us

        artifact = self._find_artifact(event.artifact_cache_key)

        logging.debug('BC: got build step already started: %s' % artifact.name)
        started = BuildStepAlreadyStarted(
            self._request['id'], build_step_name(artifact), event.worker_name)
        self.mainloop.queue_event(BuildController, started)
        logging.debug('BC: emitted %s' % repr(started))

    def _maybe_relay_build_output(self, event_source, event):
        distbuild.crash_point()
        if self._request['id'] not in event.msg['ids']:
            return # not for us

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
        artifacts = map_build_graph(self._artifact, lambda a: a)
        wanted = [a for a in artifacts if a.source.cache_key == cache_key]
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
            if a.source == artifact.source:
                a.state = BUILT

        if artifact.source.morphology['kind'] == 'chunk':
            # Building a single chunk artifact
            # yields all chunk artifacts for the given source
            # so we set the state of this source's artifacts
            # to BUILT
            map_build_graph(self._artifact, set_state)

        self._queue_worker_builds(None, event)

    def _notify_annotation_failed(self, event_source, event):
        errmsg = ('Failed to annotate build graph: http request got %d: %s'
                  % (event.http_status_code, event.error_msg))

        logging.error(errmsg)
        failed = BuildFailed(self._request['id'], errmsg)
        self.mainloop.queue_event(BuildController, failed)

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

        build_failed = BuildFailed(
            self._request['id'], 
            'Building failed for %s' % artifact.name)
        self.mainloop.queue_event(BuildController, build_failed)

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
        baseurl = urlparse.urljoin(
            self._artifact_cache_server, '/1.0/artifacts')
        filename = ('%s.%s.%s' % 
            (self._artifact.source.cache_key,
             self._artifact.source.morphology['kind'],
             self._artifact.name))
        url = '%s?filename=%s' % (baseurl, urllib.quote(filename))
        finished = BuildFinished(self._request['id'], [url])
        self.mainloop.queue_event(BuildController, finished)
