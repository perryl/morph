# Copyright (C) 2013, 2014  Codethink Limited
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


import unittest

import morphlib


class MorphologySetTests(unittest.TestCase):

    def setUp(self):
        self.morphs = morphlib.morphset.MorphologySet()

        self.system = morphlib.morphology.Morphology({
            'kind': 'system',
            'name': 'foo-system',
            'strata': [
                {
                    'repo': 'test:morphs',
                    'ref': 'master',
                    'morph': 'foo-stratum',
                },
            ],
        })
        self.system.repo_url = 'test:morphs'
        self.system.ref = 'master'
        self.system.filename = 'foo-system.morph'

        self.stratum = morphlib.morphology.Morphology({
            'kind': 'stratum',
            'name': 'foo-stratum',
            'chunks': [
                {
                    'repo': 'test:foo-chunk',
                    'ref': 'master',
                    'morph': 'foo-chunk',
                },
            ],
            'build-depends': [],
        })
        self.stratum.repo_url = 'test:morphs'
        self.stratum.ref = 'master'
        self.stratum.filename = 'foo-stratum.morph'

    def test_is_empty_initially(self):
        self.assertEqual(self.morphs.morphologies, [])
        self.assertFalse(
            self.morphs.has(
                self.system.repo_url, self.system.ref, self.system.filename))

    def test_adds_morphology(self):
        self.morphs.add_morphology(self.system)
        self.assertEqual(self.morphs.morphologies, [self.system])
        self.assertTrue(
            self.morphs.has(
                self.system.repo_url, self.system.ref, self.system.filename))

        self.morphs.add_morphology(self.stratum)
        self.assertEqual(
            self.morphs.morphologies,
            [self.system, self.stratum])

    def test_does_not_add_morphology_twice(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.system)
        self.assertEqual(self.morphs.morphologies, [self.system])

    def test_get_chunk_triplet(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.assertEqual(
            self.morphs.get_chunk_triplet(self.stratum, 'foo-chunk'),
            ('test:foo-chunk', 'master', 'foo-chunk'))

    def test_raises_chunk_not_in_stratum_error(self):
        self.assertRaises(
            morphlib.morphset.ChunkNotInStratumError,
            self.morphs.get_chunk_triplet, self.stratum, 'wrong')

    def test_changes_stratum_ref(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.morphs.change_ref(
            self.stratum.repo_url,
            self.stratum.ref,
            self.stratum['name'],
            'new-ref')
        self.assertEqual(self.stratum.ref, 'new-ref')
        self.assertEqual(
            self.system['strata'][0],
            {
                'repo': 'test:morphs',
                'ref': 'new-ref',
                'morph': 'foo-stratum',
                'unpetrify-ref': 'master',
            })

    def test_changes_stratum_ref_in_build_depends(self):
        other_stratum = morphlib.morphology.Morphology({
            'name': 'other-stratum',
            'kind': 'stratum',
            'chunks': [],
            'build-depends': [
                {
                    'repo': self.stratum.repo_url,
                    'ref': self.stratum.ref,
                    'morph': self.stratum['name'],
                    'unpetrify-ref': 'master',
                },
            ]
        })
        other_stratum.repo_url = 'test:morphs'
        other_stratum.ref = 'master'
        other_stratum.filename = 'other-stratum.morph'

        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.morphs.add_morphology(other_stratum)
        self.morphs.change_ref(
            self.stratum.repo_url,
            self.stratum.ref,
            self.stratum['name'],
            'new-ref')
        self.assertEqual(
            other_stratum['build-depends'][0],
            {
                'repo': 'test:morphs',
                'ref': 'new-ref',
                'morph': 'foo-stratum',
                'unpetrify-ref': 'master',
            })

    def test_changes_chunk_ref(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.morphs.change_ref(
            'test:foo-chunk',
            'master',
            'foo-chunk',
            'new-ref')
        self.assertEqual(
            self.stratum['chunks'],
            [
                {
                    'repo': 'test:foo-chunk',
                    'ref': 'new-ref',
                    'morph': 'foo-chunk',
                    'unpetrify-ref': 'master',
                }
            ])

    def test_list_refs(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.assertEqual(sorted(self.morphs.list_refs()),
                         [('test:foo-chunk', 'master'),
                          ('test:morphs', 'master')])

    def test_repoint_refs(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.morphs.repoint_refs('test:morphs', 'test')
        self.assertEqual(self.system['strata'],
                         [
                             {
                                 'morph': 'foo-stratum',
                                 'ref': 'test',
                                 'repo': 'test:morphs',
                                 'unpetrify-ref': 'master',
                             }
                         ])

    def test_petrify_chunks(self):
        # TODO: test petrifying a larger morphset
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.morphs.petrify_chunks({('test:foo-chunk', 'master'): '0'*40})
        self.assertEqual(
            self.stratum['chunks'],
            [
                {
                    'repo': 'test:foo-chunk',
                    'ref': '0'*40,
                    'morph': 'foo-chunk',
                    'unpetrify-ref': 'master',
                }
            ])

    def test_unpetrify_all(self):
        self.morphs.add_morphology(self.system)
        self.morphs.add_morphology(self.stratum)
        self.morphs.petrify_chunks({('test:foo-chunk', 'master'): '0'*40})
        self.morphs.unpetrify_all()
        self.assertEqual(
            self.stratum['chunks'],
            [
                {
                    'repo': 'test:foo-chunk',
                    'ref': 'master',
                    'morph': 'foo-chunk',
                }
            ])
