# distbuild/worker_build_scheduler.py -- schedule worker-builds on workers
#
# Copyright (C) 2012, 2014-2016  Codethink Limited
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


import collections
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

    def __init__(self, initiators, cache_key, worker_name):
        self.initiators = initiators
        self.artifact_cache_key = cache_key
        self.worker_name = worker_name

class WorkerBuildStepAlreadyStarted(object):

    def __init__(self, initiator_id, cache_key, worker_name):
        self.initiator_id = initiator_id
        self.artifact_cache_key = cache_key
        self.worker_name = worker_name

class WorkerBuildWaiting(object):

    def __init__(self, initiator_id, cache_key):
        self.initiator_id = initiator_id
        self.artifact_cache_key = cache_key

class WorkerBuildOutput(object):

    def __init__(self, msg, cache_key):
        self.msg = msg
        self.artifact_cache_key = cache_key

class WorkerBuildCaching(object):

    def __init__(self, initiators, cache_key):
        self.initiators = initiators
        self.artifact_cache_key = cache_key

class WorkerBuildFinished(object):

    def __init__(self, msg, cache_key, worker_name):
        self.msg = msg
        self.artifact_cache_key = cache_key
        self.worker_name = worker_name

class WorkerBuildFailed(object):

    def __init__(self, msg, cache_key):
        self.msg = msg
        self.artifact_cache_key = cache_key


class _NeedJob(object):

    def __init__(self, who):
        self.who = who
        

class _HaveAJob(object):

    def __init__(self, job):
        self.job = job

class _Disconnected(object):

    def __init__(self, who):
        self.who = who


class Job(object):

    def __init__(self, job_id, artifact, initiator_id):
        self.id = job_id
        self.artifact = artifact
        self.initiators = [initiator_id]
        self.who = None  # we don't know who's going to do this yet

        self._state = 'queued'

    def describe_state(self):
        if self.who is not None:
            return self._state + ', given to %s' % self.who
        else:
            return self._state

    def running(self):
        return self._state == 'running'

    def active(self):
        return self._state == 'running' or self._state == 'queued'

    def failed(self):
        return self._state == 'failed'

    def set_state(self, state):
        assert state in ['queued', 'running', 'complete', 'failed']
        logging.debug('Setting job state for job %s with id %s to %s',
                      self.artifact.basename(), self.id, state)
        self._state = state


class JobQueue(object):
    '''Tracks worker build jobs that are queued, or in progress.'''

    def __init__(self, owner):
        self._owner = owner
        self._jobs = {}

    def get_active_job_for_artifact(self, artifact_basename):
        jobs =  [job for job in self.active_jobs()
                 if job.artifact.basename() == artifact_basename]
        if len(jobs) > 1:
            logging.warn('More than one running job for %s',
                         artifact_basename)
        if not jobs:
            return None
        return jobs[0]

    def get_job_for_id(self, id):
        return self._jobs.get(id, None)

    def add(self, job):
        artifact_basename = job.artifact.basename()

        if self.has_job_for_artifact(artifact_basename):
            logging.info(
                "Duplicate job for %s added to %s job queue.",
                artifact_basename, self._owner)
        self._jobs[job.id] = job

    def remove(self, job):
        if job.id in self._jobs:
            del self._jobs[job.id]
        else:
            logging.warning("Tried to remove a job that doesn't exist "
                            "(%s)", job.artifact.basename())

    def has_job_for_artifact(self, artifact_basename):
        for job in self:
            if job.artifact.basename() == artifact_basename:
                return True

    def __iter__(self):
        return self._jobs.itervalues()

    def remove_jobs(self, jobs):
        for job in jobs:
            self.remove(job)

    def get_next_job(self):
        # for now just return the first thing we find that's not being built
        waiting = [job for job in self if job.who == None]

        return waiting.pop() if len(waiting) > 0 else None

    def running_jobs(self):
        return [job for job in self if job.running()]

    def active_jobs(self):
        return [job for job in self if job.active()]

    def __repr__(self):
        items = []
        for job in self._jobs.itervalues():
            items.append(
                '%s (%s)' % (job.artifact.basename(), job.describe_state()))
        return str(items)


class _BuildFinished(object):

    def __init__(self, job):
        self.job = job


class _BuildFailed(object):

    pass


class _BuildCancelled(object):

    pass

        
class _Cached(object):

    pass


class _JobStarted(object):

    def __init__(self, job):
        self.job = job


class _JobFinished(object):

    def __init__(self, job):
        self.job = job


class _JobFailed(object):

    def __init__(self, job):
        self.job = job
    
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
        self._available_workers = []
        self._jobs = JobQueue(owner='controller')
        self._idgen = distbuild.IdentifierGenerator('Job')

        spec = [
            # state, source, event_class, new_state, callback
            ('idle', WorkerBuildQueuer, WorkerBuildRequest, 'idle',
                self._handle_request),
            ('idle', WorkerBuildQueuer, WorkerCancelPending, 'idle',
                self._handle_cancel),

            ('idle', WorkerConnection, _NeedJob, 'idle', self._handle_worker),
            ('idle', WorkerConnection, _JobStarted, 'idle',
                self._set_job_started),
            ('idle', WorkerConnection, _JobFinished, 'idle',
                self._set_job_finished),
            ('idle', WorkerConnection, _JobFailed, 'idle',
                self._set_job_failed),

            ('idle', WorkerConnection, _Disconnected, 'idle',
                self._handle_worker_disconnected),
        ]
        self.add_transitions(spec)

    def _set_job_started(self, event_source, event):
        event.job.set_state('running')

    def _set_job_finished(self, event_source, event):
        job = event.job
        job.set_state('complete')
        self._jobs.remove(job)

    def _set_job_failed(self, event_source, event):
        job = event.job
        job.set_state('failed')
        self._jobs.remove(job)

    def _handle_request(self, event_source, event):
        distbuild.crash_point()

        logging.debug('Handling build request for %s' % event.initiator_id)
        logging.debug('Current jobs: %s' % self._jobs)
        logging.debug('Workers available: %d' % len(self._available_workers))

        # Have we already made a job for this thing?
        # If so, add our initiator id to the existing job
        # If not, create a job

        job = self._jobs.get_active_job_for_artifact(
            event.artifact.basename())
        if job is not None:
            job.initiators.append(event.initiator_id)

            # Completed jobs are not tracked, so we can't tell here if the
            # job was already built. It shouldn't happen, because the
            # BuildController has already checked for cached builds when
            # annotating the build graph.
            if job.running():
                logging.debug('Worker build step already started: %s' %
                    event.artifact.basename())
                progress = WorkerBuildStepAlreadyStarted(event.initiator_id,
                    event.artifact.cache_key, job.who.name())
            else:
                logging.debug('Job created but not building yet '
                    '(waiting for a worker to become available): %s' %
                    event.artifact.basename())
                progress = WorkerBuildWaiting(event.initiator_id,
                    event.artifact.cache_key)

            self.mainloop.queue_event(WorkerConnection, progress)
        else:
            logging.debug('WBQ: Creating job for: %s' % event.artifact.name)
            job = Job(self._idgen.next(), event.artifact, event.initiator_id)
            self._jobs.add(job)

            if self._available_workers:
                self._give_job(job)
            else:
                progress = WorkerBuildWaiting(event.initiator_id,
                    event.artifact.cache_key)
                self.mainloop.queue_event(WorkerConnection, progress)

    def _handle_cancel(self, event_source, event):

        def cancel_this(job):
            if event.initiator_id not in job.initiators:
                return False    # not for us

            name = job.artifact.basename()
            job_id = job.id

            logging.debug('Checking whether to remove job %s with job id %s',
                          name, job_id)

            if len(job.initiators) == 1:
                if job.running() or job.failed():
                    logging.debug('NOT removing running job %s with job id %s '
                                  '(WorkerConnection will cancel job)',
                                  name, job_id)
                else:
                    logging.debug('Removing job %s with job id %s',
                                  name, job_id)
                    return True
            else:
                # Don't cancel, but still remove this initiator from
                # the list of initiators
                logging.debug('NOT removing job %s with job id %s '
                              'other initiators want it: %s', name, job_id,
                              [i for i in job.initiators
                                if i != event.initiator_id])

                job.initiators.remove(event.initiator_id)

            return False

        self._jobs.remove_jobs(
            [job for job in self._jobs if cancel_this(job)])

    def _handle_worker(self, event_source, event):
        distbuild.crash_point()

        logging.debug('WBQ: Adding worker to queue: %s', event.who.name())
        self._available_workers.append(event)

        logging.debug('Current jobs: %s', self._jobs)
        logging.debug('Workers available: %d', len(self._available_workers))

        job = self._jobs.get_next_job()

        if job:
            self._give_job(job)
            
    def _give_job(self, job):
        worker = self._available_workers.pop(0)
        job.who = worker.who

        logging.debug(
            'WBQ: Giving %s to %s' %
                (job.artifact.name, worker.who.name()))

        self.mainloop.queue_event(worker.who, _HaveAJob(job))

    def _handle_worker_disconnected(self, event_source, event):
        self._remove_worker(self, event.who)

    def _remove_worker(self, worker):
        logging.debug('WBQ: Removing worker %s from queue', worker.name())

        # There should only be one InitiatorConnection instance per worker in
        # the _available_workers list. But anything can happen in space! So we
        # take care to remove all GiveJob messages in the list that came from
        # the disconnected worker, not the first.
        self._available_workers = filter(
            lambda worker_msg: worker_msg.who != worker,
            self._available_workers)


class WorkerConnection(distbuild.StateMachine):

    '''Communicate with a single worker.'''
    
    _request_ids = distbuild.IdentifierGenerator('WorkerConnection')
    _initiator_request_map = collections.defaultdict(set)

    def __init__(self, cm, conn, writeable_cache_server, 
                 worker_cache_server_port, morph_instance):
        distbuild.StateMachine.__init__(self, 'idle')
        self._cm = cm
        self._conn = conn
        self._writeable_cache_server = writeable_cache_server
        self._worker_cache_server_port = worker_cache_server_port
        self._morph_instance = morph_instance
        self._debug_exec_output = False

        addr, port = self._conn.getpeername()
        name = socket.getfqdn(addr)
        self._worker_name = '%s:%s' % (name, port)

        self._jobs = JobQueue(owner=self.name())

    def name(self):
        return self._worker_name

    def __str__(self):
        return self.name()

    def setup(self):
        distbuild.crash_point()

        logging.debug('WC: Setting up instance %s' % repr(self))
    
        self._jm = distbuild.JsonMachine(self._conn)
        self.mainloop.add_state_machine(self._jm)
        
        spec = [
            # state, source, event_class, new_state, callback
            ('idle', self._jm, distbuild.JsonEof, None,  self._disconnected),
            ('idle', self, _HaveAJob, 'building', self._start_build),
            
            ('building', distbuild.BuildController,
                distbuild.BuildCancel, 'building',
                self._maybe_cancel),

            ('building', self._jm, distbuild.JsonEof, None,
                self._disconnected),
            ('building', self._jm, distbuild.JsonNewMessage, 'building',
                self._handle_json_message),
            ('building', self, _BuildFailed, 'idle', self._request_job),
            ('building', self, _BuildCancelled, 'idle', self._request_job),
            ('building', self, _BuildFinished, 'caching',
                self._request_caching),

            ('caching', self._jm, distbuild.JsonEof, None, self._disconnected),
            ('caching', distbuild.HelperRouter, distbuild.HelperResult,
                'caching', self._maybe_handle_helper_result),
            ('caching', self, _Cached, 'idle', self._request_job),
            ('caching', self, _BuildFailed, 'idle', self._request_job),
        ]
        self.add_transitions(spec)
        
        self._request_job(None, None)

    def _maybe_cancel(self, event_source, build_cancel):
        logging.debug('WC: BuildController %r requested a cancel',
                      event_source)

        initiator_id = build_cancel.id
        for job in self._jobs.active_jobs():
            self._remove_initiator_from_job(job, initiator_id)

    def _remove_initiator_from_job(self, job, initiator_id):
        '''Remove the given initiator from 'job', and cancel it if needed.

        If the given initiator is not interested in 'job', nothing happens.

        '''

        if initiator_id in job.initiators:
            if len(job.initiators) == 1:
                self._cancel_job(job)
            else:
                logging.debug(
                    'WC: Not cancelling running job %s, other initiators want '
                    'it done: %s', job.artifact.basename(),
                    [i for i in job.initiators if i != initiator_id])
                job.initiators.remove(initiator_id)

    def _cancel_job(self, job):
        logging.debug(
            'WC: Cancelling job %s, currently building on %s',
            job.artifact.basename(), self.name())

        msg = distbuild.message('exec-cancel', id=job.id)
        self._jm.send(msg)
        # NOTE: We need to set job's state to 'failed' as soon as possible.
        # The exec-response message may take a while to arrive, and if we
        # wait for that then it is possible that another build-request for
        # the same artifact could be made, which would result in the build
        # not being started since the cancelled job would still be 'running'.
        # The new build will then fail when the exec-response for the old
        # build finally arrives.
        job.set_state('failed')
        self.mainloop.queue_event(self, _BuildCancelled())

    def _disconnected(self, event_source, event):
        distbuild.crash_point()

        logging.debug('WC: Disconnected from worker %s' % self.name())
        self.mainloop.queue_event(WorkerConnection, _Disconnected(self))

        self.mainloop.queue_event(self._cm, distbuild.Reconnect())

    def _sanity_check_new_job(self, job):
        # There's nothing that we can really do if the controller goes nuts
        # (there's no 'reject job' message), but we can at least log warnings.

        if self._jobs.has_job_for_artifact(job.artifact.basename()):
            logging.warn('Worker %s already has job %s', self.name(),
                         job.id)

        running_jobs = self._jobs.running_jobs()
        if len(running_jobs) != 0:
            logging.warn('This worker already has running jobs: %s',
                         running_jobs)

    def _start_build(self, event_source, event):
        distbuild.crash_point()

        job = event.job
        self._sanity_check_new_job(job)

        self._jobs.add(job)
        job.set_state('running')

        logging.debug('WC: starting build: %s for %s' %
                      (job.artifact.name, job.initiators))

        argv = [
            self._morph_instance,
            'worker-build',
            '--build-log-on-stdout',
            job.artifact.name,
        ]

        msg = distbuild.message('exec-request',
            id=job.id,
            argv=argv,
            stdin_contents=distbuild.encode_artifact_reference(job.artifact),
        )
        self._jm.send(msg)

        # The WorkerBuildQueuer object will set the job state to 'running' when
        # it receives the _JobStarted message.
        self.mainloop.queue_event(WorkerConnection, _JobStarted(job))

        started = WorkerBuildStepStarted(job.initiators,
            job.artifact.cache_key, self.name())
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
        job = self._jobs.get_job_for_id(event.msg['id'])

        if job:
            handler(event.msg, job)
        else:
            logging.warn('Received %s for unknown job %s',
                         event.msg['type'], event.msg['id'])

    def _handle_exec_output(self, msg, job):
        '''Handle output from a job that the worker is or was running.'''

        new = dict(msg)
        new['ids'] = job.initiators

        if self._debug_exec_output:
            logging.debug('WC: emitting: %s', repr(new))
        self.mainloop.queue_event(
            WorkerConnection,
            WorkerBuildOutput(new, job.artifact.cache_key))

    def _handle_exec_response(self, msg, job):
        '''Handle completion of a job that the worker is or was running.'''

        logging.debug('WC: finished building: %s' % job.artifact.name)
        logging.debug('initiators that need to know: %s' % job.initiators)

        new = dict(msg)
        new['ids'] = job.initiators

        if new['exit'] != 0:
            # Build failed.
            new_event = WorkerBuildFailed(new, job.artifact.cache_key)
            self.mainloop.queue_event(WorkerConnection, new_event)
            self.mainloop.queue_event(WorkerConnection, _JobFailed(job))
            self.mainloop.queue_event(self, _BuildFailed())
        else:
            # Build succeeded. We have more work to do: caching the result.
            self.mainloop.queue_event(self, _BuildFinished(job))
            job._exec_response = new

    def _request_job(self, event_source, event):
        distbuild.crash_point()
        self.mainloop.queue_event(WorkerConnection, _NeedJob(self))

    def _request_caching(self, event_source, event):
        # This code should be moved into the morphlib.remoteartifactcache
        # module. It would be good to share it with morphlib.buildcommand,
        # which also wants to fetch artifacts from a remote cache.
        distbuild.crash_point()

        logging.debug('Requesting shared artifact cache to get artifacts')

        job = event.job
        kind = job.artifact.kind

        if kind == 'chunk':
            artifact_names = job.artifact.source_artifact_names

            suffixes = ['%s.%s' % (kind, name) for name in artifact_names]
            suffixes.append('build-log')
        else:
            filename = '%s.%s' % (kind, job.artifact.name)
            suffixes = [filename]

            if kind == 'stratum':
                suffixes.append(filename + '.meta')
        
        suffixes = [urllib.quote(x) for x in suffixes]
        suffixes = ','.join(suffixes)

        worker_host = self._conn.getpeername()[0]
        
        url = urlparse.urljoin(
            self._writeable_cache_server, 
            '/1.0/fetch?host=%s:%d&cacheid=%s&artifacts=%s' %
                (urllib.quote(worker_host),
                 self._worker_cache_server_port,
                 urllib.quote(job.artifact.cache_key),
                 suffixes))

        msg = distbuild.message(
            'http-request', id=self._request_ids.next(), url=url,
            method='GET', body=None, headers=None)
        job._cache_request_id = msg['id']
        req = distbuild.HelperRequest(msg)
        self.mainloop.queue_event(distbuild.HelperRouter, req)
        
        progress = WorkerBuildCaching(job.initiators,
            job.artifact.cache_key)
        self.mainloop.queue_event(WorkerConnection, progress)

    def _maybe_handle_helper_result(self, event_source, event):
        # This function is called for every HelperResult message sent by the
        # controller's distbuild-helper process (for every completed or failed
        # http-request).
        for job in self._jobs:
            if event.msg['id'] == getattr(job, '_cache_request_id', None):
                self._handle_helper_result_for_job(job, event)

    def _handle_helper_result_for_job(self, job, event):
        distbuild.crash_point()

        logging.debug('caching: event.msg: %s' % repr(event.msg))
        if event.msg['status'] == httplib.OK:
            logging.debug('Shared artifact cache population done')

            finished_event = WorkerBuildFinished(
                job._exec_response, job.artifact.cache_key, job.who.name())
            self.mainloop.queue_event(WorkerConnection, finished_event)

            self.mainloop.queue_event(self, _Cached())
        else:
            logging.error(
                'Failed to populate artifact cache: %s %s' %
                    (event.msg['status'], event.msg['body']))

            # We will attempt to remove this job twice
            # unless we mark it as failed before the BuildController
            # processes the WorkerBuildFailed event.
            #
            # The BuildController will not try to cancel jobs that have
            # been marked as failed.
            self.mainloop.queue_event(WorkerConnection, _JobFailed(job))

            failed_event = WorkerBuildFailed(
                job._exec_response, job.artifact.cache_key)
            self.mainloop.queue_event(WorkerConnection, failed_event)

            self.mainloop.queue_event(self, _BuildFailed())

        # Caching is the last step of a job, so we're now done with it.
        self.mainloop.queue_event(WorkerConnection, _JobFinished(job))
