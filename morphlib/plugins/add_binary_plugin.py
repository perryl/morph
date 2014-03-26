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
import urlparse

import morphlib


class AddBinaryPlugin(cliapp.Plugin):

    '''Add a subcommand for dealing with large binary files.'''

    def enable(self):
        self.app.add_subcommand(
            'add-binary', self.add_binary, arg_synopsis='FILENAME...')

    def disable(self):
        pass

    def add_binary(self, binaries):
        '''Add a binary file to the current repository.

        Command line argument:

        * `FILENAME...` is the binaries to be added to the repository.

        This checks for the existence of a .gitfat file in the repository. If
        there is one then a line is added to .gitattributes telling it that
        the given binary should be handled by git-fat. If there is no .gitfat
        file then it is created, with the rsync remote pointing at the correct
        directory on the Trove host. A line is then added to .gitattributes to
        say that the given binary should be handled by git-fat.

        Example:

            morph add-binary big_binary.tar.gz

        '''
        if not binaries:
            raise morphlib.Error('add-binary must get at least one argument')

        gd = morphlib.gitdir.GitDirectory(os.getcwd())
        gd.fat_init()
        if not gd.has_fat():
            self._make_gitfat(gd)
        self._handle_binaries(binaries, gd)
        logging.info('Staged binaries for commit')

    def _handle_binaries(self, binaries, gd):
        '''Add a filter for the given file, and then add it to the repo.'''
        # begin by ensuring all paths given are relative to the root directory
        files = []
        for binary in binaries:
            path = gd.get_relpath(os.path.realpath(binary))
            files.append(path)

        # now add any files that aren't already mentioned in .gitattributes to
        # the file so that git fat knows what to do
        attr_path = gd.join_path('.gitattributes')
        if '.gitattributes' in gd.list_files():
            with open(attr_path, 'r') as attributes:
                current = set(f.split()[0] for f in attributes)
        else:
            current = set()
        to_add = set(files) - current

        # if we don't need to change .gitattributes then we can just do
        # `git add <binaries>`
        if not to_add:
            gd.get_index().add_files_from_working_tree(files)
            return

        with open(attr_path, 'a') as attributes:
            for path in to_add:
                attributes.write('%s filter=fat -crlf\n' % path)

        # we changed .gitattributes, so need to stage it for committing
        files.append(attr_path)
        gd.get_index().add_files_from_working_tree(files)

    def _make_gitfat(self, gd):
        '''Make .gitfat point to the rsync directory for the repo.'''
        remote = gd.get_remote('origin')
        if not remote.get_push_url():
            raise Exception(
                'Remote `origin` does not have a push URL defined.')
        url = urlparse.urlparse(remote.get_push_url())
        if url.scheme != 'ssh':
            raise Exception(
                'Push URL for `origin` is not an SSH URL: %s' % url.geturl())
        fat_store = '%s:%s' % (url.netloc, url.path)
        fat_path = gd.join_path('.gitfat')
        with open(fat_path, 'w+') as gitfat:
            gitfat.write('[rsync]\n')
            gitfat.write('remote = %s' % fat_store)
        gd.get_index().add_files_from_working_tree([fat_path])
