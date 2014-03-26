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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import cliapp
import logging
import os

import morphlib


class PushPullPlugin(cliapp.Plugin):

    '''Add subcommands to wrap the git push and pull commands.'''

    def enable(self):
        self.app.add_subcommand(
            'push', self.push, arg_synopsis='REPO TARGET')
        self.app.add_subcommand('pull', self.pull, arg_synopsis='[REMOTE]')

    def disable(self):
        pass

    def push(self, args):
        '''Push a branch to a remote repository.

        Command line arguments:

        * `REPO` is the repository to push your changes to.

        * `TARGET` is the branch to push to the repository.

        This is a wrapper for the `git push` command. It also deals with
        pushing any binary files that have been added using git-fat.

        Example:

            morph push origin jrandom/new-feature

        '''
        if len(args) != 2:
            raise morphlib.Error('push must get exactly two arguments')

        gd = morphlib.gitdir.GitDirectory(os.getcwd())
        remote, branch = args
        rs = morphlib.gitdir.RefSpec(branch)
        gd.get_remote(remote).push(rs)
        if gd.has_fat():
            gd.fat_init()
            gd.fat_push()

    def pull(self, args):
        '''Pull changes to the current branch from a repository.

        Command line arguments:

        * `REMOTE` is the remote branch to pull from. By default this is the
          branch being tracked by your current git branch (ie origin/master
          for branch master)

        This is a wrapper for the `git pull` command. It also deals with
        pulling any binary files that have been added to the repository using
        git-fat.

        Example:

            morph pull

        '''
        if len(args) > 1:
            raise morphlib.Error('pull takes at most one argument')

        gd = morphlib.gitdir.GitDirectory(os.getcwd())
        remote = gd.get_remote('origin')
        if args:
            branch = args[0]
            remote.pull(branch)
        else:
            remote.pull()
        if gd.has_fat():
            gd.fat_init()
            gd.fat_pull()
