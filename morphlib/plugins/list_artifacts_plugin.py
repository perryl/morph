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

# This plugin is used as part of the Baserock automated release process.
#
# See: <http://wiki.baserock.org/guides/release-process> for more information.


import cliapp
import morphlib


class ListArtifactsPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'list-artifacts', self.list_artifacts,
            arg_synopsis='REPO REF MORPH [MORPH]...')

    def disable(self):
        pass

    def list_artifacts(self, args):
        '''List every artifact in the build graph of a system.

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a branch or other commit reference in that repository.
        * `MORPH` is a system morphology name at that ref.

        You can pass multiple values for `MORPH`, in which case the command
        outputs the union of the build graphs of all the systems passed in.

        The output includes any meta-artifacts such as .meta and .build-log
        files.

        '''

        if len(args) < 3:
            raise cliapp.AppException(
                'Wrong number of arguments to list-artifacts command '
                '(see help)')

        repo, ref = args[0], args[1]
        system_filenames = map(morphlib.util.sanitise_morphology_path,
                               args[2:])

        self.lrc, self.rrc = morphlib.util.new_repo_caches(self.app)
        self.resolver = morphlib.artifactresolver.ArtifactResolver()

        artifact_files = set()
        for system_filename in system_filenames:
            system_artifact_files = self.list_artifacts_for_system(
                repo, ref, system_filename)
            artifact_files.update(system_artifact_files)

        for artifact_file in sorted(artifact_files):
            print artifact_file

    def list_artifacts_for_system(self, repo, ref, system_filename):
        '''List all artifact files in the build graph of a single system.'''

        # Sadly, we must use a fresh source pool and a fresh list of artifacts
        # for each system. Creating a source pool is slow (queries every Git
        # repo involved in the build) and resolving artifacts isn't so quick
        # either. Unfortunately, each Source object can only have one set of
        # Artifact objects associated, which means the source pool cannot mix
        # sources that are being built for multiple architectures: the build
        # graph representation does not distinguish chunks or strata of
        # different architectures right now.

        self.app.status(
            msg='Creating source pool for %s' % system_filename, chatty=True)
        source_pool = self.app.create_source_pool(
            self.lrc, self.rrc, (repo, ref, system_filename))

        self.app.status(
            msg='Resolving artifacts for %s' % system_filename, chatty=True)
        artifacts = self.resolver.resolve_artifacts(source_pool)

        def find_artifact_by_name(artifacts_list, filename):
            for a in artifacts_list:
                if a.source.filename == name:
                    return a
            raise ValueError

        system_artifact = find_artifact_by_name(artifacts, system_filename)

        self.app.status(
            msg='Computing cache keys for %s' % system_filename, chatty=True)
        build_env = morphlib.buildenvironment.BuildEnvironment(
            self.app.settings, system_artifact.source.morphology['arch'])
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        artifact_files = set()
        for artifact in system_artifact.walk():
            artifact.cache_key = ckc.compute_key(artifact)
            artifact.cache_id = ckc.get_cache_id(artifact)

            artifact_files.add(artifact.basename())

            if artifact.source.morphology.needs_artifact_metadata_cached:
                artifact_files.add('%s.meta' % artifact.basename())

            # This is unfortunate hardwiring of behaviour; in future we
            # should list all artifacts in the meta-artifact file, so we
            # don't have to guess what files there will be.
            artifact_files.add('%s.meta' % artifact.cache_key)
            if artifact.source.morphology['kind'] == 'chunk':
                artifact_files.add('%s.build-log' % artifact.cache_key)

        return artifact_files
