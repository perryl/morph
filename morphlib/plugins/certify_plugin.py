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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# This plugin is used as part of the Baserock automated release process.
#
# See: <http://wiki.baserock.org/guides/release-process> for more information.

import warnings

import cliapp
import morphlib

class CertifyPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'certify', self.certify,
            arg_synopsis='REPO REF MORPH [MORPH]...')

    def disable(self):
        pass

    def certify(self, args):
        '''Certify that any given system definition is reproducible.

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a branch or other commit reference in that repository.
        * `MORPH` is a system morphology name at that ref.

        Example:

            morph certify baserock:baserock/definitions master \
                systems/devel-system-x86_64-generic.morph

        '''

        if len(args) < 3:
            raise cliapp.AppException(
                'Wrong number of arguments to certify command '
                '(see help)')

        repo, ref = args[0], args[1]
        system_filenames = map(morphlib.util.sanitise_morphology_path,
                               args[2:])

        self.lrc, self.rrc = morphlib.util.new_repo_caches(self.app)
        self.resolver = morphlib.artifactresolver.ArtifactResolver()

        for system_filename in system_filenames:
            self.certify_system(repo, ref, system_filename)

    def certify_system(self, repo, ref, system_filename):
        '''Certify reproducibility of system.'''

        self.app.status(
            msg='Creating source pool for %s' % system_filename, chatty=True)
        source_pool = morphlib.sourceresolver.create_source_pool(
            self.lrc, self.rrc, repo, ref, [system_filename],
            cachedir=self.app.settings['cachedir'],
            update_repos = not self.app.settings['no-git-update'],
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

        aliases = self.app.settings['repo-alias']
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)

        certified = True

        for source in set(a.source for a in system_artifact.walk()):
            source.cache_key = ckc.compute_key(source)
            source.cache_id = ckc.get_cache_id(source)

            if source.morphology['kind'] != 'chunk':
                continue

            name = source.morphology['name']
            ref = source.original_ref

            # Test that chunk has a sha1 ref
            # TODO: Could allow either sha1 or existent tag.
            if not morphlib.git.is_valid_sha1(ref):
                warnings.warn('Chunk "{}" has non-sha1 ref: "{}"\n'
                              .format(name, ref))
                certified = False

            cached = self.lrc.get_updated_repo(source.repo_name, ref)

            # Test that sha1 ref is anchored in a tag or branch,
            # and thus not a candidate for removal on `git gc`.
            if (morphlib.git.is_valid_sha1(ref) and
                    not len(cached.tags_containing_sha1(ref)) and
                    not len(cached.branches_containing_sha1(ref))):
                warnings.warn('Chunk "{}" has unanchored ref: "{}"\n'
                              .format(name, ref))
                certified = False

            # Test that chunk repo is on trove-host
            pull_url = resolver.pull_url(source.repo_name)
            if self.app.settings['trove-host'] not in pull_url:
                warnings.warn('Chunk "{}" has repo not on trove-host: "{}"\n'
                              .format(name, pull_url))
                certified = False

        if certified:
            print('=> Reproducibility certification PASSED for\n   {}'
                  .format(system_filename))
        else:
            print('=> Reproducibility certification FAILED for\n   {}'
                  .format(system_filename))
