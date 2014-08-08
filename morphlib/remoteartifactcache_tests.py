# Copyright (C) 2012-2014  Codethink Limited
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


import StringIO
import unittest
import urllib2

import morphlib


class RemoteArtifactCacheTests(unittest.TestCase):

    def setUp(self):
        loader = morphlib.morphloader.MorphologyLoader()
        morph = loader.load_from_string(
            '''
                name: chunk
                kind: chunk
                products:
                    - artifact: chunk-runtime
                      include:
                          - usr/bin
                          - usr/sbin
                          - usr/lib
                          - usr/libexec
                    - artifact: chunk-devel
                      include:
                          - usr/include
                    - artifact: chunk-doc
                      include:
                          - usr/share/doc
            ''')
        self.source = morphlib.source.Source(
            'repo', 'ref', 'sha1', 'tree', morph, 'chunk.morph')
        self.runtime_artifact = morphlib.artifact.Artifact(
            self.source, 'chunk-runtime')
        self.runtime_artifact.cache_key = 'CHUNK-RUNTIME'
        self.devel_artifact = morphlib.artifact.Artifact(
            self.source, 'chunk-devel')
        self.devel_artifact.cache_key = 'CHUNK-DEVEL'
        self.doc_artifact = morphlib.artifact.Artifact(
            self.source, 'chunk-doc')
        self.doc_artifact.cache_key = 'CHUNK-DOC'

        self.existing_files = set([
            self.runtime_artifact.basename(),
            self.devel_artifact.basename(),
            self.runtime_artifact.metadata_basename('meta'),
            '%s.%s' % (self.runtime_artifact.cache_key, 'meta'),
        ])

        self.server_url = 'http://foo.bar:8080'
        self.cache = morphlib.remoteartifactcache.RemoteArtifactCache(
            self.server_url)
        self.cache._has_file = self._has_file
        self.cache._get_file = self._get_file

    def _has_file(self, filename):
        return filename in self.existing_files

    def _get_file(self, filename):
        if filename in self.existing_files:
            return StringIO.StringIO('%s' % filename)
        else:
            raise urllib2.URLError('foo')

    def test_sets_server_url(self):
        self.assertEqual(self.cache.server_url, self.server_url)

    def test_has_existing_artifact(self):
        self.assertTrue(self.cache.has(self.runtime_artifact))

    def test_has_a_different_existing_artifact(self):
        self.assertTrue(self.cache.has(self.devel_artifact))

    def test_does_not_have_a_non_existent_artifact(self):
        self.assertFalse(self.cache.has(self.doc_artifact))

    def test_has_existing_artifact_metadata(self):
        self.assertTrue(self.cache.has_artifact_metadata(
            self.runtime_artifact, 'meta'))

    def test_does_not_have_non_existent_artifact_metadata(self):
        self.assertFalse(self.cache.has_artifact_metadata(
            self.runtime_artifact, 'non-existent-meta'))

    def test_has_existing_source_metadata(self):
        self.assertTrue(self.cache.has_source_metadata(
            self.runtime_artifact.source,
            self.runtime_artifact.cache_key,
            'meta'))

    def test_does_not_have_non_existent_source_metadata(self):
        self.assertFalse(self.cache.has_source_metadata(
            self.runtime_artifact.source,
            self.runtime_artifact.cache_key,
            'non-existent-meta'))

    def test_get_existing_artifact(self):
        handle = self.cache.get(self.runtime_artifact)
        data = handle.read()
        self.assertEqual(data, self.runtime_artifact.basename())

    def test_get_a_different_existing_artifact(self):
        handle = self.cache.get(self.devel_artifact)
        data = handle.read()
        self.assertEqual(data, self.devel_artifact.basename())

    def test_fails_to_get_a_non_existent_artifact(self):
        self.assertRaises(morphlib.remoteartifactcache.GetError,
                          self.cache.get, self.doc_artifact,
                          log=lambda *args: None)

    def test_get_existing_artifact_metadata(self):
        handle = self.cache.get_artifact_metadata(
            self.runtime_artifact, 'meta')
        data = handle.read()
        self.assertEqual(
            data, '%s.%s' % (self.runtime_artifact.basename(), 'meta'))

    def test_fails_to_get_non_existent_artifact_metadata(self):
        self.assertRaises(
            morphlib.remoteartifactcache.GetArtifactMetadataError,
            self.cache.get_artifact_metadata,
            self.runtime_artifact,
            'non-existent-meta',
            log=lambda *args: None)

    def test_get_existing_source_metadata(self):
        handle = self.cache.get_source_metadata(
            self.runtime_artifact.source,
            self.runtime_artifact.cache_key,
            'meta')
        data = handle.read()
        self.assertEqual(
            data, '%s.%s' % (self.runtime_artifact.cache_key, 'meta'))

    def test_fails_to_get_non_existent_source_metadata(self):
        self.assertRaises(
            morphlib.remoteartifactcache.GetSourceMetadataError,
            self.cache.get_source_metadata,
            self.runtime_artifact.source,
            self.runtime_artifact.cache_key,
            'non-existent-meta')

    def test_escapes_pluses_in_request_urls(self):
        returned_url = self.cache._request_url('gtk+')
        correct_url = '%s/1.0/artifacts?filename=gtk%%2B' % self.server_url
        self.assertEqual(returned_url, correct_url)
