# Copyright (C) 2011-2014  Codethink Limited
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


import gzip
import os
import shutil
import stat
import tempfile
import tarfile
import unittest
import StringIO

import morphlib


class BinsTest(unittest.TestCase):

    def recursive_lstat(self, root):
        '''Return a list of (pathname, stat) pairs for everything in root.

        Pathnames are relative to root. Directories are recursed into.
        The stat result is selective, not all fields are used.

        '''

        def remove_root(pathname):
            self.assertTrue(pathname.startswith(root))
            if pathname == root:
                return '.'
            else:
                return pathname[(len(root) + 1):]

        def lstat(filename):
            st = os.lstat(filename)

            # For directories, the size is dependent on the contents, and
            # possibly on things that have been deleted already. An unpacked
            # directory can be identical even if the size field is different.
            # So we ignore it for directories.
            #
            # Similarly, the mtime for a directory will change when we remove
            # files in the directory, and a different mtime is not necessarily
            # a sign of a bad unpack. It's possible for the tests to arrange
            # for everything to be correct as far as directory mtimes are
            # concerned, but it's not worth it, so we fudge the mtime too.
            if stat.S_ISDIR(st.st_mode):
                return (st.st_mode, 0, 0)
            else:
                return (st.st_mode, st.st_size, 0)

        result = []

        for dirname, subdirs, basenames in os.walk(root):
            result.append((remove_root(dirname), lstat(dirname)))
            for basename in sorted(basenames):
                filename = os.path.join(dirname, basename)
                result.append((remove_root(filename), lstat(filename)))
            subdirs.sort()

        return result


class ChunkTests(BinsTest):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.instdir = os.path.join(self.tempdir, 'inst')
        self.chunk_file = os.path.join(self.tempdir, 'chunk')
        self.chunk_f = open(self.chunk_file, 'wb')
        self.unpacked = os.path.join(self.tempdir, 'unpacked')

    def tearDown(self):
        self.chunk_f.close()
        shutil.rmtree(self.tempdir)

    def populate_instdir(self):
        timestamp = 12765

        os.mkdir(self.instdir)

        bindir = os.path.join(self.instdir, 'bin')
        os.mkdir(bindir)
        filename = os.path.join(bindir, 'foo')
        with open(filename, 'w'):
            pass
        os.utime(filename, (timestamp, timestamp))

        libdir = os.path.join(self.instdir, 'lib')
        os.mkdir(libdir)
        filename = os.path.join(libdir, 'libfoo.so')
        with open(filename, 'w'):
            pass
        os.utime(filename, (timestamp, timestamp))

        self.instdir_orig_files = self.recursive_lstat(self.instdir)

    def create_chunk(self, includes):
        self.populate_instdir()
        morphlib.bins.create_chunk(self.instdir, self.chunk_f, includes)
        self.chunk_f.flush()

    def unpack_chunk(self):
        os.mkdir(self.unpacked)
        morphlib.bins.unpack_binary(self.chunk_file, self.unpacked)

    def test_empties_files(self):
        self.create_chunk(['bin/foo', 'lib/libfoo.so'])
        self.assertEqual([x for x, y in self.recursive_lstat(self.instdir)],
                         ['.', 'bin', 'lib'])

    def test_creates_and_unpacks_chunk_exactly(self):
        self.create_chunk(['bin', 'bin/foo', 'lib', 'lib/libfoo.so'])
        self.unpack_chunk()
        self.assertEqual(self.instdir_orig_files,
                         self.recursive_lstat(self.unpacked))

    def test_uses_only_matching_names(self):
        self.create_chunk(['bin/foo'])
        self.unpack_chunk()
        self.assertEqual([x for x, y in self.recursive_lstat(self.unpacked)],
                         ['.', 'bin', 'bin/foo'])
        self.assertEqual([x for x, y in self.recursive_lstat(self.instdir)],
                         ['.', 'bin', 'lib', 'lib/libfoo.so'])

    def test_does_not_compress_artifact(self):
        self.create_chunk(['bin'])
        f = gzip.open(self.chunk_file)
        self.assertRaises(IOError, f.read)
        f.close()


class ExtractTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.instdir = os.path.join(self.tempdir, 'inst')
        self.unpacked = os.path.join(self.tempdir, 'unpacked')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def create_chunk(self, callback):
        fh = StringIO.StringIO()
        os.mkdir(self.instdir)
        patterns = callback(self.instdir)
        morphlib.bins.create_chunk(self.instdir, fh, patterns)
        shutil.rmtree(self.instdir)
        fh.flush()
        fh.seek(0)
        return fh

    def test_extracted_files_replace_links(self):
        def make_linkfile(basedir):
            with open(os.path.join(basedir, 'babar'), 'w') as f:
                pass
            os.symlink('babar', os.path.join(basedir, 'bar'))
            return ['babar']
        linktar = self.create_chunk(make_linkfile)

        def make_file(basedir):
            with open(os.path.join(basedir, 'bar'), 'w') as f:
                pass
            return ['bar']
        filetar = self.create_chunk(make_file)

        os.mkdir(self.unpacked)
        morphlib.bins.unpack_binary_from_file(linktar, self.unpacked)
        morphlib.bins.unpack_binary_from_file(filetar, self.unpacked)
        mode = os.lstat(os.path.join(self.unpacked, 'bar')).st_mode
        self.assertTrue(stat.S_ISREG(mode))

    def test_extracted_dirs_keep_links(self):
        def make_usrlink(basedir):
            os.symlink('.', os.path.join(basedir, 'usr'))
            return ['usr']
        linktar = self.create_chunk(make_usrlink)

        def make_usrdir(basedir):
            os.mkdir(os.path.join(basedir, 'usr'))
            return ['usr']
        dirtar = self.create_chunk(make_usrdir)

        morphlib.bins.unpack_binary_from_file(linktar, self.unpacked)
        morphlib.bins.unpack_binary_from_file(dirtar, self.unpacked)
        mode = os.lstat(os.path.join(self.unpacked, 'usr')).st_mode
        self.assertTrue(stat.S_ISLNK(mode))

    def test_extracted_files_follow_links(self):
        def make_usrlink(basedir):
            os.symlink('.', os.path.join(basedir, 'usr'))
            return ['usr']
        linktar = self.create_chunk(make_usrlink)

        def make_usrdir(basedir):
            os.mkdir(os.path.join(basedir, 'usr'))
            with open(os.path.join(basedir, 'usr', 'foo'), 'w') as f:
                pass
            return ['usr', 'usr/foo']
        dirtar = self.create_chunk(make_usrdir)

        morphlib.bins.unpack_binary_from_file(linktar, self.unpacked)
        morphlib.bins.unpack_binary_from_file(dirtar, self.unpacked)
        mode = os.lstat(os.path.join(self.unpacked, 'foo')).st_mode
        self.assertTrue(stat.S_ISREG(mode))
