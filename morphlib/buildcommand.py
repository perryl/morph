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


import os
import shutil
import logging
import tempfile

import morphlib
import distbuild


class MultipleRootArtifactsError(morphlib.Error):

    def __init__(self, artifacts):
        self.msg = ('System build has multiple root artifacts: %r'
                    % [a.name for a in artifacts])
        self.artifacts = artifacts


class BuildCommand(object):

    '''High level logic for building.

    This controls how the whole build process goes. This is a separate
    class to enable easy experimentation of different approaches to
    the various parts of the process.

    '''

    def __init__(self, app, build_env = None):
        self.supports_local_build = True

        self.app = app
        self.lac, self.rac = self.new_artifact_caches()
        self.lrc, self.rrc = self.new_repo_caches()

    def build(self, args):
        '''Build triplets specified on command line.'''

        self.app.status(msg='Build starts', chatty=True)

        for repo_name, ref, filename in self.app.itertriplets(args):
            self.app.status(msg='Building %(repo_name)s %(ref)s %(filename)s',
                            repo_name=repo_name, ref=ref, filename=filename)
            self.app.status(msg='Deciding on task order')
            srcpool = self.create_source_pool(repo_name, ref, filename)
            self.validate_sources(srcpool)
            root_artifact = self.resolve_artifacts(srcpool)
            self.build_in_order(root_artifact)

        self.app.status(msg='Build ends successfully')

    def new_artifact_caches(self):
        '''Create interfaces for the build artifact caches.

        This includes creating the directories on disk if they are missing.

        '''
        return morphlib.util.new_artifact_caches(self.app.settings)

    def new_repo_caches(self):
        return morphlib.util.new_repo_caches(self.app)

    def new_build_env(self, arch):
        '''Create a new BuildEnvironment instance.'''
        return morphlib.buildenvironment.BuildEnvironment(self.app.settings,
                                                          arch)

    def create_source_pool(self, repo_name, ref, filename):
        '''Find the source objects required for building a the given artifact

        The SourcePool will contain every stratum and chunk dependency of the
        given artifact (which must be a system) but will not take into account
        any Git submodules which are required in the build.

        '''
        self.app.status(msg='Creating source pool', chatty=True)
        srcpool = self.app.create_source_pool(
            self.lrc, self.rrc, (repo_name, ref, filename))

        return srcpool

    def validate_sources(self, srcpool):
        self.app.status(
            msg='Validating cross-morphology references', chatty=True)
        self._validate_cross_morphology_references(srcpool)

        self.app.status(msg='Validating for there being non-bootstrap chunks',
                        chatty=True)
        self._validate_has_non_bootstrap_chunks(srcpool)

    def _validate_root_artifact(self, root_artifact):
        self._validate_root_kind(root_artifact)
        self._validate_architecture(root_artifact)

    @staticmethod
    def _validate_root_kind(root_artifact):
        root_kind = root_artifact.source.morphology['kind']
        if root_kind != 'system':
            raise morphlib.Error(
                'Building a %s directly is not supported' % root_kind)

    def _validate_architecture(self, root_artifact):
        '''Perform the validation between root and target architectures.'''

        root_arch = root_artifact.source.morphology['arch']
        host_arch = morphlib.util.get_host_architecture()
        if root_arch != host_arch:
            raise morphlib.Error(
                'Are you trying to cross-build? '
                    'Host architecture is %s but target is %s'
                    % (host_arch, root_arch))

    @staticmethod
    def _validate_has_non_bootstrap_chunks(srcpool):
        stratum_sources = [src for src in srcpool
                           if src.morphology['kind'] == 'stratum']
        # any will return true for an empty iterable, which will give
        # a false positive when there are no strata.
        # This is an error by itself, but the source of this error can
        # be better diagnosed later, so we abort validating here.
        if not stratum_sources:
            return

        if not any(spec.get('build-mode', 'staging') != 'bootstrap'
                   for src in stratum_sources
                   for spec in src.morphology['chunks']):
            raise morphlib.Error('No non-bootstrap chunks found.')

    def resolve_artifacts(self, srcpool):
        '''Resolve the artifacts that will be built for a set of sources'''

        self.app.status(msg='Creating artifact resolver', chatty=True)
        ar = morphlib.artifactresolver.ArtifactResolver()

        self.app.status(msg='Resolving artifacts', chatty=True)
        artifacts = ar.resolve_artifacts(srcpool)

        self.app.status(msg='Computing build order', chatty=True)
        root_artifacts = self._find_root_artifacts(artifacts)
        if len(root_artifacts) > 1:
            # Validate root artifacts, since validation covers errors
            # such as trying to build a chunk or stratum directly,
            # and this is one cause for having multiple root artifacts
            for root_artifact in root_artifacts:
                self._validate_root_artifact(root_artifact)
            raise MultipleRootArtifactsError(root_artifacts)
        root_artifact = root_artifacts[0]

        # Validate the root artifact here, since it's a costly function
        # to finalise it, so any pre finalisation validation is better
        # done before that happens, but we also don't want to expose
        # the root artifact until it's finalised.
        self.app.status(msg='Validating root artifact', chatty=True)
        self._validate_root_artifact(root_artifact)
        arch = root_artifact.source.morphology['arch']

        self.app.status(msg='Creating build environment for %(arch)s',
                        arch=arch, chatty=True)
        build_env = self.new_build_env(arch)

        self.app.status(msg='Computing cache keys', chatty=True)
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)
        for artifact in artifacts:
            artifact.cache_key = ckc.compute_key(artifact)
            artifact.cache_id = ckc.get_cache_id(artifact)

            logging.debug('artifact.cache_key: %s\tartifact.cache_id: %s'
                % (artifact.cache_key, artifact.cache_id))

        root_artifact.build_env = build_env
        return root_artifact

    def _validate_cross_morphology_references(self, srcpool):
        '''Perform validation across all morphologies involved in the build'''

        stratum_names = []

        for src in srcpool:
            kind = src.morphology['kind']

            # Verify that chunks pointed to by strata really are chunks, etc.
            method_name = '_validate_cross_refs_for_%s' % kind
            if hasattr(self, method_name):
                logging.debug('Calling %s' % method_name)
                getattr(self, method_name)(src, srcpool)
            else:
                logging.warning('No %s' % method_name)

            # Verify stratum build-depends agree with the system's contents.
            # It is permissible for a stratum to build-depend on a stratum that
            # isn't specified in the target system morphology.
            # Multiple references to the same stratum are permitted. This is
            # handled by the SourcePool deduplicating added Sources.
            # It is forbidden to have two different strata with the same name.
            # Hence if a Stratum is defined in the System, and in a Stratum as
            # a build-dependency, then they must both have the same Repository
            # and Ref specified.
            if src.morphology['kind'] == 'stratum':
                name = src.morphology['name']
                ref = src.sha1[:7]
                self.app.status(msg='Stratum [%(name)s] version is %(ref)s', 
                                name=name, ref=ref)
                if name in stratum_names:
                    raise morphlib.Error(
                        "Conflicting versions of stratum '%s' appear in the "
                        "build. Check the contents of the system against the "
                        "build-depends of the strata." % name)
                stratum_names.append(name)

    def _validate_cross_refs_for_system(self, src, srcpool):
        self._validate_cross_refs_for_xxx(
            src, srcpool, src.morphology['strata'], 'stratum')

    def _validate_cross_refs_for_stratum(self, src, srcpool):
        self._validate_cross_refs_for_xxx(
            src, srcpool, src.morphology['chunks'], 'chunk')

    def _validate_cross_refs_for_xxx(self, src, srcpool, specs, wanted):
        for spec in specs:
            repo_name = spec.get('repo') or src.repo_name
            ref = spec.get('ref') or src.original_ref
            filename = '%s.morph' % spec['morph']
            logging.debug(
                'Validating cross ref to %s:%s:%s' %
                    (repo_name, ref, filename))
            other = srcpool.lookup(repo_name, ref, filename)
            if other.morphology['kind'] != wanted:
                raise morphlib.Error(
                    '%s %s references %s:%s:%s which is a %s, '
                        'instead of a %s' %
                        (src.morphology['kind'],
                         src.morphology['name'],
                         repo_name,
                         ref,
                         filename,
                         other.morphology['kind'],
                         wanted))

    def _find_root_artifacts(self, artifacts):
        '''Find all the root artifacts among a set of artifacts in a DAG.
        
        It would be nice if the ArtifactResolver would return its results in a
        more useful order to save us from needing to do this -- the root object
        is known already since that's the one the user asked us to build.
        
        '''

        return [a for a in artifacts if not a.dependents]

    def build_in_order(self, root_artifact):
        '''Build everything specified in a build order.'''

        self.app.status(msg='Building a set of artifacts', chatty=True)
        build_env = root_artifact.build_env
        artifacts = root_artifact.walk()
        old_prefix = self.app.status_prefix
        for i, a in enumerate(artifacts):
            self.app.status_prefix = (
                old_prefix + '[Build %(index)d/%(total)d] [%(name)s] ' % {
                    'index': (i+1),
                    'total': len(artifacts),
                    'name': a.name,
                })

            self.app.status(msg='Checking if %(kind)s needs '
                                'building %(sha1)s',
                            kind=a.source.morphology['kind'],
                            sha1=a.source.sha1[:7])

            if self.is_built(a):
                self.cache_artifacts_locally([a])
                self.app.status(
                    msg='The %(kind)s is cached at %(cache)s',
                    kind=a.source.morphology['kind'],
                    cache=os.path.basename(self.lac.artifact_filename(a))[:7])
            else:
                self.app.status(msg='Building %(kind)s %(name)s',
                                name=a.name, kind=a.source.morphology['kind'])
                self.build_artifact(a, build_env)

            self.app.status(msg='%(kind)s %(name)s is cached at %(cachepath)s',
                            kind=a.source.morphology['kind'], name=a.name,
                            cachepath=self.lac.artifact_filename(a),
                            chatty=(a.source.morphology['kind'] != "system"))
        self.app.status_prefix = old_prefix

    def is_built(self, artifact):
        '''Does either cache already have the artifact?'''
        return self.lac.has(artifact) or (self.rac and self.rac.has(artifact))

    def build_artifact(self, artifact, build_env):
        '''Build one artifact.

        All the dependencies are assumed to be built and available
        in either the local or remote cache already.

        '''
        self.get_sources(artifact)
        deps = self.get_recursive_deps(artifact)
        self.cache_artifacts_locally(deps)

        use_chroot = False
        setup_mounts = False
        if artifact.source.morphology['kind'] == 'chunk':
            build_mode = artifact.source.build_mode
            extra_env = {'PREFIX': artifact.source.prefix}

            dep_prefix_set = artifact.get_dependency_prefix_set()
            extra_path = [os.path.join(d, 'bin') for d in dep_prefix_set]

            if build_mode not in ['bootstrap', 'staging', 'test']:
                logging.warning('Unknown build mode %s for chunk %s. '
                                'Defaulting to staging mode.' %
                                (build_mode, artifact.name))
                build_mode = 'staging'

            if build_mode == 'staging':
                use_chroot = True
                setup_mounts = True

            staging_area = self.create_staging_area(build_env,
                                                    use_chroot,
                                                    extra_env=extra_env,
                                                    extra_path=extra_path)
            try:
                self.install_dependencies(staging_area, deps, artifact)
            except BaseException:
                staging_area.abort()
                raise
        else:
            staging_area = self.create_staging_area(build_env, False)

        self.build_and_cache(staging_area, artifact, setup_mounts)
        self.remove_staging_area(staging_area)

    def get_recursive_deps(self, artifact):
        return artifact.walk()[:-1]

    def get_sources(self, artifact):
        '''Update the local git repository cache with the sources.'''

        repo_name = artifact.source.repo_name
        if self.app.settings['no-git-update']:
            self.app.status(msg='Not updating existing git repository '
                                '%(repo_name)s '
                                'because of no-git-update being set',
                            chatty=True,
                            repo_name=repo_name)
            artifact.source.repo = self.lrc.get_repo(repo_name)
            return

        if self.lrc.has_repo(repo_name):
            artifact.source.repo = self.lrc.get_repo(repo_name)
            try:
                sha1 = artifact.source.sha1
                artifact.source.repo.resolve_ref(sha1)
                self.app.status(msg='Not updating git repository '
                                    '%(repo_name)s because it '
                                    'already contains sha1 %(sha1)s',
                                chatty=True, repo_name=repo_name,
                                sha1=sha1)
            except morphlib.cachedrepo.InvalidReferenceError:
                self.app.status(msg='Updating %(repo_name)s',
                                repo_name=repo_name)
                artifact.source.repo.update()
        else:
            self.app.status(msg='Cloning %(repo_name)s',
                            repo_name=repo_name)
            artifact.source.repo = self.lrc.cache_repo(repo_name)

        # Update submodules.
        done = set()
        self.app.cache_repo_and_submodules(
            self.lrc, artifact.source.repo.url,
            artifact.source.sha1, done)

    def cache_artifacts_locally(self, artifacts):
        '''Get artifacts missing from local cache from remote cache.'''

        def copy(remote, local):
            shutil.copyfileobj(remote, local)
            remote.close()
            local.close()

        for artifact in artifacts:
            if not self.lac.has(artifact):
                self.app.status(msg='Fetching to local cache: '
                                    'artifact %(name)s',
                                name=artifact.name)
                rac_file = self.rac.get(artifact)
                lac_file = self.lac.put(artifact)
                copy(rac_file, lac_file)

            if artifact.source.morphology.needs_artifact_metadata_cached:
                if not self.lac.has_artifact_metadata(artifact, 'meta'):
                    self.app.status(msg='Fetching to local cache: '
                                        'artifact metadata %(name)s',
                                    name=artifact.name)
                    copy(self.rac.get_artifact_metadata(artifact, 'meta'),
                         self.lac.put_artifact_metadata(artifact, 'meta'))

    def create_staging_area(self, build_env, use_chroot=True, extra_env={},
                            extra_path=[]):
        '''Create the staging area for building a single artifact.'''

        self.app.status(msg='Creating staging area')
        staging_dir = tempfile.mkdtemp(
            dir=os.path.join(self.app.settings['tempdir'], 'staging'))
        staging_area = morphlib.stagingarea.StagingArea(
            self.app, staging_dir, build_env, use_chroot, extra_env,
            extra_path)
        return staging_area

    def remove_staging_area(self, staging_area):
        '''Remove the staging area.'''

        self.app.status(msg='Removing staging area')
        staging_area.remove()

    # Nasty hack to avoid installing chunks built in 'bootstrap' mode in a
    # different stratum when constructing staging areas.
    def is_stratum(self, a):
        return a.source.morphology['kind'] == 'stratum'

    def in_same_stratum(self, a, b):
        return len(filter(self.is_stratum, a.dependencies)) == \
               len(filter(self.is_stratum, b.dependencies))

    def install_dependencies(self, staging_area, artifacts, target_artifact):
        '''Install chunk artifacts into staging area.

        We only ever care about chunk artifacts as build dependencies,
        so this is not a generic artifact installer into staging area.
        Any non-chunk artifacts are silently ignored.

        All artifacts MUST be in the local artifact cache already.

        '''

        for artifact in artifacts:
            if artifact.source.morphology['kind'] != 'chunk':
                continue
            if artifact.source.build_mode == 'bootstrap':
               if not self.in_same_stratum(artifact, target_artifact):
                    continue
            self.app.status(
                msg='Installing chunk %(chunk_name)s from cache %(cache)s',
                chunk_name=artifact.name,
                cache=artifact.cache_key[:7],
                chatty=True)
            handle = self.lac.get(artifact)
            staging_area.install_artifact(handle)

        if target_artifact.source.build_mode == 'staging':
            morphlib.builder2.ldconfig(self.app.runcmd, staging_area.dirname)

    def build_and_cache(self, staging_area, artifact, setup_mounts):
        '''Build an artifact and put it into the local artifact cache.'''

        self.app.status(msg='Starting actual build: %(name)s '
                            '%(sha1)s',
                        name=artifact.name, sha1=artifact.source.sha1[:7])
        builder = morphlib.builder2.Builder(
            self.app, staging_area, self.lac, self.rac, self.lrc,
            self.app.settings['max-jobs'], setup_mounts)
        return builder.build_and_cache(artifact)

class InitiatorBuildCommand(BuildCommand):

    def __init__(self, app, addr, port):
        self.app = app
        self.addr = addr
        self.port = port
        self.app.settings['push-build-branches'] = True
        super(InitiatorBuildCommand, self).__init__(app)

    def build(self, args):
        '''Initiate a distributed build on a controller'''

        distbuild.add_crash_conditions(self.app.settings['crash-condition'])

        if len(args) != 3:
            raise morphlib.Error(
                'Need repo, ref, morphology triplet to build')

        if self.addr == '':
            raise morphlib.Error(
                'Need address of controller to run a distbuild')

        self.app.status(msg='Starting distributed build')
        loop = distbuild.MainLoop()
        cm = distbuild.ConnectionMachine(
            self.addr, self.port, distbuild.Initiator, [self.app] + args)
        loop.add_state_machine(cm)
        loop.run()
