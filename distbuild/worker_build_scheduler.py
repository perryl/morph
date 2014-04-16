# distbuild/worker_build_scheduler.py -- schedule worker-builds on workers
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


import collections
import errno
import httplib
import logging
import socket
import urllib
import urlparse

import distbuild


class WorkerBuildRequest(object):

    def __init__(self, artifact, initiator_id):
        self.artifact = artifact
        self.initiator_id = initiator_id


class WorkerCancelPending(object):
    
    def __init__(self, initiator_id):
        self.initiator_id = initiator_id    


class WorkerBuildStepStarted(object):

    def __init__(self, initiator_id, cache_key, worker_name):
        self.initiator_id = initiator_id
        self.artifact_cache_key = cache_key
        self.worker_name = worker_name


class WorkerBuildOutput(object):

    def __init__(self, msg, cache_key):
        self.msg = msg
        self.artifact_cache_key = cache_key


class WorkerBuildInProgress(object):
    def __init__(self, initiator_id, cache_key, worker_name):
        self.initiator_id = initiator_id
        self.artifact_cache_key = cache_key
        self.worker_name = worker_name


class WorkerBuildCaching(object):

    def __init__(self, initiator_id, cache_key):
        self.initiator_id = initiator_id
        self.artifact_cache_key = cache_key


class WorkerBuildFinished(object):

    def __init__(self, msg, cache_key):
        self.msg = msg
        self.artifact_cache_key = cache_key
        
        
class WorkerBuildFailed(object):

    def __init__(self, msg, cache_key):
        self.msg = msg
        self.artifact_cache_key = cache_key


class _NeedJob(object):

    def __init__(self, who):
        self.who = who
        

class _HaveAJob(object):

    def __init__(self, artifact, initiator_id):
        self.artifact = artifact
        self.initiator_id = initiator_id

class Job(object):

    def __init__(self, artifact, initiator_id):
        self.artifact = artifact
        self.initiatiors = [initiator_id]
        self.who = None  # we don't know who's going to do this yet
        
        
class _BuildFinished(object):

    def __init__(self, msg):
        self.msg = msg
        
# TODO: we could probably just pass the job around instead,
# then we wouldn't need to search for the job again when it completes
# premature optimisation at this point though i guess
class _BuildFailed(object):

    pass
        
class _Cached(object):

    pass
    
    
class WorkerBuildQueuer(distbuild.StateMachine):

    '''Maintain queue of outstanding worker-build requests.
    
    This state machine captures WorkerBuildRequest events, and puts them
    into a queue. It also catches _NeedJob events, from a
    WorkerConnection, and responds to them with _HaveAJob events,
    when it has an outstanding request.
    
    '''
    
    def __init__(self):
        distbuild.StateMachine.__init__(self, 'idle')

    def setup(self):
        distbuild.crash_point()

        logging.debug('WBQ: Setting up %s' % self)
        self._request_queue = []
        self._available_workers = []
        self._jobs = {}
        
        spec = [
            # state, source, event_class, new_state, callback
            ('idle', WorkerBuildQueuer, WorkerBuildRequest, 'idle',
                self._handle_request),
            ('idle', WorkerBuildQueuer, WorkerCancelPending, 'idle',
                self._handle_cancel),
            # TODO: probably _NeedJob can have a different function,
            # since there's no artifact to check, no notification etc
            ('idle', WorkerConnection, _NeedJob, 'idle', self._handle_worker),
        ]
        self.add_transitions(spec)

    def _handle_request(self, event_source, event):
        distbuild.crash_point()

        # Are we already building the thing?
        # If so, add our initiator id to the existing job
        # If not, add the job to the list and queue it
        #job = filter(lambda job: job.artifact == event.artifact, self._jobs)

        logging.debug('Handling build request for %s' % event.initiator_id)
        logging.debug('Currently building: %s' [job.artifact.name for job in self._jobs])

        if event.artifact in self._jobs:
            job.initiators.append(event.initiator_id)

            logging.debug("Worker build in progress")
            progress = WorkerBuildInProgress(
                self._initiator_id, self._artifact.cache_key, job.who.name())

            self.mainloop.queue_event(WorkerConnection, progress)
        else:
            j = Job(event.artifact, event.initiator_id)
            #self._jobs.append(j)
            self._jobs[event.artifact] = j

            logging.debug('WBQ: Adding request to queue: %s'
                % event.artifact.name)
            self._request_queue.append(event)
            logging.debug(
                'WBQ: %d available workers and %d requests queued' %
                    (len(self._available_workers),
                     len(self._request_queue)))
            if self._available_workers:
                j.who = self._give_job()
                logging.debug('Gave job to %s' % j.who.name())

    def _handle_cancel(self, event_source, worker_cancel_pending):
        # TODO: this probably needs to check whether any initiators
        # care about this thing

        for request in [r for r in self._request_queue if
                        r.initiator_id == worker_cancel_pending.initiator_id]:
            logging.debug('WBQ: Removing request from queue: %s',
                          request.artifact.name)
            self._request_queue.remove(request)

    def _handle_worker(self, event_source, event):
        distbuild.crash_point()

        who = event.who

        # If we have an artifact we're done with it now
        if who.last_built:
            logging.debug('%s wants new job, just just did %s' %
                (who.name(), who.last_built.name))
            del self._jobs[who.last_built]  # job's done
        else:
            logging.debug('%s wants its first job' % who.name())

        logging.debug('WBQ: Adding worker to queue: %s' % event.who)
        self._available_workers.append(event)
        logging.debug(
            'WBQ: %d available workers and %d requests queued' %
                (len(self._available_workers),
                 len(self._request_queue)))
        if self._request_queue:
            self._give_job()
            
    def _give_job(self):
        request = self._request_queue.pop(0)
        worker = self._available_workers.pop(0)
        logging.debug(
            'WBQ: Giving %s to %s' %
                (request.artifact.name, worker.who.name()))
        self.mainloop.queue_event(worker.who, _HaveAJob(request.artifact,
                                                        request.initiator_id))

        return worker.who
    
    
class WorkerConnection(distbuild.StateMachine):

    '''Communicate with a single worker.'''
    
    _request_ids = distbuild.IdentifierGenerator('WorkerConnection')
    _route_map = distbuild.RouteMap()
    _initiator_request_map = collections.defaultdict(set)

    def __init__(self, cm, conn, writeable_cache_server, 
                 worker_cache_server_port, morph_instance):
        distbuild.StateMachine.__init__(self, 'idle')
        self._cm = cm
        self._conn = conn
        self._writeable_cache_server = writeable_cache_server
        self._worker_cache_server_port = worker_cache_server_port
        self._morph_instance = morph_instance
        self._helper_id = None

        self.last_built = None
        # TODO: we can probably just use self._artifact, for this
        # try it out later

        addr, port = self._conn.getpeername()
        name = socket.getfqdn(addr)
        self._worker_name = '%s:%s' % (name, port)

    def name(self):
        return self._worker_name

    def setup(self):
        distbuild.crash_point()

        logging.debug('WC: Setting up instance %s' % repr(self))
    
        self._jm = distbuild.JsonMachine(self._conn)
        self.mainloop.add_state_machine(self._jm)
        
        spec = [
            # state, source, event_class, new_state, callback
            ('idle', self._jm, distbuild.JsonEof, None,  self._reconnect),
            ('idle', self, _HaveAJob, 'building', self._start_build),
            
            ('building', distbuild.BuildController,
                distbuild.BuildCancel, 'building',
                self._maybe_cancel),
            ('building', self._jm, distbuild.JsonEof, None, self._reconnect),
            ('building', self._jm, distbuild.JsonNewMessage, 'building',
                self._handle_json_message),
            ('building', self, _BuildFailed, 'idle', self._request_job),
            ('building', self, _BuildFinished, 'caching',
                self._request_caching),

            ('caching', distbuild.HelperRouter, distbuild.HelperResult,
                'caching', self._maybe_handle_helper_result),
            ('caching', self, _Cached, 'idle', self._request_job),
            ('caching', self, _BuildFailed, 'idle', self._request_job),
        ]
        self.add_transitions(spec)
        
        self._request_job(None, None)

    def _maybe_cancel(self, event_source, build_cancel):
        logging.debug('WC: BuildController %r requested a cancel' %
                      event_source)
        if build_cancel.id == self._initiator_id:
            distbuild.crash_point()

            for id in self._initiator_request_map[self._initiator_id]:
                logging.debug('WC: Cancelling exec %s' % id)
                msg = distbuild.message('exec-cancel', id=id)
                self._jm.send(msg)

    def _reconnect(self, event_source, event):
        distbuild.crash_point()

        logging.debug('WC: Triggering reconnect')
        self.mainloop.queue_event(self._cm, distbuild.Reconnect())

    def _start_build(self, event_source, event):
        distbuild.crash_point()

        self._artifact = event.artifact
        self.last_built = event.artifact
        self._initiator_id = event.initiator_id
        logging.debug('WC: starting build: %s for %s' %
                      (self._artifact.name, self._initiator_id))

        argv = [
            self._morph_instance,
            'worker-build',
            self._artifact.name,
        ]
        msg = distbuild.message('exec-request',
            id=self._request_ids.next(),
            argv=argv,
            stdin_contents=distbuild.serialise_artifact(self._artifact),
        )
        self._jm.send(msg)
        logging.debug('WC: sent to worker %s: %r' % (self._worker_name, msg))
        self._route_map.add(self._initiator_id, msg['id'])
        self._initiator_request_map[self._initiator_id].add(msg['id'])
        logging.debug(
            'WC: route map from %s to %s',
            self._artifact.cache_key, msg['id'])

        started = WorkerBuildStepStarted(
            self._initiator_id, self._artifact.cache_key, self.name())
        self.mainloop.queue_event(WorkerConnection, started)

    def _handle_json_message(self, event_source, event):
        '''Handle JSON messages from the worker.'''

        distbuild.crash_point()

        logging.debug(
            'WC: from worker %s: %r' % (self._worker_name, event.msg))

        handlers = {
            'exec-output': self._handle_exec_output,
            'exec-response': self._handle_exec_response,
        }
        
        handler = handlers[event.msg['type']]
        handler(event.msg)

    def _handle_exec_output(self, msg):
        new = dict(msg)
        new['id'] = self._route_map.get_incoming_id(msg['id'])
        logging.debug('WC: emitting: %s', repr(new))
        self.mainloop.queue_event(
            WorkerConnection,
            WorkerBuildOutput(new, self._artifact.cache_key))

    def _handle_exec_response(self, msg):
        logging.debug('WC: finished building: %s' % self._artifact.name)

        new = dict(msg)
        new['id'] = self._route_map.get_incoming_id(msg['id'])
        self._route_map.remove(msg['id'])
        self._initiator_request_map[self._initiator_id].remove(msg['id'])

        if new['exit'] != 0:
            # Build failed.
            new_event = WorkerBuildFailed(new, self._artifact.cache_key)
            self.mainloop.queue_event(WorkerConnection, new_event)
            self.mainloop.queue_event(self, _BuildFailed())
            self._artifact = None
            self._initiator_id = None
        else:
            # Build succeeded. We have more work to do: caching the result.
            self.mainloop.queue_event(self, _BuildFinished(new))

    def _request_job(self, event_source, event):
        distbuild.crash_point()
        self.mainloop.queue_event(WorkerConnection, _NeedJob(self))

    def _request_caching(self, event_source, event):
        distbuild.crash_point()

        logging.debug('Requesting shared artifact cache to get artifacts')

        kind = self._artifact.source.morphology['kind']

        if kind == 'chunk':
            source_artifacts = self._artifact.source.artifacts

            suffixes = ['%s.%s' % (kind, name) for name in source_artifacts]
        else:
            filename = '%s.%s' % (kind, self._artifact.name)
            suffixes = [filename]

            if kind == 'stratum':
                suffixes.append(filename + '.meta')
            elif kind == 'system':
                # FIXME: This is a really ugly hack.
                if filename.endswith('-rootfs'):
                    suffixes.append(filename[:-len('-rootfs')] + '-kernel')
        
        suffixes = [urllib.quote(x) for x in suffixes]
        suffixes = ','.join(suffixes)

        worker_host = self._conn.getpeername()[0]
        
        url = urlparse.urljoin(
            self._writeable_cache_server, 
            '/1.0/fetch?host=%s:%d&cacheid=%s&artifacts=%s' %
                (urllib.quote(worker_host),
                 self._worker_cache_server_port,
                 urllib.quote(self._artifact.cache_key),
                 suffixes))

        msg = distbuild.message(
            'http-request', id=self._request_ids.next(), url=url,
            method='GET', body=None, headers=None)
        self._helper_id = msg['id']
        req = distbuild.HelperRequest(msg)
        self.mainloop.queue_event(distbuild.HelperRouter, req)
        
        # tell anything that's interested in this thing that it's caching
        # instead of sending one initiator id, we should send a list of ids
        # for initiators that might be interested in this event

        progress = WorkerBuildCaching(
            self._initiator_id, self._artifact.cache_key)
        self.mainloop.queue_event(WorkerConnection, progress)
        
        self._initiator_id = None
        self._finished_msg = event.msg

    def _maybe_handle_helper_result(self, event_source, event):
        if event.msg['id'] == self._helper_id:
            distbuild.crash_point()

            logging.debug('caching: event.msg: %s' % repr(event.msg))
            if event.msg['status'] == httplib.OK:
                logging.debug('Shared artifact cache population done')
                new_event = WorkerBuildFinished(
                    self._finished_msg, self._artifact.cache_key)
                self.mainloop.queue_event(WorkerConnection, new_event)
                self._finished_msg = None
                self._helper_id = None
                self.mainloop.queue_event(self, _Cached())
            else:
                logging.error(
                    'Failed to populate artifact cache: %s %s' %
                        (event.msg['status'], event.msg['body']))
                new_event = WorkerBuildFailed(
                    self._finished_msg, self._artifact.cache_key)
                self.mainloop.queue_event(WorkerConnection, new_event)
                self._finished_msg = None
                self._helper_id = None
                self.mainloop.queue_event(self, _BuildFailed())

            self._artifact = None
