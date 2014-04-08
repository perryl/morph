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
        
        
class _JobIsFinished(object):

    def __init__(self, msg):
        self.msg = msg
        
        
class _JobFailed(object):

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
        
        spec = [
            ('idle', WorkerBuildQueuer, WorkerBuildRequest, 'idle',
                self._handle_request),
            ('idle', WorkerBuildQueuer, WorkerCancelPending, 'idle',
                self._handle_cancel),
            ('idle', WorkerConnection, _NeedJob, 'idle', self._handle_worker),
        ]
        self.add_transitions(spec)

    def _handle_request(self, event_source, event):
        distbuild.crash_point()

        logging.debug('WBQ: Adding request to queue: %s' % event.artifact.name)
        self._request_queue.append(event)
        logging.debug(
            'WBQ: %d available workers and %d requests queued' %
                (len(self._available_workers),
                 len(self._request_queue)))
        if self._available_workers:
            self._give_job()

    def _handle_cancel(self, event_source, worker_cancel_pending):
        for request in [r for r in self._request_queue if
                        r.initiator_id == worker_cancel_pending.initiator_id]:
            logging.debug('WBQ: Removing request from queue: %s',
                          request.artifact.name)
            self._request_queue.remove(request)

    def _handle_worker(self, event_source, event):
        distbuild.crash_point()

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
        
    def name(self):
        addr, port = self._conn.getpeername()
        name = socket.getfqdn(addr)
        return '%s:%s' % (name, port)

    def setup(self):
        distbuild.crash_point()

        logging.debug('WC: Setting up instance %s' % repr(self))
    
        self._jm = distbuild.JsonMachine(self._conn)
        self.mainloop.add_state_machine(self._jm)
        
        spec = [
            ('idle', self._jm, distbuild.JsonEof, None,  self._reconnect),
            ('idle', self, _HaveAJob, 'building', self._start_build),
            
            ('building', distbuild.BuildController,
                distbuild.BuildCancel, 'building',
                self._maybe_cancel),
            ('building', self._jm, distbuild.JsonEof, None, self._reconnect),
            ('building', self._jm, distbuild.JsonNewMessage, 'building',
                self._handle_json_message),
            ('building', self, _JobFailed, 'idle', self._request_job),
            ('building', self, _JobIsFinished, 'caching',
                self._request_caching),

            ('caching', distbuild.HelperRouter, distbuild.HelperResult,
                'caching', self._handle_helper_result),
            ('caching', self, _Cached, 'idle', self._request_job),
            ('caching', self, _JobFailed, 'idle', self._request_job),
        ]
        self.add_transitions(spec)
        
        self._request_job(None, None)

    def _maybe_cancel(self, event_source, build_cancel):
        logging.debug('WC: BuildController requested a cancel')
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
        logging.debug('WC: sent to worker: %s' % repr(msg))
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

        logging.debug('WC: from worker: %s' % repr(event.msg))

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
            self.mainloop.queue_event(self, _JobFailed())
            self._artifact = None
            self._initiator_id = None
        else:
            # Build succeeded. We have more work to do: caching the result.
            self.mainloop.queue_event(self, _JobIsFinished(new))

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
        
        progress = WorkerBuildCaching(
            self._initiator_id, self._artifact.cache_key)
        self.mainloop.queue_event(WorkerConnection, progress)
        
        self._initiator_id = None
        self._finished_msg = event.msg

    def _handle_helper_result(self, event_source, event):
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
                self.mainloop.queue_event(self, _JobFailed())

            self._artifact = None
