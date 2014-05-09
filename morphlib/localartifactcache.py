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
import hashlib
import json
import logging
import os
import tempfile
import time

import morphlib


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
        for filepath in self.cachefs.walkfiles():
            filename = os.path.basename(filepath)
            cachekey = filename[:64]
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

    def _calculate_checksum(self, artifact_filename):
        # FIXME: pick a block size
        block_size = 10 * 1024 * 1024 # 10MB
        hasher = hashlib.sha1()
        with open(artifact_filename, 'rb') as f:
            while True:
                data = f.read(block_size)
                if len(data) == 0:
                    break
                hasher.update(data)
        return hasher.hexdigest()

    def _calculate_unpacked_chunk_checksum(self, chunk_dir):
        # create a chunk artifact from the unpacked chunk and return the
        # checksum. It should be identical, right ??
        #
        # This code is not the same code used in builder2.ChunkBuilder.
        # It's actually much better and as soon as I've checked that it
        # produces identical results it should be used in builder2 too.
        # I'm especially confused why bins.create_chunk() removes files,
        # instead of leaving it up to the ChunkBuilder code.

        def filepaths(destdir):
            for dirname, subdirs, basenames in os.walk(destdir):
                subdirsymlinks = [os.path.join(dirname, x) for x in subdirs
                                    if os.path.islink(x)]
                filenames = [os.path.join(dirname, x) for x in basenames]
                for path in [dirname] + subdirsymlinks + filenames:
                    yield path
        paths = filepaths(chunk_dir)

        with tempfile.TemporaryFile() as f:
            checksum = morphlib.bins.create_chunk_2(
                chunk_dir, f, name=None, include=paths)

        return checksum

    def validate(self, unpacked_chunk_cache_dir):
        '''Check for corruption in all cached binary artifacts.'''
        bad = {}
        no_checksum = []

        def error(msg, *args):
            msg = msg % args
            bad[cache_key] = bad.get(cache_key, []) + [msg]
            logging.error('Found artifact corruption: %s' % msg)

        for cache_key, artifacts, last_used in self.list_contents():
            binary_artifacts = list(artifacts - {'build-log', 'meta'})

            if len(cache_key) < 64 or len(binary_artifacts) == 0:
                # Morph itself leaves junk temporary files around in the
                # artifact cache directory, as does the user. Ignore it.
                logging.info('Ignoring %s' % cache_key)
                continue

            kind = binary_artifacts[0].split('.', 1)[0]

            if kind == 'stratum':
                continue

            display_name = '%s %s' % (kind, cache_key)
            logging.info('Checking artifacts for %s' % display_name)

            filename = self._source_metadata_filename(None, cache_key, 'meta')
            if not os.path.exists(filename):
                # This artifact was downloaded from Trove. :(
                logging.warning('No source metadata for %s.' % display_name)
                continue

            try:
                with open(filename) as f:
                    build_info = json.load(f)
            except (IOError, OSError, ValueError) as e:
                error(
                    '%s: unable to read source metadata: %s', display_name, e)
                continue

            if 'checksums' not in build_info:
                # This is the case for artifacts created by old versions of
                # Morph. We don't raise an error, for compatiblity.
                logging.warning('No checksums for %s.', display_name)
                no_checksum.append(display_name)
                continue

            for artifact in binary_artifacts:
                display_name = '%s.%s' % (cache_key, artifact)

                if '.' not in artifact:
                    logging.warning('Invalid artifact name %s' % artifact)
                    continue

                _, artifact_name = artifact.split('.', 1)
                expected_checksum = build_info['checksums'].get(artifact_name)

                if expected_checksum == None:
                    error('%s: checksum missing!', display_name)
                    continue

                artifact_filename = self.cachefs.getsyspath(
                    '%s.%s' % (cache_key, artifact))
                checksum = self._calculate_checksum(artifact_filename)

                if checksum != expected_checksum:
                    error('%s has bad checksum %s', display_name, checksum)

                if kind == 'chunk':
                    unpacked_name = '%s.%s.d' % (cache_key, artifact)
                    unpacked_path = os.path.join(
                        unpacked_chunk_cache_dir, unpacked_name)
                    if os.path.exists(unpacked_path):
                        checksum = self._calculate_unpacked_chunk_checksum(
                            unpacked_path)

                        if checksum != expected_checksum:
                            error('unpacked chunk %s has bad checksum %s',
                                unpacked_path, checksum)

        return bad, no_checksum
