# distbuild_plugin.py -- Morph distributed build plugin
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


import cliapp
import logging
import sys

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


class SerialiseArtifactPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('serialise-artifact', self.serialise_artifact, 
                                arg_synopsis='REPO REF MORPHOLOGY')

    def disable(self):
        pass

    def serialise_artifact(self, args):
        '''Internal use only: Serialise Artifact build graph as JSON.'''
        
        distbuild.add_crash_conditions(self.app.settings['crash-condition'])
        
        if len(args) != 3:
            raise cliapp.AppException('Must get triplet')
        
        repo_name, ref, morph_name = args
        filename = '%s.morph' % morph_name
        build_command = morphlib.buildcommand.BuildCommand(self.app)
        srcpool = build_command.create_source_pool(repo_name, ref, filename)
        artifact = build_command.resolve_artifacts(srcpool)
        self.app.output.write(distbuild.serialise_artifact(artifact))
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

        serialized = sys.stdin.readline()
        artifact = distbuild.deserialise_artifact(serialized)
        
        bc = morphlib.buildcommand.BuildCommand(self.app)
        
        # We always, unconditionally clear the local artifact cache
        # to avoid it growing boundlessly on a worker. Especially system
        # artifacts are big (up to gigabytes), and having a new one for
        # every build eats up a lot of disk space.
        bc.lac.clear()

        arch = artifact.arch
        bc.build_artifact(artifact, bc.new_build_env(arch))


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
        router = distbuild.ListenServer(address, port, distbuild.JsonRouter)
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
            ['controller-helper-address'],
            'listen for helper connections on ADDRESS (domain / IP address)',
            default='localhost',
            group=group_distbuild)
        self.app.settings.integer(
            ['controller-helper-port'],
            'listen for helper connections on PORT',
            default=5656,
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

        artifact_cache_server = (
            self.app.settings['artifact-cache-server'] or
            self.app.settings['cache-server'])
        writeable_cache_server = self.app.settings['writeable-cache-server']
        worker_cache_server_port = \
            self.app.settings['worker-cache-server-port']
        morph_instance = self.app.settings['morph-instance']

        listener_specs = [
            ('controller-helper-address', 'controller-helper-port', 
             distbuild.HelperRouter, []),
            ('controller-initiator-address', 'controller-initiator-port',
             distbuild.InitiatorConnection, 
             [artifact_cache_server, morph_instance]),
        ]

        loop = distbuild.MainLoop()
        
        queuer = distbuild.WorkerBuildQueuer()
        loop.add_state_machine(queuer)

        for addr, port, sm, extra_args in listener_specs:
            addr = self.app.settings[addr]
            port = self.app.settings[port]
            listener = distbuild.ListenServer(
                addr, port, sm, extra_args=extra_args)
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


class InitiatorBuildCommand(morphlib.buildcommand.BuildCommand):

    def __init__(self, app, addr, port):
        self.app = app
        self.addr = addr
        self.port = port
        self.app.settings['push-build-branches'] = True
        super(InitiatorBuildCommand, self).__init__(app)

    def build(self, args):
        '''Initiate a distributed build on a controller'''
        
        distbuild.add_crash_conditions(self.app.settings['crash-condition'])

        if len(args) != 3:
            raise cliapp.AppException(
                'Need repo, ref, morphology triplet to build')

        self.app.status(msg='Starting distributed build')
        loop = distbuild.MainLoop()
        cm = distbuild.ConnectionMachine(
            self.addr, self.port, distbuild.Initiator, [self.app] + args)
        loop.add_state_machine(cm)
        loop.run()


class Initiator(cliapp.Plugin):

    def enable(self):
        self.app.settings.boolean(
            ['disable-distbuild'], 'disable distributed building',
            group=group_distbuild)
        self.app.hookmgr.add_callback(
            'new-build-command', self.create_build_command)

    def disable(self):
        pass

    def create_build_command(self, old_build_command):
        addr = self.app.settings['controller-initiator-address']
        port = self.app.settings['controller-initiator-port']

        if addr != '' and not self.app.settings['disable-distbuild']:
            return InitiatorBuildCommand(self.app, addr, port)
        else:
            return old_build_command


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