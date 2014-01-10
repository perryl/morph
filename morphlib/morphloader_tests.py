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


import os
import shutil
import tempfile
import unittest

import morphlib


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
build-system: dummy
'''
        morph = self.loader.parse_morphology_text(string, 'test')
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_fails_to_parse_utter_garbage(self):
        self.assertRaises(
            morphlib.morphloader.MorphologySyntaxError,
            self.loader.parse_morphology_text, ',,,', 'test')

    def test_fails_to_parse_non_dict(self):
        self.assertRaises(
            morphlib.morphloader.NotADictionaryError,
            self.loader.parse_morphology_text, '- item1\n- item2\n', 'test')

    def test_fails_to_validate_dict_without_kind(self):
        m = morphlib.morph3.Morphology({
            'invalid': 'field',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_chunk_with_no_fields(self):
        m = morphlib.morph3.Morphology({
            'kind': 'chunk',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def chunk_morph(self, name='foo', **kwargs):
        '''Create an example chunk morphology'''
        return morphlib.morph3.Morphology(
            kind='chunk', name=name, **kwargs)

    def stratum_morph(self, name='foo', **kwargs):
        '''Create an example stratum morphology'''
        return morphlib.morph3.Morphology(
            kind='stratum', name=name, **kwargs)

    def system_morph(self, name='foo', arch='testarch', strata='unset',
                     **kwargs):
        '''Create an example system morphology'''
        if strata == 'unset':
            strata = [
                {'morph': 'bar'}
            ]
        return morphlib.morph3.Morphology(
            kind='system', name=name, arch=arch, strata=strata, **kwargs)

    def cluster_morph(self, name='foo', **kwargs):
        '''Create an example cluster morphology'''
        return morphlib.morph3.Morphology(
            kind='cluster', name=name, **kwargs)

    def test_fails_to_validate_chunk_with_invalid_field(self):
        m = self.chunk_morph(invalid='field')
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_validate_requires_products_list(self):
        m = self.chunk_morph(
            products={
                'foo-runtime': ['.'],
                'foo-devel': ['.'],
            })
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        e = cm.exception
        self.assertEqual((e.field, e.expected, e.actual, e.morphology_name),
                         ('products', list, dict, 'foo'))

    def test_validate_requires_products_list_of_mappings(self):
        m = self.chunk_morph(
            products={
                'foo-runtime',
            })
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        e = cm.exception
        self.assertEqual((e.field, e.expected, e.actual, e.morphology_name),
                         ('products[0]', dict, str, 'foo'))

    def test_validate_requires_products_list_required_fields(self):
        m = self.chunk_morph(
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
        self.assertEqual(
            sorted((type(ex), ex.field) for ex in exs),
            sorted((
                (morphlib.morphloader.MissingFieldError,
                 'products[0].artifact'),
                (morphlib.morphloader.MissingFieldError,
                 'products[0].include'),
                (morphlib.morphloader.InvalidFieldError,
                 'products[0].cludein'),
                (morphlib.morphloader.InvalidFieldError,
                 'products[0].factiart'),
            ))
        )

    def test_validate_requires_products_list_include_is_list(self):
        m = self.chunk_morph(
            products=[
                {
                    'artifact': 'foo-runtime',
                    'include': '.*',
                }
            ])
        with self.assertRaises(morphlib.morphloader.InvalidTypeError) as cm:
            self.loader.validate(m)
        ex = cm.exception
        self.assertEqual(('products[0].include', list, str, 'foo'),
                         (ex.field, ex.expected, ex.actual,
                          ex.morphology_name))

    def test_validate_requires_products_list_include_is_list_of_strings(self):
        m = self.chunk_morph(
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
        self.assertEqual(('products[0].include[0]', str, int, 'foo'),
                         (ex.field, ex.expected, ex.actual,
                          ex.morphology_name))


    def test_fails_to_validate_stratum_with_no_fields(self):
        m = morphlib.morph3.Morphology({
            'kind': 'stratum',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_stratum_with_invalid_field(self):
        m = self.stratum_morph(invalid='field')
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_fails_to_validate_system_with_obsolete_system_kind_field(self):
        m = self.system_morph(**{
            'system-kind': 'foo',
        })
        self.assertRaises(
            morphlib.morphloader.ObsoleteFieldsError, self.loader.validate, m)

    def test_fails_to_validate_system_with_obsolete_disk_size_field(self):
        m = self.system_morph(**{
            'disk-size': 'over 9000',
        })
        self.assertRaises(
            morphlib.morphloader.ObsoleteFieldsError, self.loader.validate, m)

    def test_fails_to_validate_system_with_no_fields(self):
        m = morphlib.morph3.Morphology({
            'kind': 'system',
        })
        self.assertRaises(
            morphlib.morphloader.MissingFieldError, self.loader.validate, m)

    def test_fails_to_validate_system_with_invalid_field(self):
        m = self.system_morph(invalid='field')
        self.assertRaises(
            morphlib.morphloader.InvalidFieldError, self.loader.validate, m)

    def test_fails_to_validate_morphology_with_unknown_kind(self):
        m = morphlib.morph3.Morphology({
            'kind': 'invalid',
        })
        self.assertRaises(
            morphlib.morphloader.UnknownKindError, self.loader.validate, m)

    def test_validate_requires_unique_stratum_names_within_a_system(self):
        m = self.system_morph(
            strata=[
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
            ])
        self.assertRaises(morphlib.morphloader.DuplicateStratumError,
                          self.loader.validate, m)

    def test_validate_requires_unique_chunk_names_within_a_stratum(self):
        m = self.stratum_morph(
            chunks=[
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
            ])
        self.assertRaises(morphlib.morphloader.DuplicateChunkError,
                          self.loader.validate, m)

    def test_validate_requires_a_valid_architecture(self):
        m = self.system_morph(arch="blah")
        self.assertRaises(
            morphlib.morphloader.UnknownArchitectureError,
            self.loader.validate, m)

    def test_validate_normalises_architecture_armv7_to_armv7l(self):
        m = self.system_morph(arch="armv7")
        self.loader.validate(m)
        self.assertEqual(m['arch'], 'armv7l')

    def test_validate_requires_build_deps_for_chunks_in_strata(self):
        m = self.stratum_morph(
            chunks=[
                {
                    "name": "foo",
                    "repo": "foo",
                    "ref": "foo",
                    "morph": "foo",
                    "build-mode": "bootstrap",
                }
            ])
        self.assertRaises(
            morphlib.morphloader.NoBuildDependenciesError,
            self.loader.validate, m)

    def test_validate_requires_build_deps_or_bootstrap_mode_for_strata(self):
        m = self.stratum_morph(
            chunks=[
                {
                    "name": "chunk",
                    "repo": "test:repo",
                    "ref": "sha1",
                    "build-depends": []
                }
            ])
        self.assertRaises(
            morphlib.morphloader.NoStratumBuildDependenciesError,
            self.loader.validate, m)

        m['build-depends'] = [
            {
                "repo": "foo",
                "ref": "foo",
                "morph": "foo",
            },
        ]
        self.loader.validate(m)

        del m['build-depends']
        m['chunks'][0]['build-mode'] = 'bootstrap'
        self.loader.validate(m)

    def test_validate_requires_chunks_in_strata(self):
        m = self.stratum_morph(**{
            'chunks': [],
            'build-depends': [
                {
                    "repo": "foo",
                    "ref": "foo",
                    "morph": "foo",
                },
            ]})
        self.assertRaises(
            morphlib.morphloader.EmptyStratumError,
            self.loader.validate, m)

    def test_validate_requires_strata_in_system(self):
        m = morphlib.morph3.Morphology(
            name='system',
            kind='system',
            arch='testarch')
        self.assertRaises(
            morphlib.morphloader.MissingFieldError,
            self.loader.validate, m)

    def test_validate_requires_list_of_strata_in_system(self):
        for v in (None, {}):
            m = self.system_morph(strata=v)
            with self.assertRaises(
                morphlib.morphloader.SystemStrataNotListError) as cm:

                self.loader.validate(m)
            self.assertEqual(cm.exception.strata_type, type(v))

    def test_validate_requires_non_empty_strata_in_system(self):
        m = self.system_morph(strata=[])
        self.assertRaises(
            morphlib.morphloader.EmptySystemError,
            self.loader.validate, m)

    def test_validate_requires_stratum_specs_in_system(self):
        m = self.system_morph(strata=["foo"])
        with self.assertRaises(
            morphlib.morphloader.SystemStratumSpecsNotMappingError) as cm:

            self.loader.validate(m)
        self.assertEqual(cm.exception.strata, ["foo"])

    def test_loads_yaml_from_string(self):
        string = '''\
name: foo
kind: chunk
build-system: dummy
'''
        morph = self.loader.load_from_string(string)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_loads_json_from_string(self):
        string = '''\
{
    "name": "foo",
    "kind": "chunk",
    "build-system": "dummy"
}
'''
        morph = self.loader.load_from_string(string)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_loads_from_file(self):
        with open(self.filename, 'w') as f:
            f.write('''\
name: foo
kind: chunk
build-system: dummy
''')
        morph = self.loader.load_from_file(self.filename)
        self.assertEqual(morph['kind'], 'chunk')
        self.assertEqual(morph['name'], 'foo')
        self.assertEqual(morph['build-system'], 'dummy')

    def test_saves_to_string(self):
        morph = morphlib.morph3.Morphology({
            'name': 'foo',
            'kind': 'chunk',
            'build-system': 'dummy',
        })
        text = self.loader.save_to_string(morph)

        # The following verifies that the YAML is written in a normalised
        # fashion.
        self.assertEqual(text, '''\
build-system: dummy
kind: chunk
name: foo
''')

    def test_saves_to_file(self):
        morph = morphlib.morph3.Morphology({
            'name': 'foo',
            'kind': 'chunk',
            'build-system': 'dummy',
        })
        self.loader.save_to_file(self.filename, morph)

        with open(self.filename) as f:
            text = f.read()

        # The following verifies that the YAML is written in a normalised
        # fashion.
        self.assertEqual(text, '''\
build-system: dummy
kind: chunk
name: foo
''')

    def test_validate_does_not_set_defaults(self):
        m = self.chunk_morph()
        self.loader.validate(m)
        self.assertEqual(sorted(m.keys()), sorted(['kind', 'name']))

    def test_sets_defaults_for_chunks(self):
        m = self.chunk_morph()
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'chunk',
                'name': 'foo',
                'description': '',
                'build-system': 'manual',

                'configure-commands': [],
                'pre-configure-commands': [],
                'post-configure-commands': [],

                'build-commands': [],
                'pre-build-commands': [],
                'post-build-commands': [],

                'test-commands': [],
                'pre-test-commands': [],
                'post-test-commands': [],

                'install-commands': [],
                'pre-install-commands': [],
                'post-install-commands': [],

                'products': [],
                'devices': [],
                'max-jobs': None,
            })

    def test_unsets_defaults_for_chunks(self):
        m = self.chunk_morph(**{'build-system': 'manual'})
        self.loader.unset_defaults(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'chunk',
                'name': 'foo',
            })

    def test_sets_defaults_for_strata(self):
        m = self.stratum_morph(
            chunks=[
                {
                    'name': 'bar',
                    'repo': 'bar',
                    'ref': 'bar',
                    'morph': 'bar',
                    'build-mode': 'bootstrap',
                    'build-depends': [],
                }])
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
                    },
                ],
                'products': [],
            })

    def test_unsets_defaults_for_strata(self):
        test_dict = {
            'kind': 'stratum',
            'name': 'foo',
            'chunks': {
                    'name': 'bar',
                    "ref": "bar",
                    'build-mode': 'bootstrap',
                    'build-depends': [],
            }
        }
        test_dict_with_build_depends = dict(test_dict)
        test_dict_with_build_depends["build-depends"] = []
        m = morphlib.morph3.Morphology(test_dict_with_build_depends)
        self.loader.unset_defaults(m)
        self.assertEqual(
            dict(m),
            test_dict)

    def test_sets_defaults_for_system(self):
        m = self.system_morph()
        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(
            dict(m),
            {
                'kind': 'system',
                'name': 'foo',
                'description': '',
                'arch': 'testarch',
                'strata': [
                    {'morph': 'bar'},
                ],
                'configuration-extensions': [],
            })

    def test_unsets_defaults_for_system(self):
        m = self.system_morph(**{
                'description': '',
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
        m = self.cluster_morph(
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
        m = self.cluster_morph(
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

    def test_sets_stratum_chunks_repo_and_morph_from_name(self):
        m = self.stratum_morph(
            chunks=[
                {
                    "name": "le-chunk",
                    "ref": "ref",
                    "build-depends": [],
                }
            ])

        self.loader.set_defaults(m)
        self.loader.validate(m)
        self.assertEqual(m['chunks'][0]['repo'], 'le-chunk')
        self.assertEqual(m['chunks'][0]['morph'], 'le-chunk')

    def test_collapses_stratum_chunks_repo_and_morph_from_name(self):
        m = self.stratum_morph(
            chunks=[
                {
                    "name": "le-chunk",
                    "repo": "le-chunk",
                    "morph": "le-chunk",
                    "ref": "ref",
                    "build-depends": [],
                }
            ])

        self.loader.unset_defaults(m)
        self.assertTrue('repo' not in m['chunks'][0])
        self.assertTrue('morph' not in m['chunks'][0])

    def test_convertes_max_jobs_to_an_integer(self):
        m = self.chunk_morph(**{
            'max-jobs': '42'
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
