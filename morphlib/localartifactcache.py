# Copyright (C) 2012,2013  Codethink Limited
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


import collections
import os
import time

import morphlib
import logging


class LocalArtifactCache(object):
    '''Abstraction over the local artifact cache

       It provides methods for getting a file handle to cached artifacts
       so that the layout of the cache need not be known.

       It also updates modification times of artifacts so that it can track
       when they were last used, so it can be requested to clean up if
       disk space is low.

       Modification time is updated in both the get and has methods.

       NOTE: Parts of the build assume that every artifact of a source is
       available, so all the artifacts of a source need to be removed together.

       This complication needs to be handled either during the fetch logic, by
       updating the mtime of every artifact belonging to a source, or at
       cleanup time by only removing an artifact if every artifact belonging to
       a source is too old, and then remove them all at once.

       Since the cleanup logic will be complicated for other reasons it makes
       sense to put the complication there.
       '''

    def __init__(self, cachefs):
        self.cachefs = cachefs

    def put(self, artifact):
        filename = self.artifact_filename(artifact)
        logging.debug('Artifact cache put() has filename: ', filename)
        return morphlib.savefile.SaveFile(filename, mode='w')

    def put_artifact_metadata(self, artifact, name):
        filename = self._artifact_metadata_filename(artifact, name)
        return morphlib.savefile.SaveFile(filename, mode='w')

    def put_source_metadata(self, source, cachekey, name):
        filename = self._source_metadata_filename(source, cachekey, name)
        return morphlib.savefile.SaveFile(filename, mode='w')

    def _has_file(self, filename):
        if os.path.exists(filename):
            os.utime(filename, None)
            return True
        return False

    def has(self, artifact):
        filename = self.artifact_filename(artifact)
        return self._has_file(filename)

    def has_artifact_metadata(self, artifact, name):
        filename = self._artifact_metadata_filename(artifact, name)
        return self._has_file(filename)

    def has_source_metadata(self, source, cachekey, name):
        filename = self._source_metadata_filename(source, cachekey, name)
        return self._has_file(filename)

    def get(self, artifact):
        filename = self.artifact_filename(artifact)
        os.utime(filename, None)
        return open(filename)

    def get_artifact_metadata(self, artifact, name):
        filename = self._artifact_metadata_filename(artifact, name)
        os.utime(filename, None)
        return open(filename)

    def get_source_metadata(self, source, cachekey, name):
        filename = self._source_metadata_filename(source, cachekey, name)
        os.utime(filename, None)
        return open(filename)

    def artifact_filename(self, artifact):
        return self.cachefs.getsyspath(artifact.basename())

    def _artifact_metadata_filename(self, artifact, name):
        return self.cachefs.getsyspath(artifact.metadata_basename(name))

    def _source_metadata_filename(self, source, cachekey, name):
        return self.cachefs.getsyspath('%s.%s' % (cachekey, name))

    def clear(self):
        '''Clear everything from the artifact cache directory.
        
        After calling this, the artifact cache will be entirely empty.
        Caveat caller.

         '''
        for filename in self.cachefs.walkfiles():
            self.cachefs.remove(filename)

    def list_contents(self):
        '''Return the set of sources cached and related information.

           returns a [(cache_key, set(artifacts), last_used)]

        '''
        CacheInfo = collections.namedtuple('CacheInfo', ('artifacts', 'mtime'))
        contents = collections.defaultdict(lambda: CacheInfo(set(), 0))
        for filename in self.cachefs.walkfiles():
            cachekey = filename[:63]
            artifact = filename[65:]
            artifacts, max_mtime = contents[cachekey]
            artifacts.add(artifact)
            art_info = self.cachefs.getinfo(filename)
            time_t = art_info['modified_time'].timetuple()
            contents[cachekey] = CacheInfo(artifacts,
                                           max(max_mtime, time.mktime(time_t)))
        return ((cache_key, info.artifacts, info.mtime)
                for cache_key, info in contents.iteritems())

    def remove(self, cachekey):
        '''Remove all artifacts associated with the given cachekey.'''
        for filename in (x for x in self.cachefs.walkfiles()
                         if x.startswith(cachekey)):
            self.cachefs.remove(filename)
