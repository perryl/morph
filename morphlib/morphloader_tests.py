# Copyright (C) 2013-2015  Codethink Limited
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
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# =*= License: GPL-2 =*=


import contextlib
import os
import shutil
import tempfile
import unittest
import warnings

import morphlib


def stratum_template(name):
    '''Returns a valid example stratum, with one chunk reference.'''
    m = morphlib.morphology.Morphology({
        "name": name,
        "kind": "stratum",
        "build-depends": [
            { "morph": "foo" },
        ],
        "chunks": [
            {
                "name": "chunk",
                "repo": "test:repo",
                "ref": "sha1",
                "build-system": "manual",
            }
        ]
    })
    return m


class MorphologyLoaderTests(unittest.TestCase):

    def setUp(self):
        self.loader = morphlib.morphloader.MorphologyLoader()
        self.tempdir = tempfile.mkdtemp()
        self.filename = os.path.join(self.tempdir, 'foo.morph')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_parses_yaml_from_string(self):
        string = '''\
name: foo
kind: chunk
build-system: manual
'''
        morph = self.loader.parse_morphology_text(string, 'test')
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'manual')

    def test_fails_to_parse_utter_garbage(self):
        self.assertRaises(
            morphlib.morphloader.MorphologySyntaxError,
            self.loader.parse_morphology_text, ',,,', 'test')

    def test_fails_to_parse_non_dict(self):
        self.assertRaises(
            morphlib.morphloader.NotADictionaryError,
            self.loader.parse_morphology_text, '- item1\n- item2\n', 'test')

    def test_fails_to_validate_dict_without_kind(self):
        m = morphlib.morphology.Morphology({
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_chunk_with_no_fields(self):
        m = morphlib.morphology.Morphology({
            'kind': 'chunk',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_chunk_with_invalid_field(self):
        m = morphlib.morphology.Morphology({
            'kind': 'chunk',
            'name': 'foo',
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_validate_requires_products_list(self):
        m = morphlib.morphology.Morphology(
            kind='chunk',
            name='foo',
            products={
                'foo-runtime': ['.'],
                'foo-devel': ['.'],
            })
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        e = cm.exception
        self.assertEqual(e.field, 'products')
        self.assertEqual(e.expected, list)
        self.assertEqual(e.actual, dict)
        self.assertEqual(e.morphology_name, 'foo')

    def test_validate_requires_products_list_of_mappings(self):
        m = morphlib.morphology.Morphology(
            kind='chunk',
            name='foo',
            products=[
                'foo-runtime',
            ])
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        e = cm.exception
        self.assertEqual(e.field, 'products[0]')
        self.assertEqual(e.expected, dict)
        self.assertEqual(e.actual, str)
        self.assertEqual(e.morphology_name, 'foo')

    def test_validate_requires_products_list_required_fields(self):
        m = morphlib.morphology.Morphology(
            kind='chunk',
            name='foo',
            products=[
                {
                    'factiart': 'foo-runtime',
                    'cludein': [],
                }
            ])
        with self.assertRaises(morphlib.morphloader.MultipleValidationErrors) \
        as cm:
            self.loader.validate(m)
        exs = cm.exception.errors
        self.assertEqual(type(exs[0]), morphlib.morphloader.MissingFieldError)
        self.assertEqual(exs[0].field, 'products[0].artifact')
        self.assertEqual(type(exs[1]), morphlib.morphloader.MissingFieldError)
        self.assertEqual(exs[1].field, 'products[0].include')
        self.assertEqual(type(exs[2]), morphlib.morphloader.InvalidFieldError)
        self.assertEqual(exs[2].field, 'products[0].cludein')
        self.assertEqual(type(exs[3]), morphlib.morphloader.InvalidFieldError)
        self.assertEqual(exs[3].field, 'products[0].factiart')

    def test_validate_requires_products_list_include_is_list(self):
        m = morphlib.morphology.Morphology(
            kind='chunk',
            name='foo',
            products=[
                {
                    'artifact': 'foo-runtime',
                    'include': '.*',
                }
            ])
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        ex = cm.exception
        self.assertEqual(ex.field, 'products[0].include')
        self.assertEqual(ex.expected, list)
        self.assertEqual(ex.actual, str)
        self.assertEqual(ex.morphology_name, 'foo')

    def test_validate_requires_products_list_include_is_list_of_strings(self):
        m = morphlib.morphology.Morphology(
            kind='chunk',
            name='foo',
            products=[
                {
                    'artifact': 'foo-runtime',
                    'include': [
                        123,
                    ]
                }
            ])
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        ex = cm.exception
        self.assertEqual(ex.field, 'products[0].include[0]')
        self.assertEqual(ex.expected, str)
        self.assertEqual(ex.actual, int)
        self.assertEqual(ex.morphology_name, 'foo')


    def test_fails_to_validate_stratum_with_no_fields(self):
        m = morphlib.morphology.Morphology({
            'kind': 'stratum',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_stratum_with_invalid_field(self):
        m = morphlib.morphology.Morphology({
            'kind': 'stratum',
            'name': 'foo',
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_validate_requires_chunk_refs_in_stratum_to_be_strings(self):
        m = morphlib.morphology.Morphology({
            'kind': 'stratum',
            'name': 'foo',
            'build-depends': [],
            'chunks': [
                {
                    'name': 'chunk',
                    'repo': 'test:repo',
                    'ref': 1,
                    'build-depends': []
                }
            ]
        })
        with self.assertRaises(
                morphlib.morphloader.ChunkSpecRefNotStringError):
            self.loader.validate(m)

    def test_fails_to_validate_stratum_with_empty_refs_for_a_chunk(self):
        m = morphlib.morphology.Morphology({
            'kind': 'stratum',
            'name': 'foo',
            'build-depends': [],
            'chunks' : [
                {
                    'name': 'chunk',
                    'repo': 'test:repo',
                    'ref': None,
                    'build-depends': []
                }
            ]
        })
        with self.assertRaises(
                morphlib.morphloader.EmptyRefError):
            self.loader.validate(m)

    def test_fails_to_validate_stratum_which_build_depends_on_self(self):
        text = '''\
name: bad-stratum
kind: stratum
build-depends:
- morph: strata/bad-stratum.morph
chunks:
- name: chunk
  repo: test:repo
  ref: foo'''
        self.assertRaises(
            morphlib.morphloader.DependsOnSelfError,
            self.loader.load_from_string, text, 'strata/bad-stratum.morph')

    def test_fails_to_validate_system_with_no_fields(self):
        m = morphlib.morphology.Morphology({
            'kind': 'system',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_system_with_invalid_field(self):
        m = morphlib.morphology.Morphology(
            kind="system",
            name="foo",
            arch="blah",
            strata=[
                {'morph': 'bar'},
            ],
            invalid='field')
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_fails_to_validate_morphology_with_unknown_kind(self):
        m = morphlib.morphology.Morphology({
            'kind': 'invalid',
        })
        self.assertRaises(
            morphlib.morphloader.UnknownKindError, self.loader.validate, m)

    def test_validate_requires_unique_stratum_names_within_a_system(self):
        m = morphlib.morphology.Morphology(
            {
                "kind": "system",
                "name": "foo",
                "arch": "x86-64",
                "strata": [
                    {
                        "morph": "stratum",
                        "repo": "test1",
                        "ref": "ref"
                    },
                    {
                        "morph": "stratum",
                        "repo": "test2",
                        "ref": "ref"
                    }
                ]
            })
        self.assertRaises(morphlib.morphloader.DuplicateStratumError,
                          self.loader.validate, m)

    def test_validate_requires_unique_chunk_names_within_a_stratum(self):
        m = morphlib.morphology.Morphology(
            {
                "kind": "stratum",
                "name": "foo",
                "build-depends": [
                    {"morph": "bar"},
                ],
                "chunks": [
                    {
                        "name": "chunk",
                        "repo": "test1",
                        "ref": "ref"
                    },
                    {
                        "name": "chunk",
                        "repo": "test2",
                        "ref": "ref"
                    }
                ]
            })
        self.assertRaises(morphlib.morphloader.DuplicateChunkError,
                          self.loader.validate, m)

    def test_validate_requires_a_valid_architecture(self):
        m = morphlib.morphology.Morphology(
            kind="system",
            name="foo",
            arch="blah",
            strata=[
                {'morph': 'bar'},
            ])
        self.assertRaises(
            morphlib.morphloader.UnknownArchitectureError,
            self.loader.validate, m)

    def test_validate_requires_build_deps_or_bootstrap_mode_for_strata(self):
        m = stratum_template("stratum-no-bdeps-no-bootstrap")

        self.loader.validate(m)

        del m['build-depends']
        self.assertRaises(
            morphlib.morphloader.NoStratumBuildDependenciesError,
            self.loader.validate, m)

        m['chunks'][0]['build-mode'] = 'bootstrap'
        self.loader.validate(m)

    def test_validate_stratum_build_deps_are_list(self):
        m = stratum_template("stratum-invalid-bdeps")
        m['build-depends'] = 0.1
        self.assertRaises(
            morphlib.morphloader.InvalidTypeError,
            self.loader.validate, m)

    def test_validate_chunk_build_deps_are_list(self):
        m = stratum_template("stratum-invalid-bdeps")
        m['chunks'][0]['build-depends'] = 0.1
        self.assertRaises(
            morphlib.morphloader.InvalidTypeError,
            self.loader.validate, m)

    def test_validate_chunk_has_build_instructions(self):
        m = stratum_template("stratum-no-build-instructions")
        del m['chunks'][0]['build-system']
        self.assertRaises(
            morphlib.morphloader.ChunkSpecNoBuildInstructionsError,
            self.loader.validate, m)

    def test_validate_chunk_conflicting_build_instructions(self):
        m = stratum_template("stratum-conflicting-build-instructions")
        m['chunks'][0]['morph'] = 'conflicting-information'
        self.assertRaises(
            morphlib.morphloader.ChunkSpecConflictingFieldsError,
            self.loader.validate, m)

    def test_validate_requires_chunks_in_strata(self):
        m = stratum_template("stratum-no-chunks")
        del m['chunks']
        self.assertRaises(
            morphlib.morphloader.EmptyStratumError,
            self.loader.validate, m)

    def test_validate_requires_strata_in_system(self):
        m = morphlib.morphology.Morphology(
            name='system',
            kind='system',
            arch='testarch')
        self.assertRaises(
            morphlib.morphloader.MissingFieldError,
            self.loader.validate, m)

    def test_validate_requires_list_of_strata_in_system(self):
        for v in (None, {}):
            m = morphlib.morphology.Morphology(
                name='system',
                kind='system',
                arch='testarch',
                strata=v)
            with self.assertRaises(
                morphlib.morphloader.SystemStrataNotListError) as cm:

                self.loader.validate(m)
            self.assertEqual(cm.exception.strata_type, type(v))

    def test_validate_requires_non_empty_strata_in_system(self):
        m = morphlib.morphology.Morphology(
            name='system',
            kind='system',
            arch='testarch',
            strata=[])
        self.assertRaises(
            morphlib.morphloader.EmptySystemError,
            self.loader.validate, m)

    def test_validate_requires_stratum_specs_in_system(self):
        m = morphlib.morphology.Morphology(
            name='system',
            kind='system',
            arch='testarch',
            strata=["foo"])
        with self.assertRaises(
            morphlib.morphloader.SystemStratumSpecsNotMappingError) as cm:

            self.loader.validate(m)
        self.assertEqual(cm.exception.strata, ["foo"])

    def test_validate_requires_unique_deployment_names_in_cluster(self):
        subsystem = [{'morph': 'baz', 'deploy': {'foobar': None}}]
        m = morphlib.morphology.Morphology(
            name='cluster',
            kind='cluster',
            systems=[{'morph': 'foo',
                      'deploy': {'deployment': {}},
                      'subsystems': subsystem},
                     {'morph': 'bar',
                      'deploy': {'deployment': {}},
                      'subsystems': subsystem}])
        with self.assertRaises(
                morphlib.morphloader.DuplicateDeploymentNameError) as cm:
            self.loader.validate(m)
        ex = cm.exception
        self.assertIn('foobar', ex.duplicates)
        self.assertIn('deployment', ex.duplicates)

    def test_loads_yaml_from_string(self):
        string = '''\
name: foo
kind: chunk
build-system: manual
'''
        morph = self.loader.load_from_string(string)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'manual')

    def test_loads_json_from_string(self):
        string = '''\
{
    "name": "foo",
    "kind": "chunk",
    "build-system": "manual"
}
'''
        morph = self.loader.load_from_string(string)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'manual')

    def test_loads_from_file(self):
        with open(self.filename, 'w') as f:
            f.write('''\
name: foo
kind: chunk
build-system: manual
''')
        morph = self.loader.load_from_file(self.filename)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'manual')

    def test_saves_to_string(self):
        morph = morphlib.morphology.Morphology({
            'name': 'foo',
            'kind': 'chunk',
            'build-system': 'manual',
        })
        text = self.loader.save_to_string(morph)

        # The following verifies that the YAML is written in a normalised
        # fashion.
        self.assertEqual(text, '''\
name: foo
kind: chunk
build-system: manual
''')

    def test_saves_to_file(self):
        morph = morphlib.morphology.Morphology({
            'name': 'foo',
            'kind': 'chunk',
            'build-system': 'manual',
        })
        self.loader.save_to_file(self.filename, morph)

        with open(self.filename) as f:
            text = f.read()

        # The following verifies that the YAML is written in a normalised
        # fashion.
        self.assertEqual(text, '''\
name: foo
kind: chunk
build-system: manual
''')

    def test_validate_does_not_set_defaults(self):
        m = morphlib.morphology.Morphology({
            'kind': 'chunk',
            'name': 'foo',
        })
        self.loader.validate(m)
        self.assertEqual(sorted(m.keys()), sorted(['kind', 'name']))

    def test_sets_defaults_for_chunks(self):
        m = morphlib.morphology.Morphology({
            'kind': 'chunk',
            'name': 'foo',
        })
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'chunk',
                'name': 'foo',
                'description': '',
                'build-system': 'manual',
                'build-mode': 'staging',

                'configure-commands': None,
                'pre-configure-commands': None,
                'post-configure-commands': None,

                'build-commands': None,
                'pre-build-commands': None,
                'post-build-commands': None,

                'test-commands': None,
                'pre-test-commands': None,
                'post-test-commands': None,

                'install-commands': None,
                'pre-install-commands': None,
                'post-install-commands': None,

                'strip-commands': None,
                'pre-strip-commands': None,
                'post-strip-commands': None,

                'products': [],
                'system-integration': [],
                'devices': [],
                'max-jobs': None,
                'prefix': '/usr',
            })

    def test_unsets_defaults_for_chunks(self):
        m = morphlib.morphology.Morphology({
            'kind': 'chunk',
            'name': 'foo',
            'build-system': 'manual',
        })
        self.loader.unset_defaults(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'chunk',
                'name': 'foo',
            })

    def test_sets_defaults_for_strata(self):
        m = morphlib.morphology.Morphology({
            'kind': 'stratum',
            'name': 'foo',
            'chunks': [
                {
                    'name': 'bar',
                    'repo': 'bar',
                    'ref': 'bar',
                    'morph': 'bar',
                    'build-mode': 'bootstrap',
                    'build-depends': [],
                },
            ],
        })
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'stratum',
                'name': 'foo',
                'description': '',
                'build-depends': [],
                'chunks': [
                    {
                        'name': 'bar',
                        "repo": "bar",
                        "ref": "bar",
                        "morph": "bar",
                        'build-mode': 'bootstrap',
                        'build-depends': [],
                        'prefix': '/usr',
                    },
                ],
                'products': [],
            })

    def test_unsets_defaults_for_strata(self):
        test_dict = {
            'kind': 'stratum',
            'name': 'foo',
            'chunks': [
                {
                    'name': 'bar',
                    "ref": "bar",
                    'build-mode': 'staging',
                    'build-depends': [],
                    'prefix': '/usr',
                },
            ],
        }
        test_dict_with_build_depends = dict(test_dict)
        test_dict_with_build_depends["build-depends"] = []
        m = morphlib.morphology.Morphology(test_dict_with_build_depends)
        self.loader.unset_defaults(m)
        self.assertEqual(
            dict(m),
            test_dict)

    def test_sets_defaults_for_system(self):
        m = morphlib.morphology.Morphology(
            kind='system',
            name='foo',
            arch='testarch',
            strata=[
                {
                    'morph': 'bar',
                },
            ])
        self.loader.set_defaults(m)
        self.assertEqual(
            {
                'kind': 'system',
                'name': 'foo',
                'description': '',
                'arch': 'testarch',
                'strata': [
                    {
                        'morph': 'bar',
                    },
                ],
                'configuration-extensions': [],
            },
            dict(m))

    def test_unsets_defaults_for_system(self):
        m = morphlib.morphology.Morphology(
            {
                'description': '',
                'kind': 'system',
                'name': 'foo',
                'arch': 'testarch',
                'strata': [
                    {
                        'morph': 'bar',
                    },
                ],
                'configuration-extensions': [],
            })
        self.loader.unset_defaults(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'system',
                'name': 'foo',
                'arch': 'testarch',
                'strata': [
                    {'morph': 'bar'},
                ],
            })

    def test_sets_defaults_for_cluster(self):
        m = morphlib.morphology.Morphology(
            name='foo',
            kind='cluster',
            systems=[
                {'morph': 'foo'},
                {'morph': 'bar'}])
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(m['systems'],
            [{'morph': 'foo',
              'deploy-defaults': {},
              'deploy': {}},
             {'morph': 'bar',
              'deploy-defaults': {},
              'deploy': {}}])

    def test_unsets_defaults_for_cluster(self):
        m = morphlib.morphology.Morphology(
            name='foo',
            kind='cluster',
            description='',
            systems=[
                {'morph': 'foo',
                 'deploy-defaults': {},
                 'deploy': {}},
                {'morph': 'bar',
                 'deploy-defaults': {},
                 'deploy': {}}])
        self.loader.unset_defaults(m)
        self.assertNotIn('description', m)
        self.assertEqual(m['systems'],
                         [{'morph': 'foo'},
                          {'morph': 'bar'}])

    def test_sets_stratum_chunks_repo_from_name(self):
        m = morphlib.morphology.Morphology(
            {
                "name": "foo",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "le-chunk",
                        "ref": "ref",
                        "build-system": "manual",
                        "build-depends": [],
                    }
                ]
            })

        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(m['chunks'][0]['repo'], 'le-chunk')

    def test_collapses_stratum_chunks_repo_from_name(self):
        m = morphlib.morphology.Morphology(
            {
                "name": "foo",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "le-chunk",
                        "repo": "le-chunk",
                        "morph": "le-chunk",
                        "ref": "ref",
                        "build-system": "manual",
                        "build-depends": [],
                    }
                ]
            })

        self.loader.unset_defaults(m)
        self.assertTrue('repo' not in m['chunks'][0])

    def test_convertes_max_jobs_to_an_integer(self):
        m = morphlib.morphology.Morphology(
            {
                "name": "foo",
                "kind": "chunk",
                "max-jobs": "42"
            })
        self.loader.set_defaults(m)
        self.assertEqual(m['max-jobs'], 42)

    def test_parses_simple_cluster_morph(self):
        string = '''
            name: foo
            kind: cluster
            systems:
                - morph: bar
        '''
        m = self.loader.parse_morphology_text(string, 'test')
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(m['name'], 'foo')
        self.assertEqual(m['kind'], 'cluster')
        self.assertEqual(m['systems'][0]['morph'], 'bar')

    @contextlib.contextmanager
    def catch_warnings(*warning_classes):
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.resetwarnings()
            for warning_class in warning_classes:
                warnings.simplefilter("always", warning_class)
            yield caught_warnings

    def test_unordered_asciibetically_after_ordered(self):
        # We only get morphologies with arbitrary keys in clusters
        m = morphlib.morphology.Morphology(
            name='foo',
            kind='cluster',
            systems=[
                {
                    'morph': 'system-name',
                    'repo': 'test:morphs',
                    'ref': 'master',
                    'deploy': {
                        'deployment-foo': {
                            'type': 'tarball',
                            'location': '/tmp/path.tar',
                            'HOSTNAME': 'aasdf',
                        }
                    }
                }
            ]
        )
        s = self.loader.save_to_string(m)
        # root field order
        self.assertLess(s.find('name'), s.find('kind'))
        self.assertLess(s.find('kind'), s.find('systems'))
        # systems field order
        self.assertLess(s.find('morph'), s.find('repo'))
        self.assertLess(s.find('repo'), s.find('ref'))
        self.assertLess(s.find('ref'), s.find('deploy'))
        # deployment keys field order
        self.assertLess(s.find('type'), s.find('location'))
        self.assertLess(s.find('location'), s.find('HOSTNAME'))

    def test_multi_line_round_trip(self):
        s = ('name: foo\n'
             'kind: bar\n'
             'description: |\n'
             '  1 2 3\n'
             '  4 5 6\n'
             '  7 8 9\n')
        m = self.loader.parse_morphology_text(s, 'string')
        self.assertEqual(s, self.loader.save_to_string(m))

    def test_smoketest_multi_line_unicode(self):
        m = morphlib.morphology.Morphology(
            name=u'foo',
            description=u'1 2 3\n4 5 6\n7 8 9\n',
        )
        s = self.loader.save_to_string(m)

    def test_smoketest_multi_line_unicode_encoded(self):
        m = morphlib.morphology.Morphology(
            name=u'foo \u263A'.encode('utf-8'),
            description=u'1 \u263A\n2 \u263A\n3 \u263A\n'.encode('utf-8'),
        )
        s = self.loader.save_to_string(m)

    def test_smoketest_binary_garbage(self):
        m = morphlib.morphology.Morphology(
            description='\x92',
        )
        s = self.loader.save_to_string(m)


    def test_unknown_build_system(self):
        m = morphlib.morphology.Morphology({
            'kind': 'chunk',
            'name': 'foo',
            'build-system': 'monkey scientist',
        })
        with self.assertRaises(morphlib.morphloader.UnknownBuildSystemError):
            s = self.loader.set_commands(m)
