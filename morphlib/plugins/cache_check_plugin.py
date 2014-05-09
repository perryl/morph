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


class CacheCheckPlugin(cliapp.Plugin):
    '''Check for corruption in Morph's inputs and caches.

    This plugin is intended to be useful when investigating unexplained errors
    during builds or in built systems. If the inputs or caches contained
    corruption, this may explain the errors.

    Note that this does not check the 'ccache' data. There is no way to
    validate if this has been corrupted, currently. You can disable ccache in
    Morph with the 'no-ccache' setting.

    '''

    def enable(self):
        self.app.add_subcommand('check-git-cache', self.check_git_cache)
        self.app.add_subcommand('check-artifact-cache',
                                self.check_artifact_cache)

    def disable(self):
        pass

    def check_git_cache(self, args):
        '''Check for corruption in the local cache of Git repositories.'''

        lrc, rrc = morphlib.util.new_repo_caches(self.app)

        # Trove is ignored -- validating that is really up to the sysadmin.
        # morph could do that, though.

        self.app.status(
            msg='Checking all locally cached git repositories for corruption')
        git_errors = lrc.validate()

        self.app.output.write(
            'Found corruption in %i cached git repo(s).\n' % len(git_errors))

        for repo_dir, error_text in git_errors.iteritems():
            self.app.output.write('    %s\n' % repo_dir)
            error_text_indented = '\n'.join(
                ['    ' + line for line in error_text.split('\n')])
            self.app.output.write("    %s\n" % error_text_indented)

    def check_artifact_cache(self, args):
        '''Check for corruption in the local cache of built artifacts.

        This includes the artifact cache itself, and the unpacked chunk
        artifacts which are used at build time.

        '''
        self.app.status(
            msg='Checking all locally cached build artifacts for corruption')

        lac, rac = morphlib.util.new_artifact_caches(self.app.settings)
        unpacked_chunk_cache_dir = os.path.join(
            self.app.settings['tempdir'], 'chunks')
        errors, no_checksum = lac.validate(unpacked_chunk_cache_dir)

        if len(no_checksum) > 0:
            self.app.output.write(
                '%i builds do not have checksums' % len(no_checksum))
            if self.app.settings['verbose']:
                for name in no_checksum:
                    self.app.output.write('    %s\n' % name)

        self.app.output.write(
            'Found corruption in %i cached builds(s).\n' % len(errors))

        for cache_key, error_list in errors.iteritems():
            for line in error_list:
                self.app.output.write("    %s\n" % line)

        # FIXME: ccache is not validated! don't use ccache, perhaps!
