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

import morphlib


class RefManifestPlugin(cliapp.Plugin):

    """Add subcommands for managing the ref-manifest in definitions."""

    def enable(self):
        self.app.add_subcommand('update-ref', self.update_ref,
                                arg_synopsis='CHUNK REF SHA')

    def disable(self):
        pass

    def load_manifest(self, sb):
        repo_path = sb.get_git_directory_name(sb.root_repository_url)
        location = os.path.join(repo_path, 'ref-manifest')
        return morphlib.refmanifest.RefManifest.load_from_file(location)

    def update_ref(self, args):
        """Update a ref in the manifest.

        Command line argument:

        * `CHUNK` is the chunk to update the ref for.

        * `REF` is the ref you wish to update.

        * `SHA` is the new SHA1 of the ref.

        This updates a ref in the ref-manifest file in the root
        repository of the current system branch.

        """
        if len(args) < 3:
           raise morphlib.Error('update-ref takes exactly 3 arguments')

        chunk_name = args[0]
        ref = args[1]
        sha = args[2]

        sb = morphlib.sysbranchdir.open_from_within('.')
        ref_manifest = self.load_manifest(sb)
        ref_manifest.set_chunk_ref(chunk_name, ref, sha)
        self.app.status(msg='Set ref %s to %s in %s' % (ref, sha, chunk_name))
        ref_manifest.save_to_file(location)
