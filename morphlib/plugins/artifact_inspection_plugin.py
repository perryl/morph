# Copyright (C) 2012-2016 Codethink Limited
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


import cliapp
import glob
import json
import os
import re
import contextlib

import morphlib

from morphlib.bins import call_in_artifact_directory
from morphlib.extractedtarball import ExtractedTarball
from morphlib.mountableimage import MountableImage


class NotASystemArtifactError(cliapp.AppException):

    def __init__(self, artifact):
        cliapp.AppException.__init__(
                self, '%s is not a system artifact' % artifact)


class ProjectVersionGuesser(object):

    def __init__(self, app, repo_cache, interesting_files):
        self.app = app
        self.repo_cache = repo_cache
        self.interesting_files = interesting_files

    def file_contents(self, repo, ref, tree):
        filenames = [x for x in self.interesting_files if x in tree]
        for filename in filenames:
            # This can use a remote repo cache if available, to avoid having
            # to clone every repo locally.
            yield filename, self.repo_cache.cat_file(repo, ref, filename)


class AutotoolsVersionGuesser(ProjectVersionGuesser):

    def __init__(self, app, repo_cache):
        ProjectVersionGuesser.__init__(self, app, repo_cache, [
            'configure.ac',
            'configure.in',
            'configure.ac.in',
            'configure.in.in',
        ])

    def guess_version(self, repo, ref, tree):
        version = None
        for filename, data in self.file_contents(repo, ref, tree):
            # First, try to grep for AC_INIT()
            version = self._check_ac_init(data)
            if version:
                self.app.status(
                        msg='%(repo)s: Version of %(ref)s detected '
                            'via %(filename)s:AC_INIT: %(version)s',
                        repo=repo, ref=ref, filename=filename,
                        version=version, chatty=True)
                break

            # Then, try running autoconf against the configure script
            version = self._check_autoconf_package_version(
                repo, ref, filename, data)
            if version:
                self.app.status(
                        msg='%(repo)s: Version of %(ref)s detected '
                            'by processing %(filename)s: %(version)s',
                        repo=repo, ref=ref, filename=filename,
                        version=version, chatty=True)
                break
        return version

    def _check_ac_init(self, data):
        data = data.replace('\n', ' ')
        for macro in ['AC_INIT', 'AM_INIT_AUTOMAKE']:
            pattern = r'.*%s\((.*?)\).*' % macro
            if not re.match(pattern, data):
                continue
            acinit = re.sub(pattern, r'\1', data)
            if acinit:
                version = acinit.split(',')
                if macro == 'AM_INIT_AUTOMAKE' and len(version) == 1:
                    continue
                version = version[0] if len(version) == 1 else version[1]
                version = re.sub('[\[\]]', '', version).strip()
                version = version.split()[0]
                if version:
                    if version and version[0].isdigit():
                        return version
        return None

    def _check_autoconf_package_version(self, repo, ref, filename, data):
        with morphlib.util.temp_dir(
                dir=self.app.settings['tempdir']) as tempdir:
            with open(os.path.join(tempdir, filename), 'w') as f:
                f.write(data)
            exit_code, output, errors = self.app.runcmd_unchecked(
                ['autoconf', filename],
                ['grep', '^PACKAGE_VERSION='],
                ['cut', '-d=', '-f2'],
                ['sed', "s/'//g"],
                cwd=tempdir)
            version = None
            if output:
                output = output.strip()
                if output and output[0].isdigit():
                    version = output
            if exit_code != 0:
                self.app.status(
                    msg='%(repo)s: Failed to detect version from '
                    '%(ref)s:%(filename)s',
                    repo=repo, ref=ref, filename=filename, chatty=True)
        return version


class VersionGuesser(object):

    def __init__(self, app):
        self.app = app
        self.repo_cache = morphlib.util.new_repo_cache(app)
        self.guessers = [
            AutotoolsVersionGuesser(app, self.repo_cache)
        ]

    def guess_version(self, repo, ref):
        self.app.status(msg='%(repo)s: Guessing version of %(ref)s',
                        repo=repo, ref=ref, chatty=True)
        version = None
        try:
            # This can use a remote repo cache if available, to avoid having
            # to clone every repo locally.
            tree = self.repo_cache.ls_tree(repo, ref)

            for guesser in self.guessers:
                version = guesser.guess_version(repo, ref, tree)
                if version:
                    break
        except cliapp.AppException as err:
            self.app.status(msg='%(repo)s: Failed to list files in %(ref)s',
                            repo=repo, ref=ref, chatty=True)
        return version


class ManifestGenerator(object):

    def __init__(self, app):
        self.app = app
        self.version_guesser = VersionGuesser(app)

    def generate(self, artifact, dirname):
        # Try to find a directory with baserock metadata files.
        metadirs = [
            os.path.join(dirname, 'factory', 'baserock'),
            os.path.join(dirname, 'baserock')
        ]
        existing_metadirs = [x for x in metadirs if os.path.isdir(x)]
        if not existing_metadirs:
            raise NotASystemArtifactError(artifact)
        metadir = existing_metadirs[0]

        # Collect all meta information about the system, its strata
        # and its chunks that we are interested in.
        artifacts = []
        for basename in glob.glob(os.path.join(metadir, '*.meta')):
            metafile = os.path.join(metadir, basename)
            metadata = json.load(open(metafile))

            # Try to guess the version of this artifact
            version = self.version_guesser.guess_version(
                    metadata['repo'], metadata['sha1'])
            if version is None:
                version = ''
            else:
                version = '-%s' % version

            fst_col = '%s.%s.%s%s' % (metadata['cache-key'][:7],
                                      metadata['kind'],
                                      metadata['artifact-name'],
                                      version)

            original_ref = metadata['original_ref']
            if (metadata['kind'] in ('system', 'stratum') and
                'baserock/builds/' in original_ref):
                original_ref = original_ref[: len('baserock/builds/') + 7]

            artifacts.append({
                'kind': metadata['kind'],
                'name': metadata['artifact-name'],
                'fst_col': fst_col,
                'repo': metadata['repo'],
                'original_ref': original_ref,
                'sha1': metadata['sha1'][:7]
            })
        
        # Generate a format string for dumping the information.
        fmt = self._generate_output_format(artifacts)
        self.app.output.write(fmt % ('ARTIFACT', 'REPOSITORY',
                                     'REF', 'COMMIT'))

        # Print information about system, strata and chunks.
        self._print_artifacts(fmt, artifacts, 'system')
        self._print_artifacts(fmt, artifacts, 'stratum')
        self._print_artifacts(fmt, artifacts, 'chunk')

    def _generate_output_format(self, artifacts):
        colwidths = {}
        for artifact in artifacts:
            for key, value in artifact.iteritems():
                colwidths[key] = max(colwidths.get(key, 0), len(value))

        return '%%-%is\t' \
               '%%-%is\t' \
               '%%-%is\t' \
               '%%-%is\n' % (
                colwidths['fst_col'],
                colwidths['repo'],
                colwidths['original_ref'],
                colwidths['sha1'])

    def _print_artifacts(self, fmt, artifacts, kind):
        for artifact in sorted(artifacts, key=lambda x: x['name']):
            if artifact['kind'] == kind:
                self.app.output.write(fmt % (artifact['fst_col'],
                                             artifact['repo'],
                                             artifact['original_ref'],
                                             artifact['sha1']))


class ArtifactInspectionPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand('generate-manifest-genivi',
                                self.generate_manifest,
                                arg_synopsis='SYSTEM-ARTIFACT')

    def disable(self):
        pass

    def generate_manifest(self, args):
        '''Generate a content manifest for a system image.

        Command line arguments:

        * `SYSTEM-ARTIFACT` is a filename to the system artifact
          (root filesystem) for the built system.

        This command generates a manifest for a built system image.
        The manifest includes the constituent artifacts,
        a guess at the component version, the exact commit for
        the component (commit SHA1, repository URL, git symbolic
        ref), and the morphology filename.


        The manifest includes each constituent artifact, with several
        columns of data:
        
        * 7-char cache key with the artifact kind (system, stratum, chunk),
        artifact name, and version (if guessable) added
        * the git repository
        * the symbolic reference
        * a 7-char commit id

        Example:

            morph generate-manifest-genivi /src/cache/artifacts/foo-rootfs

        '''

        if len(args) != 1:
            raise cliapp.AppException('morph generate-manifest expects '
                                      'a system image as its input')

        artifact = args[0]

        def generate_manifest(dirname):
            generator = ManifestGenerator(self.app)
            generator.generate(artifact, dirname)

        call_in_artifact_directory(self.app, artifact, generate_manifest)
