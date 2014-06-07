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


import logging
import os
import shutil
import time

import fs.osfs
import cliapp

import morphlib


class GCPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('gc', self.gc,
                                arg_synopsis='')
        self.app.settings.integer(['cachedir-artifact-delete-older-than'],
                                  'always delete artifacts older than this '
                                  'period in seconds, (default: 1 week)',
                                  metavar='PERIOD',
                                  group="Storage Options",
                                  default=(60*60*24*7))
        self.app.settings.integer(['cachedir-artifact-keep-younger-than'],
                                  'allow deletion of artifacts older than '
                                  'this period in seconds, (default: 1 day)',
                                  metavar='PERIOD',
                                  group="Storage Options",
                                  default=(60*60*24))

    def disable(self):
        pass

    def gc(self, args):
        '''Make space by removing unused files.

           This command removes all artifacts older than
           --cachedir-artifact-delete-older-than if the file system
           that holds the cache directory has less than --cachedir-min-space
           bytes free.

           It may delete artifacts older than
           --cachedir-artifact-keep-younger-than if it still needs to make
           space.

           It also removes any left over temporary chunks and staging areas
           from failed builds, and any failed deployments.

        '''

        tempdir = self.app.settings['tempdir']
        cachedir = self.app.settings['cachedir']
        tempdir_min_space, cachedir_min_space = \
            morphlib.util.unify_space_requirements(
                tempdir, self.app.settings['tempdir-min-space'],
                cachedir, self.app.settings['cachedir-min-space'])

        self.cleanup_tempdir(tempdir, tempdir_min_space)
        self.cleanup_cachedir(cachedir, cachedir_min_space)
        
    def cleanup_tempdir(self, temp_path, min_space):
        self.app.status(msg='Cleaning up temp dir %(temp_path)s',
                        temp_path=temp_path, chatty=True)
        for subdir in ('deployments', 'failed', 'chunks'):
            if morphlib.util.get_bytes_free_in_path(temp_path) >= min_space:
                self.app.status(msg='Not Removing subdirectory '
                                    '%(subdir)s, enough space already cleared',
                                subdir=os.path.join(temp_path, subdir),
                                chatty=True)
                break
            self.app.status(msg='Removing temp subdirectory: %(subdir)s',
                            subdir=subdir)
            path = os.path.join(temp_path, subdir)
            if os.path.exists(path):
                shutil.rmtree(path)

    def calculate_delete_range(self):
        now = time.time()
        always_delete_age =  \
            now - self.app.settings['cachedir-artifact-delete-older-than']
        may_delete_age =  \
            now - self.app.settings['cachedir-artifact-keep-younger-than']
        return always_delete_age, may_delete_age

    def find_deletable_artifacts(self, lac, max_age, min_age):
        '''Get a list of cache keys in order of how old they are.'''
        contents = list(lac.list_contents())
        always = set(cachekey
                     for cachekey, artifacts, mtime in contents
                     if mtime < max_age)
        maybe = ((cachekey, mtime)
                 for cachekey, artifacts, mtime in contents
                 if max_age <= mtime < min_age)
        return always, [cachekey for cachekey, mtime
                        in sorted(maybe, key=lambda x: x[1])]

    def cleanup_cachedir(self, cache_path, min_space):
        def sufficient_free():
            free = morphlib.util.get_bytes_free_in_path(cache_path)
            return (free >= min_space)
        if sufficient_free():
            self.app.status(msg='Not cleaning up cachedir, '
                                'sufficient space already cleared',
                            chatty=True)
            return
        lac = morphlib.localartifactcache.LocalArtifactCache(
            fs.osfs.OSFS(os.path.join(cache_path, 'artifacts')))
        max_age, min_age = self.calculate_delete_range()
        logging.debug('Must remove artifacts older than timestamp %d'
                      % max_age)
        always_delete, may_delete = \
            self.find_deletable_artifacts(lac, max_age, min_age)
        removed = 0
        source_count = len(always_delete) + len(may_delete)
        logging.debug('Must remove artifacts %s' % repr(always_delete))
        logging.debug('Can remove artifacts %s' % repr(may_delete))

        # Remove all old artifacts
        for cachekey in always_delete:
            self.app.status(msg='Removing source %(cachekey)s',
                            cachekey=cachekey, chatty=True)
            lac.remove(cachekey)
            removed += 1

        # Maybe remove remaining middle-aged artifacts
        for cachekey in may_delete:
            if sufficient_free():
                self.app.status(msg='Finished cleaning up cachedir with '
                                    '%(remaining)d old sources remaining',
                                remaining=(source_count - removed),
                                chatty=True)
                break
            self.app.status(msg='Removing source %(cachekey)s',
                            cachekey=cachekey, chatty=True)
            lac.remove(cachekey)
            removed += 1

        if sufficient_free():
            self.app.status(msg='Made sufficient space in %(cache_path)s '
                                'after removing %(removed)d sources',
                            removed=removed, cache_path=cache_path)
            return
        self.app.status(msg='Unable to clear enough space in %(cache_path)s '
                            'after removing %(removed)d sources. Please '
                            'reduce cachedir-artifact-keep-younger-than, '
                            'clear space from elsewhere, enlarge the disk '
                            'or reduce cachedir-min-space.',
                        cache_path=cache_path, removed=removed,
                        error=True)
