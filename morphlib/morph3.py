# Copyright (C) 2013-2014  Codethink Limited
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


import UserDict

import morphlib


class Morphology(UserDict.IterableUserDict):

    '''A container for a morphology, plus its metadata.

    A morphology is, basically, a dict. This class acts as that dict,
    plus stores additional metadata about the morphology, such as where
    it came from, and the ref that was used for it. It also has a dirty
    attribute, to indicate whether the morphology has had changes done
    to it, but does not itself set that attribute: the caller has to
    maintain the flag themselves.

    This class does NO validation of the data, nor does it parse the
    morphology text, or produce a textual form of itself. For those
    things, see MorphologyLoader.

    '''

    def __init__(self, *args, **kwargs):
        UserDict.IterableUserDict.__init__(self, *args, **kwargs)
        self.repo_url = None
        self.ref = None
        self.filename = None
        self.dirty = None

    def get_commands(self, which):
        '''Return the commands to run from a morphology or the build system'''
        if self.get(which, None) is None:
            attr = '_'.join(which.split('-'))
            bs = morphlib.buildsystem.lookup_build_system(self['build-system'])
            return getattr(bs, attr)
        else:
            return self[which]
