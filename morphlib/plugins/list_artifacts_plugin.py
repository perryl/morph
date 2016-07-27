# Copyright (C) 2014-2016  Codethink Limited
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

# This plugin is used as part of the Baserock automated release process.
#
# See: <http://wiki.baserock.org/guides/release-process> for more information.

from __future__ import print_function
import uuid

import cliapp
import morphlib


class ListArtifactsPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'list-artifacts', self.list_artifacts,
            arg_synopsis='MORPH [MORPH]...')

    def disable(self):
        pass

    def list_artifacts(self, args):
        '''List every artifact in the build graph of a system.

        Command line arguments:

        * `MORPH` is a system morphology name in the checked-out repository
            or in a remote repostory.

        Available options:

        * `--repo=REPO`` is a git repository URL.
        * `--ref=REF` is a branch or other commit reference in that repository.
        * `--local-changes=LOCAL-CHANGES` option to `ignore` or `include`
            uncommitted/unpushed local changes.

        You can pass multiple values for `MORPH`, in which case the command
        outputs the union of the build graphs of all the systems passed in.

        If not `REPO` and `REF` specified, it will look into the current
        working directory for a Definitions checkout.

        The output includes any meta-artifacts such as .meta and .build-log
        files.

        '''

        MINARGS = 1

        if len(args) < MINARGS:
            raise cliapp.AppException(
                'Wrong number of arguments to list-artifacts command '
                '(see help)')


        repo = self.app.settings['repo']
        ref = self.app.settings['ref']

        if bool(repo) ^ bool(ref):
            raise cliapp.AppException(
                '--repo and --ref work toghether, use both please.')

        if repo and ref:
            system_filenames = map(morphlib.util.sanitise_morphology_path,
                                   args)
            self._list_artifacts(repo, ref, system_filenames)
            return

        definitions_repo = morphlib.definitions_repo.open(
            '.', search_for_root=True, app=self.app)

        system_filenames = []
        for arg in args:
            filename = morphlib.util.sanitise_morphology_path(arg)
            filename = definitions_repo.relative_path(filename, cwd='.')
            system_filenames.append(filename)

        if self.app.settings['local-changes'] == 'include':
            # Create a temporary branch with any local changes, and push it to
            # the shared Git server. This is a convenience for developers, who
            # otherwise need to commit and push each change manually in order
            # for distbuild to see it. It renders the build unreproducible, as
            # the branch is deleted after being built, so this feature should
            # only be used during development!
            build_uuid = uuid.uuid4().hex
            branch = definitions_repo.branch_with_local_changes(
                build_uuid, push=True)
            with branch as (repo_url, commit, original_ref):
                self._list_artifacts(repo_url, commit, system_filenames)
        else:
            ref = definitions_repo.HEAD
            commit = definitions_repo.resolve_ref_to_commit(ref)
            self._list_artifacts(definitions_repo.remote_url, commit,
                                 system_filenames)

    def _list_artifacts(self, repo, ref, system_filenames):

        self.repo_cache = morphlib.util.new_repo_cache(self.app)
        self.resolver = morphlib.artifactresolver.ArtifactResolver()

        artifact_files = set()
        for system_filename in system_filenames:
            system_artifact_files = self.list_artifacts_for_system(
                repo, ref, system_filename)
            artifact_files.update(system_artifact_files)

        for artifact_file in sorted(artifact_files):
            print(artifact_file)

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
        source_pool = morphlib.sourceresolver.create_source_pool(
            self.repo_cache, repo, ref, [system_filename],
            status_cb=self.app.status)

        self.app.status(
            msg='Resolving artifacts for %s' % system_filename, chatty=True)
        root_artifacts = self.resolver.resolve_root_artifacts(source_pool)

        def find_artifact_by_name(artifacts_list, filename):
            for a in artifacts_list:
                if a.source.filename == filename:
                    return a
            raise ValueError

        system_artifact = find_artifact_by_name(root_artifacts,
                                                system_filename)

        self.app.status(
            msg='Computing cache keys for %s' % system_filename, chatty=True)
        build_env = morphlib.buildenvironment.BuildEnvironment(
            self.app.settings, system_artifact.source.morphology['arch'])
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        for source in set(a.source for a in system_artifact.walk()):
            source.cache_key = ckc.compute_key(source)
            source.cache_id = ckc.get_cache_id(source)

        artifact_files = set()
        for artifact in system_artifact.walk():

            artifact_files.add(artifact.basename())

            if artifact.source.morphology.needs_artifact_metadata_cached:
                artifact_files.add('%s.meta' % artifact.basename())

            # This is unfortunate hardwiring of behaviour; in future we
            # should list all artifacts in the meta-artifact file, so we
            # don't have to guess what files there will be.
            artifact_files.add('%s.meta' % artifact.source.cache_key)
            if artifact.source.morphology['kind'] == 'chunk':
                artifact_files.add('%s.build-log' % artifact.source.cache_key)

        return artifact_files
