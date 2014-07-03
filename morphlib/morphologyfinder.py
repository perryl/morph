# Copyright (C) 2013  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import cliapp

import morphlib


class MorphologyFinder(object):

    '''Abstract away finding morphologies in a git repository.

    This class provides an abstraction layer between a git repository
    and the morphologies contained in it.

    '''

    def __init__(self, gitdir, ref=None):
        self.gitdir = gitdir
        self.ref = ref

    def read_morphology(self, name):
        '''Return the un-parsed text of a morphology.
        
        For the given morphology name, locate and return the contents
        of the morphology as a string.

        Also returns a string describing where in the repository the
        morphology is located.

        Parsing of this morphology into a form useful for manipulating
        is handled by the MorphologyLoader class.
        
        '''
        filename = '%s.morph' % name
        return self.gitdir.read_file(filename, self.ref), filename

    def list_morphologies(self):
        '''Return the names of all morphologies in the (repo, ref).

        Finds all morphologies in the git directory at the specified
        ref. Morphology names are returned instead of filenames,
        so the implementation may change how morphologies are stored
        in git repositories.

        '''

        def is_morphology_path(path):
            return path.endswith('.morph')

        def transform_path_to_name(path):
            return path[:-len('.morph')]

        return (transform_path_to_name(path)
                for path in self.gitdir.list_files(self.ref)
                if is_morphology_path(path))
