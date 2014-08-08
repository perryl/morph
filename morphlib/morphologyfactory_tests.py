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


import unittest

import morphlib
from morphlib.morphologyfactory import (MorphologyFactory,
                                        MorphologyNotFoundError,
                                        NotcachedError)
from morphlib.remoterepocache import CatFileError


class FakeRemoteRepoCache(object):

    def cat_file(self, reponame, sha1, filename):
        if filename.endswith('.morph'):
            return '''{
                 "name": "%s",
                 "kind": "chunk",
                 "build-system": "bar"
             }''' % filename[:-len('.morph')]
        return 'text'

    def ls_tree(self, reponame, sha1):
        return []

class FakeLocalRepo(object):

    morphologies = {
        'chunk.morph': '''
                name: chunk
                kind: chunk
                build-system: bar
            ''',
        'chunk-split.morph': '''
                name: chunk-split
                kind: chunk
                build-system: bar
                products:
                    - artifact: chunk-split-runtime
                      include: []
                    - artifact: chunk-split-devel
                      include: []
            ''',
        'stratum.morph': '''
                name: stratum
                kind: stratum
                chunks:
                    - name: chunk
                      repo: test:repo
                      ref: sha1
                      build-mode: bootstrap
                      build-depends: []
            ''',
        'stratum-no-chunk-bdeps.morph': '''
                name: stratum-no-chunk-bdeps
                kind: stratum
                chunks:
                    - name: chunk
                      repo: test:repo
                      ref: sha1
                      build-mode: bootstrap
            ''',
        'stratum-no-bdeps-no-bootstrap.morph': '''
                name: stratum-no-bdeps-no-bootstrap
                kind: stratum
                chunks:
                    - name: chunk
                      repo: test:repo
                      ref: sha1
                      build-depends: []
            ''',
        'stratum-bdeps-no-bootstrap.morph': '''
                name: stratum-bdeps-no-bootstrap
                kind: stratum
                build-depends:
                    - morph: stratum
                chunks:
                    - name: chunk
                      repo: test:repo
                      ref: sha1
                      build-depends: []
            ''',
        'stratum-empty.morph': '''
                name: stratum-empty
                kind: stratum
            ''',
        'system.morph': '''
                name: system
                kind: system
                arch: %(arch)s
                strata:
                    - morph: stratum
            ''',
        'parse-error.morph': ''' name''',
        'name-mismatch.morph': '''
                name: fred
                kind: stratum
            ''',
    }

    def __init__(self):
        self.arch = 'x86_64'

    def cat(self, sha1, filename):
        if filename in self.morphologies:
            values = {
                'arch': self.arch,
            }
            return self.morphologies[filename] % values
        elif filename.endswith('.morph'):
            return '''{
                "name": "%s",
                "kind": "chunk",
                "build-system": "bar"
            }''' % filename[:-len('.morph')]
        return 'text'

    def ls_tree(self, sha1):
        return self.morphologies.keys()

class FakeLocalRepoCache(object):

    def __init__(self, lr):
        self.lr = lr

    def has_repo(self, reponame):
        return True

    def get_repo(self, reponame):
        return self.lr


class FakeApp(object):

    def status(self, **kwargs):
        pass


class MorphologyFactoryTests(unittest.TestCase):

    def setUp(self):
        self.lr = FakeLocalRepo()
        self.lrc = FakeLocalRepoCache(self.lr)
        self.rrc = FakeRemoteRepoCache()
        self.mf = MorphologyFactory(self.lrc, self.rrc, app=FakeApp())
        self.lmf = MorphologyFactory(self.lrc, None)

    def nolocalfile(self, *args):
        raise IOError('File not found')

    def noremotefile(self, *args):
        raise CatFileError('reponame', 'ref', 'filename')

    def localmorph(self, *args):
        return ['chunk.morph']

    def nolocalmorph(self, *args):
        if args[-1].endswith('.morph'):
            raise IOError('File not found')
        return 'text'

    def autotoolsbuildsystem(self, *args):
        return ['configure.in']

    def remotemorph(self, *args):
        return ['remote-chunk.morph']

    def noremotemorph(self, *args):
        if args[-1].endswith('.morph'):
            raise CatFileError('reponame', 'ref', 'filename')
        return 'text'

    def doesnothaverepo(self, reponame):
        return False

    def test_gets_morph_from_local_repo(self):
        self.lr.ls_tree = self.localmorph
        morph = self.mf.get_morphology('reponame', 'sha1',
                                       'chunk.morph')
        self.assertEqual('chunk', morph['name'])

    def test_gets_morph_from_remote_repo(self):
        self.rrc.ls_tree = self.remotemorph
        self.lrc.has_repo = self.doesnothaverepo
        morph = self.mf.get_morphology('reponame', 'sha1',
                                       'remote-chunk.morph')
        self.assertEqual('remote-chunk', morph['name'])

    def test_autodetects_local_morphology(self):
        self.lr.cat = self.nolocalmorph
        self.lr.ls_tree = self.autotoolsbuildsystem
        morph = self.mf.get_morphology('reponame', 'sha1',
                                       'assumed-local.morph')
        self.assertEqual('assumed-local', morph['name'])

    def test_autodetects_remote_morphology(self):
        self.lrc.has_repo = self.doesnothaverepo
        self.rrc.cat_file = self.noremotemorph
        self.rrc.ls_tree = self.autotoolsbuildsystem
        morph = self.mf.get_morphology('reponame', 'sha1',
                                       'assumed-remote.morph')
        self.assertEqual('assumed-remote', morph['name'])

    def test_raises_error_when_no_local_morph(self):
        self.lr.cat = self.nolocalfile
        self.assertRaises(MorphologyNotFoundError, self.mf.get_morphology,
                          'reponame', 'sha1', 'unreached.morph')

    def test_raises_error_when_fails_no_remote_morph(self):
        self.lrc.has_repo = self.doesnothaverepo
        self.rrc.cat_file = self.noremotefile
        self.assertRaises(MorphologyNotFoundError, self.mf.get_morphology,
                          'reponame', 'sha1', 'unreached.morph')

    def test_raises_error_when_name_mismatches(self):
        self.assertRaises(morphlib.Error, self.mf.get_morphology,
                          'reponame', 'sha1', 'name-mismatch.morph')

    def test_looks_locally_with_no_remote(self):
        self.lr.ls_tree = self.localmorph
        morph = self.lmf.get_morphology('reponame', 'sha1',
                                        'chunk.morph')
        self.assertEqual('chunk', morph['name'])

    def test_autodetects_locally_with_no_remote(self):
        self.lr.cat = self.nolocalmorph
        self.lr.ls_tree = self.autotoolsbuildsystem
        morph = self.mf.get_morphology('reponame', 'sha1',
                                        'assumed-local.morph')
        self.assertEqual('assumed-local', morph['name'])

    def test_fails_when_local_not_cached_and_no_remote(self):
        self.lrc.has_repo = self.doesnothaverepo
        self.assertRaises(NotcachedError, self.lmf.get_morphology,
                          'reponame', 'sha1', 'unreached.morph')

    def test_sets_builds_artifacts_for_simple_chunk(self):
        morph = self.mf.get_morphology('reponame', 'sha1', 'chunk.morph')
        self.assertEqual(morph.builds_artifacts, ['chunk'])

    def test_sets_builds_artifacts_for_split_chunk(self):
        morph = self.mf.get_morphology('reponame', 'sha1', 'chunk-split.morph')
        self.assertEqual(morph.builds_artifacts,
                         ['chunk-split-runtime', 'chunk-split-devel'])

    def test_sets_builds_artifacts_for_stratum(self):
        morph = self.mf.get_morphology('reponame', 'sha1', 'stratum.morph')
        self.assertEqual(morph.builds_artifacts, ['stratum'])

    def test_sets_build_artifacts_for_system(self):
        self.lr.arch = 'x86_32'
        morph = self.mf.get_morphology('reponame', 'sha1', 'system.morph')
        self.assertEqual(morph.builds_artifacts, ['system-rootfs'])

    def test_does_not_set_needs_artifact_metadata_cached_for_chunk(self):
        morph = self.mf.get_morphology('reponame', 'sha1', 'chunk.morph')
        self.assertEqual(morph.needs_artifact_metadata_cached, False)

    def test_sets_artifact_metadata_cached_for_stratum(self):
        morph = self.mf.get_morphology('reponame', 'sha1', 'stratum.morph')
        self.assertEqual(morph.needs_artifact_metadata_cached, True)

    def test_does_not_set_artifact_metadata_cached_for_system(self):
        morph = self.mf.get_morphology('reponame', 'sha1', 'system.morph')
        self.assertEqual(morph.needs_artifact_metadata_cached, False)


    def test_arch_is_validated(self):
        self.lr.arch = 'unknown'
        self.assertRaises(morphlib.Error, self.mf.get_morphology,
                          'reponame', 'sha1', 'system.morph')

    def test_arch_arm_defaults_to_le(self):
        self.lr.arch = 'armv7'
        morph = self.mf.get_morphology('reponame', 'sha1', 'system.morph')
        self.assertEqual(morph['arch'], 'armv7l')

    def test_fails_on_parse_error(self):
        self.assertRaises(morphlib.Error, self.mf.get_morphology,
                          'reponame', 'sha1', 'parse-error.morph')

    def test_fails_on_no_chunk_bdeps(self):
        self.assertRaises(morphlib.morphloader.NoBuildDependenciesError,
                          self.mf.get_morphology, 'reponame', 'sha1',
                          'stratum-no-chunk-bdeps.morph')

    def test_fails_on_no_bdeps_or_bootstrap(self):
        self.assertRaises(
            morphlib.morphloader.NoStratumBuildDependenciesError,
            self.mf.get_morphology, 'reponame', 'sha1',
            'stratum-no-bdeps-no-bootstrap.morph')

    def test_succeeds_on_bdeps_no_bootstrap(self):
        self.mf.get_morphology(
            'reponame', 'sha1',
            'stratum-bdeps-no-bootstrap.morph')

    def test_fails_on_empty_stratum(self):
        self.assertRaises(
            morphlib.morphloader.EmptyStratumError,
            self.mf.get_morphology, 'reponame', 'sha1', 'stratum-empty.morph')

