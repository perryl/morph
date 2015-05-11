# distbuild_plugin.py -- Morph distributed build plugin
#
# Copyright (C) 2014-2015  Codethink Limited
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
import logging
import re
import sys
import uuid

import morphlib
import distbuild


group_distbuild = 'Distributed Build Options'

class DistbuildOptionsPlugin(cliapp.Plugin):

    def enable(self):
        self.app.settings.string_list(
            ['crash-condition'],
            'add FILENAME:FUNCNAME:MAXCALLS to list of crash conditions '
                '(this is for testing only)',
            metavar='FILENAME:FUNCNAME:MAXCALLS',
            group=group_distbuild)

    def disable(self):
        pass


class DistbuildCancel(cliapp.Plugin):

    RECONNECT_INTERVAL = 30 # seconds
    MAX_RETRIES = 1

    def enable(self):
        self.app.add_subcommand('distbuild-cancel', self.distbuild_cancel,
                                arg_synopsis='ID')

    def disable(self):
        pass

    def distbuild_cancel(self, args):
        '''Cancels a currently-running distbuild

        Command line arguments:

        `ID` of the running process that you wish to cancel
        (this can be found via distbuild-list-jobs)

        Example:

            * morph distbuild-cancel InitiatorConnection-1

        '''

        if len(args) != 1:
            raise cliapp.AppException(
                'usage: morph distbuild-cancel <build-request id>')

        args.append('build-cancel')
        args.append('Sending cancel request for distbuild job.')
        addr = self.app.settings['controller-initiator-address']
        port = self.app.settings['controller-initiator-port']
        icm = distbuild.InitiatorConnectionMachine(self.app, addr, port,
                                                   distbuild.InitiatorShort,
                                                   [self.app] + args,
                                                   self.RECONNECT_INTERVAL,
                                                   self.MAX_RETRIES)
        loop = distbuild.MainLoop()
        loop.add_state_machine(icm)
        loop.run()


class DistbuildStatusPlugin(cliapp.Plugin):

    RECONNECT_INTERVAL = 30 # seconds
    MAX_RETRIES = 1

    def enable(self):
        self.app.add_subcommand('distbuild-status', self.distbuild_status,
                                arg_synopsis='ID')

    def disable(self):
        pass

    def distbuild_status(self, args):
        '''Displays build status of recent distbuild requests.

        Lists last known build status for all distbuilds (e.g. Building,
        Failed, Finished, Cancelled) on a given distbuild server as set in
        /etc/morph.conf

        Example:

            morph distbuild-status InitiatorConnection-1

        Example output:

            Build request ID: InitiatorConnection-1
              System build: systems/devel-system-x86_64-generic.morph
              Build status: Building stage1-binutils-misc

        '''

        if len(args) != 1:
            raise cliapp.AppException(
                'usage: morph distbuild-status <build-request id>')

        args.append('build-status')
        args.append('Requesting status of recent build requests.')
        addr = self.app.settings['controller-initiator-address']
        port = self.app.settings['controller-initiator-port']
        icm = distbuild.InitiatorConnectionMachine(self.app, addr, port,
                                                   distbuild.InitiatorShort,
                                                   [self.app] + args,
                                                   self.RECONNECT_INTERVAL,
                                                   self.MAX_RETRIES)
        loop = distbuild.MainLoop()
        loop.add_state_machine(icm)
        loop.run()


class DistbuildListJobsPlugin(cliapp.Plugin):

    RECONNECT_INTERVAL = 30 # seconds
    MAX_RETRIES = 1

    def enable(self):
        self.app.add_subcommand('distbuild-list-jobs',
                                self.distbuild_list_jobs, arg_synopsis='')

    def disable(self):
        pass

    def distbuild_list_jobs(self, args):
        '''Display a list of currently running distbuilds.
 
        Lists all distbuilds running on a given address and port, as set in
        the client machine's morph.conf file

        Example output:

        '1 distbuild build request(s) currently in progress
        Initiator connection (address:port): localhost:7878
        Build request message: {'repo': 'baserock:baserock/definitions',
        'original_ref': 'BRANCH_NAME', 'ref': 'SHA1', 'morphology':
        'systems/devel-system-x86_64-generic.morph', 'protocol_version': 1,
        'type': 'build-request', 'id': 'InitiatorConnection-x'}'
        Build request ID: InitiatorConnection-x

        '''

        args.append(uuid.uuid4().hex)
        args.append('list-requests')
        args.append('Requesting currently running distbuilds.')
        addr = self.app.settings['controller-initiator-address']
        port = self.app.settings['controller-initiator-port']
        icm = distbuild.InitiatorConnectionMachine(self.app, addr, port,
                                                   distbuild.InitiatorShort,
                                                   [self.app] + args,
                                                   self.RECONNECT_INTERVAL,
                                                   self.MAX_RETRIES)
        loop = distbuild.MainLoop()
        loop.add_state_machine(icm)
        loop.run()


class CalculateBuildGraphPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('calculate-build-graph',
                                self.calculate_build_graph,
                                arg_synopsis='REPO REF MORPHOLOGY [REF_NAME]')

    def disable(self):
        pass

    def calculate_build_graph(self, args):
        '''Internal use only: Encode Artifact build graph as JSON.'''
        
        distbuild.add_crash_conditions(self.app.settings['crash-condition'])
        
        if len(args) not in [3, 4]:
            raise cliapp.AppException(
                'This command takes a repo/ref/morph triplet, and optionally '
                'a ref name.')

        repo_name, ref, morph_name = args[0:3]

        if len(args) == 4:
            original_ref = args[3]
        else:
            original_ref = ref

        filename = morphlib.util.sanitise_morphology_path(morph_name)
        build_command = morphlib.buildcommand.BuildCommand(self.app)
        srcpool = build_command.create_source_pool(
            repo_name, ref, filename, original_ref=original_ref)
        artifact = build_command.resolve_artifacts(srcpool)
        self.app.output.write(distbuild.encode_artifact(artifact,
                                                        repo_name,
                                                        ref))
        self.app.output.write('\n')


class WorkerBuild(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'worker-build', self.worker_build, arg_synopsis='')

    def disable(self):
        pass
    
    def worker_build(self, args):
        '''Internal use only: Build an artifact in a worker.
        
        All build dependencies are assumed to have been built already
        and available in the local or remote artifact cache.
        
        '''
        
        distbuild.add_crash_conditions(self.app.settings['crash-condition'])

        text = sys.stdin.readline()
        artifact_reference = distbuild.decode_artifact_reference(text)

        bc = morphlib.buildcommand.BuildCommand(self.app)
        source_pool = bc.create_source_pool(artifact_reference.repo,
                                            artifact_reference.ref,
                                            artifact_reference.root_filename)

        root = bc.resolve_artifacts(source_pool)

        # Now, before we start the build, we garbage collect the caches
        # to ensure we have room.  First we remove all system artifacts
        # since we never need to recover those from workers post-hoc
        for cachekey, artifacts, last_used in bc.lac.list_contents():
            if any(self.is_system_artifact(f) for f in artifacts):
                logging.debug("Removing all artifacts for system %s" %
                        cachekey)
                bc.lac.remove(cachekey)

        self.app.subcommands['gc']([])

        source = self.find_source(source_pool, artifact_reference)
        build_env = bc.new_build_env(artifact_reference.arch)
        bc.build_source(source, build_env)

    def find_source(self, source_pool, artifact_reference):
        for s in source_pool.lookup(artifact_reference.source_repo,
                                    artifact_reference.source_ref,
                                    artifact_reference.filename):
            if s.cache_key == artifact_reference.cache_key:
                return s
        for s in source_pool.lookup(artifact_reference.source_repo,
                                    artifact_reference.source_sha1,
                                    artifact_reference.filename):
            if s.cache_key == artifact_reference.cache_key:
                return s

    def is_system_artifact(self, filename):
        return re.match(r'^[0-9a-fA-F]{64}\.system\.', filename)

class WorkerDaemon(cliapp.Plugin):

    def enable(self):
        self.app.settings.string(
            ['worker-daemon-address'],
            'listen for connections on ADDRESS (domain / IP address)',
            default='',
            group=group_distbuild)
        self.app.settings.integer(
            ['worker-daemon-port'],
            'listen for connections on PORT',
            default=3434,
            group=group_distbuild)
        self.app.settings.string(
            ['worker-daemon-port-file'],
            'write port used by worker-daemon to FILE',
            default='',
            group=group_distbuild)
        self.app.add_subcommand(
            'worker-daemon',
            self.worker_daemon,
            arg_synopsis='')
    
    def disable(self):
        pass
        
    def worker_daemon(self, args):
        '''Daemon that controls builds on a single worker node.'''

        distbuild.add_crash_conditions(self.app.settings['crash-condition'])

        address = self.app.settings['worker-daemon-address']
        port = self.app.settings['worker-daemon-port']
        port_file = self.app.settings['worker-daemon-port-file']
        router = distbuild.ListenServer(address, port, distbuild.JsonRouter,
                                        port_file=port_file)
        loop = distbuild.MainLoop()
        loop.add_state_machine(router)
        loop.run()


class ControllerDaemon(cliapp.Plugin):

    def enable(self):
        self.app.settings.string(
            ['controller-initiator-address'],
            'listen for initiator connections on ADDRESS '
                '(domain / IP address)',
            default='',
            group=group_distbuild)
        self.app.settings.integer(
            ['controller-initiator-port'],
            'listen for initiator connections on PORT',
            default=7878,
            group=group_distbuild)
        self.app.settings.string(
            ['controller-initiator-port-file'],
            'write the port to listen for initiator connections to FILE',
            default='',
            group=group_distbuild)
        self.app.settings.string(
            ['initiator-step-output-dir'],
            'write build output to files in DIR',
            group=group_distbuild)

        self.app.settings.string(
            ['controller-helper-address'],
            'listen for helper connections on ADDRESS (domain / IP address)',
            default='localhost',
            group=group_distbuild)
        self.app.settings.integer(
            ['controller-helper-port'],
            'listen for helper connections on PORT',
            default=5656,
            group=group_distbuild)
        self.app.settings.string(
            ['controller-helper-port-file'],
            'write the port to listen for helper connections to FILE',
            default='',
            group=group_distbuild)

        self.app.settings.string_list(
            ['worker'],
            'specify a build worker (WORKER is ADDRESS or ADDRESS:PORT, '
                'with PORT defaulting to 3434)',
            metavar='WORKER',
            default=[],
            group=group_distbuild)
        self.app.settings.integer(
            ['worker-cache-server-port'],
            'port number for the artifact cache server on each worker',
            metavar='PORT',
            default=8080,
            group=group_distbuild)
        self.app.settings.string(
            ['writeable-cache-server'],
            'specify the shared cache server writeable instance '
                '(SERVER is ADDRESS or ADDRESS:PORT, with PORT defaulting '
                'to 80',
            metavar='SERVER',
            group=group_distbuild)

        self.app.settings.string(
            ['morph-instance'],
            'use FILENAME to invoke morph (default: %default)',
            metavar='FILENAME',
            default='morph',
            group=group_distbuild)

        self.app.add_subcommand(
            'controller-daemon', self.controller_daemon, arg_synopsis='')

    def disable(self):
        pass
        
    def controller_daemon(self, args):
        '''Daemon that gives jobs to worker daemons.'''
        
        distbuild.add_crash_conditions(self.app.settings['crash-condition'])

        if not self.app.settings['worker']:
            raise cliapp.AppException(
                'Distbuild controller has no workers configured. Refusing to '
                'start.')

        artifact_cache_server = (
            self.app.settings['artifact-cache-server'] or
            self.app.settings['cache-server'])
        writeable_cache_server = self.app.settings['writeable-cache-server']
        worker_cache_server_port = \
            self.app.settings['worker-cache-server-port']
        morph_instance = self.app.settings['morph-instance']

        listener_specs = [
            # address, port, class to initiate on connection, class init args
            ('controller-helper-address', 'controller-helper-port', 
             'controller-helper-port-file',
             distbuild.HelperRouter, []),
            ('controller-initiator-address', 'controller-initiator-port',
             'controller-initiator-port-file',
             distbuild.InitiatorConnection, 
             [artifact_cache_server, morph_instance]),
        ]

        loop = distbuild.MainLoop()
        
        queuer = distbuild.WorkerBuildQueuer()
        loop.add_state_machine(queuer)

        for addr, port, port_file, sm, extra_args in listener_specs:
            addr = self.app.settings[addr]
            port = self.app.settings[port]
            port_file = self.app.settings[port_file]
            listener = distbuild.ListenServer(
                addr, port, sm, extra_args=extra_args, port_file=port_file)
            loop.add_state_machine(listener)

        for worker in self.app.settings['worker']:
            if ':' in worker:
                addr, port = worker.split(':', 1)
                port = int(port)
            else:
                addr = worker
                port = 3434
            cm = distbuild.ConnectionMachine(
                addr, port, distbuild.WorkerConnection, 
                [writeable_cache_server, worker_cache_server_port,
                 morph_instance])
            loop.add_state_machine(cm)

        loop.run()

class GraphStateMachines(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'graph-state-machines',
            self.graph_state_machines,
            arg_synopsis='')

    def disable(self):
        pass

    def graph_state_machines(self, args):
        cm = distbuild.ConnectionMachine(None, None, None, None)
        cm._start_connect = lambda *args: None
        self.graph_one(cm)

        self.graph_one(distbuild.BuildController(None, None, None))
        self.graph_one(distbuild.HelperRouter(None))
        self.graph_one(distbuild.InitiatorConnection(None, None, None))
        self.graph_one(distbuild.JsonMachine(None))
        self.graph_one(distbuild.WorkerBuildQueuer())

        # FIXME: These need more mocking to work.
        # self.graph_one(distbuild.Initiator(None, None,
        #    self, None, None, None))
        # self.graph_one(distbuild.JsonRouter(None))
        # self.graph_one(distbuild.SocketBuffer(None, None))
        # self.graph_one(distbuild.ListenServer(None, None, None))

    def graph_one(self, sm):
        class_name = sm.__class__.__name__.split('.')[-1]
        filename = '%s.gv' % class_name
        sm.mainloop = self
        sm.setup()
        sm.dump_dot(filename)

    # Some methods to mock this class as other classes, which the
    # state machine class need to access, just enough to allow the
    # transitions to be set up for graphing.

    def queue_event(self, *args, **kwargs):
        pass

    def add_event_source(self, *args, **kwargs):
        pass

    def add_state_machine(self, sm):
        pass

    def status(self, *args, **kwargs):
        pass
