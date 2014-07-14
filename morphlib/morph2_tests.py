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


import copy
import json
import StringIO
import unittest

import yaml

import morphlib
from morphlib.morph2 import Morphology


class MorphologyTests(unittest.TestCase):

    def test_parses_simple_json_chunk(self):
        m = Morphology('''
            {
                "name": "foo",
                "kind": "chunk",
                "build-system": "manual"
            }
        ''')

        self.assertEqual(m['name'], 'foo')
        self.assertEqual(m['kind'], 'chunk')
        self.assertEqual(m['build-system'], 'manual')
        self.assertEqual(m['pre-configure-commands'], None)
        self.assertEqual(m['configure-commands'], None)
        self.assertEqual(m['post-configure-commands'], None)
        self.assertEqual(m['pre-build-commands'], None)
        self.assertEqual(m['build-commands'], None)
        self.assertEqual(m['post-build-commands'], None)
        self.assertEqual(m['pre-test-commands'], None)
        self.assertEqual(m['test-commands'], None)
        self.assertEqual(m['post-test-commands'], None)
        self.assertEqual(m['pre-install-commands'], None)
        self.assertEqual(m['install-commands'], None)
        self.assertEqual(m['post-install-commands'], None)
        self.assertEqual(m['max-jobs'], None)
        self.assertEqual(m['products'], [])

    if morphlib.got_yaml:
        def test_parses_simple_yaml_chunk(self):
            m = Morphology('''
                name: foo
                kind: chunk
                build-system: manual
            ''')

            self.assertEqual(m['name'], 'foo')
            self.assertEqual(m['kind'], 'chunk')
            self.assertEqual(m['build-system'], 'manual')
            self.assertEqual(m['pre-configure-commands'], None)
            self.assertEqual(m['configure-commands'], None)
            self.assertEqual(m['post-configure-commands'], None)
            self.assertEqual(m['pre-build-commands'], None)
            self.assertEqual(m['build-commands'], None)
            self.assertEqual(m['post-build-commands'], None)
            self.assertEqual(m['pre-test-commands'], None)
            self.assertEqual(m['test-commands'], None)
            self.assertEqual(m['post-test-commands'], None)
            self.assertEqual(m['pre-install-commands'], None)
            self.assertEqual(m['install-commands'], None)
            self.assertEqual(m['post-install-commands'], None)
            self.assertEqual(m['max-jobs'], None)
            self.assertEqual(m['products'], [])

    def test_sets_stratum_chunks_repo_and_morph_from_name(self):
        m = Morphology('''
            {
                "name": "foo",
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "le-chunk",
                        "ref": "ref"
                    }
                ]
            }
        ''')

        self.assertEqual(m['chunks'][0]['repo'], 'le-chunk')
        self.assertEqual(m['chunks'][0]['build-depends'], None)

    def test_returns_dict_keys(self):
        m = Morphology('''
            {
                "name": "foo",
                "kind": "system",
            }
        ''')

        self.assertTrue('name' in m.keys())
        self.assertTrue('kind' in m.keys())

    def test_system_indexes_strata(self):
        m = Morphology('''
            {
                "kind": "system",
                "strata": [
                    {
                        "morph": "stratum1",
                        "repo": "repo",
                        "ref": "ref"
                    },
                    {
                        "alias": "aliased-stratum",
                        "morph": "stratum2",
                        "repo": "repo",
                        "ref": "ref"
                    }
                ]
            }
        ''')
        self.assertEqual(m.lookup_child_by_name('stratum1'),
                         {'morph': 'stratum1', 'repo': 'repo', 'ref': 'ref' })
        self.assertEqual(m.lookup_child_by_name('aliased-stratum'),
                         {'alias': 'aliased-stratum', 'morph': 'stratum2',
                          'repo': 'repo', 'ref': 'ref'})

    def test_stratum_indexes_chunks(self):
        m = Morphology('''
            {
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "chunk",
                        "repo": "repo",
                        "ref": "ref"
                    }
                ]
            }
        ''')

        child = m.lookup_child_by_name('chunk')
        self.assertEqual(child['name'], 'chunk')
        self.assertEqual(child['repo'], 'repo')
        self.assertEqual(child['ref'], 'ref')

    def test_raises_error_when_child_lookup_fails(self):
        m = Morphology('''
            {
                "kind": "stratum",
                "chunks": [
                    {
                        "name": "chunk",
                        "repo": "repo",
                        "ref": "ref"
                    }
                ]
            }
        ''')

        self.assertRaises(KeyError, m.lookup_child_by_name, 'foo')

    ## Validation tests

    def test_not_empty(self):
        self.assertRaises(morphlib.YAMLError, Morphology, '')

    def test_is_dict(self):
        self.assertRaises(morphlib.YAMLError, Morphology, 'foo')

    def test_makes_max_jobs_be_an_integer(self):
        m = Morphology('''
            {
                "name": "foo",
                "kind": "chunk",
                "max-jobs": "42"
            }
        ''')
        self.assertEqual(m['max-jobs'], 42)

    def test_stratum_names_must_be_unique_within_a_system(self):
        text = '''
            {
                "kind": "system",
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
            }
        '''
        self.assertRaises(ValueError,
                          Morphology,
                          text)

    def test_chunk_names_must_be_unique_within_a_stratum(self):
        text = '''
            {
                "kind": "stratum",
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
            }
        '''
        self.assertRaises(ValueError,
                          Morphology,
                          text)

    ## Writing tests

    stratum_text = '''{
    "kind": "stratum",
    "chunks": [
        {
            "name": "foo",
            "repo": "morphs",
            "ref": "ref",
            "build-depends": []
        },
        {
            "name": "bar",
            "repo": "morphs",
            "ref": "ref",
            "build-depends": [
                "foo"
            ]
        }
    ]
}'''

    def test_writing_handles_added_chunks(self):
        text_lines = self.stratum_text.splitlines()
        text_lines = text_lines[0:16] + text_lines[8:17] + text_lines[17:]
        text_lines[18] = '            "name": "baz",'

        # Add a new chunk to the list
        morphology = Morphology(self.stratum_text)
        morphology['chunks'].append(copy.copy(morphology['chunks'][1]))
        morphology['chunks'][2]['name'] = 'baz'

        output = StringIO.StringIO()
        morphology.update_text(self.stratum_text, output)
        d = yaml.load(output.getvalue())
        self.assertEqual(d['chunks'][2]['name'], 'baz')

    def test_writing_handles_deleted_chunks(self):
        text_lines = self.stratum_text.splitlines()
        text_lines = text_lines[0:3] + text_lines[9:]

        # Delete a chunk
        morphology = Morphology(self.stratum_text)
        del morphology['chunks'][0]

        output = StringIO.StringIO()
        morphology.update_text(self.stratum_text, output)
        d = yaml.load(output.getvalue())
        self.assertEqual(len(d['chunks']), 1)

    system_text = '''{
    "kind": "system",
    "arch": "x86_64",
}'''

    def test_nested_dict(self):
        # Real morphologies don't trigger this code path, so we test manually
        original_dict = {
            'dict': { '1': 'fee', '2': 'fie', '3': 'foe', '4': 'foo' }
        }
        live_dict = copy.deepcopy(original_dict)
        live_dict['_orig_dict'] = live_dict['dict']

        dummy = Morphology(self.stratum_text)
        output_dict = dummy._apply_changes(live_dict, original_dict)
        self.assertEqual(original_dict, output_dict)

    def test_uses_morphology_commands_when_given(self):
        m = Morphology('''
            {
                'name': 'foo',
                'kind': 'chunk',
                'build-system': 'dummy',
                'build-commands': ['build-it']
            }
        ''')
        cmds = m.get_commands('build-commands')
        self.assertEqual(cmds, ['build-it'])

    def test_uses_build_system_commands_when_morphology_doesnt(self):
        m = Morphology('''
            {
                'name': 'foo',
                'kind': 'chunk',
                'build-system': 'dummy',
            }
        ''')
        cmds = m.get_commands('build-commands')
        self.assertEqual(cmds, ['echo dummy build'])

    def test_uses_morphology_commands_when_morphology_has_empty_list(self):
        m = Morphology('''
            {
                'name': 'foo',
                'kind': 'chunk',
                'build-system': 'dummy',
                'build-commands': []
            }
        ''')
        cmds = m.get_commands('build-commands')
        self.assertEqual(cmds, [])

    ## Cluster morphologies tests

    def test_parses_simple_cluster_morph(self):
        m = Morphology('''
            name: foo
            kind: cluster
            systems:
                - morph: bar
        ''')
        self.assertEqual(m['name'], 'foo')
        self.assertEqual(m['kind'], 'cluster')
        self.assertEqual(m['systems'][0]['morph'], 'bar')

    def test_fails_without_systems(self):
        text = '''
            name: foo
            kind: cluster
            '''
        self.assertRaises(KeyError, Morphology, text)

    def test_fails_with_empty_systems(self):
        text = '''
            name: foo
            kind: cluster
            systems:
            '''
        self.assertRaises(ValueError, Morphology, text)

    def test_fails_without_morph(self):
        text = '''
            name: foo
            kind: cluster
            systems:
                 - deploy:
            '''
        self.assertRaises(KeyError, Morphology, text)

    def test_fails_with_invalid_deploy_defaults(self):
        text = '''
            name: foo
            kind: cluster
            systems:
                - morph: bar
                  deploy-defaults: ooops_i_am_not_a_mapping
            '''
        self.assertRaises(ValueError, Morphology, text)

    def test_fails_with_invalid_deployment_params(self):
        text = '''
            name: foo
            kind: cluster
            systems:
                - morph: bar
                  deploy:
                      qux: ooops_i_am_not_a_mapping
            '''
        self.assertRaises(ValueError, Morphology, text)
