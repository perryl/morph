#!/usr/bin/env python
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

import pip_lorry
import json

import unittest

class Tests(unittest.TestCase):

    def test_make_tarball_lorry(self):
        gzip, bzip, lzma = 'gzip', 'bzip2', 'lzma'

        valid_extensions = {'tar.gz': gzip, 'tgz': gzip, 'tar.Z': gzip,
                            'tar.bz2': bzip, 'tbz2': bzip,
                            'tar.lzma': lzma, 'tar.xz': lzma,
                            'tlz': lzma, 'txz': lzma}

        def make_url(extension):
            return 'http://foobar.baz/%s' % extension

        fake_package_name = 'name'
        urls = [make_url(extension) for extension in valid_extensions]

        for url in urls:
            lorry = pip_lorry.make_tarball_lorry('name', url)
            self.assertEqual(
                json.loads(lorry)[fake_package_name + '-tarball']['url'], url)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(Tests)
    unittest.TextTestRunner(verbosity=2).run(suite)
