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
import os
import yaml

import morphlib


class RefManifest(object):

    """Class to represent the ref-manifest file."""

    def __init__(self, contents, location):
        self.chunks = contents
        self.location = location

    @classmethod
    def load_from_file(cls, filepath):
        with open(filepath, 'r') as f:
            return RefManifest(yaml.load(f), filepath)

    def _get_chunk(self, chunk_name):
        if not chunk_name in self.chunks:
            raise morphlib.Error(
                'Chunk %s is not in the ref-manifest' % chunk_name)
        return self.chunks[chunk_name]

    def chunk_has_ref(self, chunk_name, ref):
        chunk = self._get_chunk(chunk_name)
        for pair in chunk:
            if ref in pair:
                return True
        return False

    def chunk_ref_different(self, chunk_name, ref, sha):
        chunk = self._get_chunk(chunk_name)
        if {ref: sha} in chunk:
            return True
        return False

    def get_chunk_ref(self, chunk_name, ref):
        chunk = self._get_chunk(chunk_name)
        for pair in chunk:
            if ref in pair:
                return pair

    def set_chunk_ref(self, chunk_name, ref, sha):
        chunk = self._get_chunk(chunk_name)
        if self.chunk_has_ref(chunk_name, ref):
            chunk.remove(self.get_chunk_ref(chunk_name, ref))
        chunk.append({ref: sha})

    def save_to_file(self, path=self.location):
        with open(path, 'w') as ref_manifest:
            ref_manifest.write(
                yaml.dump(self.chunks, default_flow_style=False))
