# Copyright (C) 2011 - 2014  Codethink Limited
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


'''Setup.py for morph.'''


from distutils.core import setup
from distutils.cmd import Command
from distutils.command.build import build
from distutils.command.clean import clean
import glob
import os
import os.path
import shutil
import stat
import subprocess

import cliapp

import morphlib


class GenerateResources(build):

    def run(self):
        if not self.dry_run:
            self.generate_manpages()
            self.generate_version()
        build.run(self)

        # Set exec permissions on deployment extensions.
        for dirname, subdirs, basenames in os.walk('morphlib/exts'):
            for basename in basenames:
                orig = os.path.join(dirname, basename)
                built = os.path.join('build/lib', dirname, basename)
                st = os.lstat(orig)
                bits = (st.st_mode &
                        (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                if bits != 0:
                    st2 = os.lstat(built)
                    os.chmod(built, st2.st_mode | bits)

    def generate_manpages(self):
        self.announce('building manpages')
        for x in ['morph']:
            with open('%s.1' % x, 'w') as f:
                subprocess.check_call(['python', x,
                                       '--generate-manpage=%s.1.in' % x,
                                       '--output=%s.1' % x], stdout=f)

    def generate_version(self):
        target_dir = os.path.join(self.build_lib, 'morphlib')

        self.mkpath(target_dir)

        def save_git_info(filename, *args):
            path = os.path.join(target_dir, filename)
            command = ['git'] + list(args)

            self.announce('generating %s with %s' %
                          (path, ' '.join(command)))

            with open(os.path.join(target_dir, filename), 'w') as f:
                cwd = os.path.dirname(__file__) or '.'
                p = subprocess.Popen(command,
                                     cwd=cwd,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
                o = p.communicate()
                if p.returncode:
                    raise subprocess.CalledProcessError(p.returncode, command)
                f.write(o[0].strip())

        save_git_info('version', 'describe', '--always',
                      '--dirty=-unreproducible')
        save_git_info('commit', 'rev-parse', 'HEAD^{commit}')
        save_git_info('tree', 'rev-parse', 'HEAD^{tree}')
        save_git_info('ref', 'rev-parse', '--symbolic-full-name', 'HEAD')

class Clean(clean):

    clean_files = [
        '.coverage',
        'build',
        'unittest-tempdir',
    ]
    clean_globs = [
        '*/*.py[co]',
    ]

    def run(self):
        clean.run(self)
        itemses = ([self.clean_files] +
                   [glob.glob(x) for x in self.clean_globs])
        for items in itemses:
            for filename in items:
                if os.path.isdir(filename):
                    shutil.rmtree(filename)
                elif os.path.exists(filename):
                    os.remove(filename)


class Check(Command):

    user_options = [
    ]

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        subprocess.check_call(['python', '-m', 'CoverageTestRunner',
                               '--ignore-missing-from=without-test-modules',
                               'morphlib'])
        os.remove('.coverage')


setup(name='morph',
      description='FIXME',
      long_description='''\
FIXME
''',
      classifiers=[
          'Development Status :: 2 - Pre-Alpha',
          'Environment :: Console',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: GNU General Public License (GPL)',
          'Operating System :: POSIX :: Linux',
          'Programming Language :: Python',
          'Topic :: Software Development :: Build Tools',
          'Topic :: Software Development :: Embedded Systems',
          'Topic :: System :: Archiving :: Packaging',
          'Topic :: System :: Software Distribution',
      ],
      author='Codethink Limited',
      author_email='baserock-dev@baserock.org',
      url='http://www.baserock.org/',
      scripts=['morph', 'distbuild-helper'],
      packages=['morphlib', 'morphlib.plugins', 'distbuild'],
      package_data={
          'morphlib': [
              'exts/*',
              'version',
              'commit',
              'tree',
              'ref',
          ]
      },
      data_files=[('share/man/man1', glob.glob('*.[1-8]'))],
      cmdclass={
          'build': GenerateResources,
          'check': Check,
          'clean': Clean,
      })
