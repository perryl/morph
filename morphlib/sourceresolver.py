# Copyright (C) 2014-2015  Codethink Limited
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


import cliapp

import collections
import logging
import os

import morphlib


class SourceResolverError(cliapp.AppException):
    pass


class MorphologyNotFoundError(SourceResolverError):
    def __init__(self, filename):
        SourceResolverError.__init__(
            self, "Couldn't find morphology: %s" % filename)


class NotcachedError(SourceResolverError):
    def __init__(self, repo_name):
        SourceResolverError.__init__(
            self, "Repository %s is not cached locally and there is no "
                  "remote cache specified" % repo_name)


class SourceResolver(object):
    '''Provides a way of resolving the set of sources for a given system.

    There are two levels of caching involved in resolving the sources to build.

    The canonical source for each source is specified in the build-command
    (for strata and systems) or in the stratum morphology (for chunks). It will
    be either a normal URL, or a keyed URL using a repo-alias like
    'baserock:baserock/definitions'.

    The 'remote repo cache' is a Baserock Trove system. It functions as a
    normal Git server, but in addition it runs a service on port 8080 called
    'morph-cache-server' which can resolve refs, list their contents and read
    specific files from the repos it holds. This allows the SourceResolver to
    work out how to build something without cloning the whole repo. (If a local
    build of that source ends up being necessary then it will get cloned into
    the local cache later on).

    The second layer of caching is the local repository cache, which mirrors
    entire repositories in $cachedir/gits. If a repo is not in the remote repo
    cache then it must be present in the local repo cache.

    '''

    def __init__(self, local_repo_cache, remote_repo_cache, update_repos,
                 status_cb=None):
        self.lrc = local_repo_cache
        self.rrc = remote_repo_cache

        self.update = update_repos
        self.status = status_cb

        self._resolved_trees = {}
        self._resolved_morphologies = {}

    def resolve_ref(self, reponame, ref):
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating
        or cloning the repository into the local repo cache.
        '''
        absref = None

        if self.lrc.has_repo(reponame):
            repo = self.lrc.get_repo(reponame)
            if self.update and repo.requires_update_for_ref(ref):
                self.status(msg='Updating cached git repository %(reponame)s '
                            'for ref %(ref)s', reponame=reponame, ref=ref)
                repo.update()
            # If the user passed --no-git-update, and the ref is a SHA1 not
            # available locally, this call will raise an exception.
            absref = repo.resolve_ref_to_commit(ref)
            tree = repo.resolve_ref_to_tree(absref)
        elif self.rrc is not None:
            try:
                absref, tree = self.rrc.resolve_ref(reponame, ref)
                if absref is not None:
                    self.status(msg='Resolved %(reponame)s %(ref)s via remote '
                                'repo cache',
                                reponame=reponame,
                                ref=ref,
                                chatty=True)
            except BaseException, e:
                logging.warning('Caught (and ignored) exception: %s' % str(e))
        if absref is None:
            if self.update:
                self.status(msg='Caching git repository %(reponame)s',
                            reponame=reponame)
                repo = self.lrc.cache_repo(reponame)
                repo.update()
            else:
                repo = self.lrc.get_repo(reponame)
            absref = repo.resolve_ref_to_commit(ref)
            tree = repo.resolve_ref_to_tree(absref)
        return absref, tree

    def _get_morphology(self, reponame, sha1, filename):
        '''Read the morphology at the specified location.'''
        key = (reponame, sha1, filename)
        if key in self._resolved_morphologies:
            return self._resolved_morphologies[key]

        morph_name = os.path.splitext(os.path.basename(filename))[0]
        loader = morphlib.morphloader.MorphologyLoader()
        if self.lrc.has_repo(reponame):
            self.status(msg="Looking for %s in local repo cache" % filename,
                        chatty=True)
            try:
                repo = self.lrc.get_repo(reponame)
                text = repo.read_file(filename, sha1)
                morph = loader.load_from_string(text)
            except IOError:
                morph = None
                file_list = repo.list_files(ref=sha1, recurse=False)
        elif self.rrc is not None:
            self.status(msg="Retrieving %(reponame)s %(sha1)s %(filename)s"
                        " from the remote git cache.",
                        reponame=reponame, sha1=sha1, filename=filename,
                        chatty=True)
            try:
                text = self.rrc.cat_file(reponame, sha1, filename)
                morph = loader.load_from_string(text)
            except morphlib.remoterepocache.CatFileError:
                morph = None
                file_list = self.rrc.ls_tree(reponame, sha1)
        else:
            raise NotcachedError(reponame)

        if morph is None:
            self.status(msg="File %s doesn't exist: attempting to infer "
                            "chunk morph from repo's build system"
                        % filename, chatty=True)
            bs = morphlib.buildsystem.detect_build_system(file_list)
            if bs is None:
                raise MorphologyNotFoundError(filename)
            morph = bs.get_morphology(morph_name)
            loader.validate(morph)
            loader.set_commands(morph)
            loader.set_defaults(morph)

        self._resolved_morphologies[key] = morph
        return morph

    def traverse_morphs(self, definitions_repo, definitions_ref,
                        system_filenames,
                        visit=lambda rn, rf, fn, arf, m: None,
                        definitions_original_ref=None):
        definitions_queue = collections.deque(system_filenames)
        chunk_in_definitions_repo_queue = []
        chunk_in_source_repo_queue = []

        resolved_commits = {}
        resolved_trees = {}
        resolved_morphologies = {}

        # Resolve the (repo, ref) pair for the definitions repo, cache result.
        definitions_absref, definitions_tree = self.resolve_ref(
            definitions_repo, definitions_ref)

        if definitions_original_ref:
            definitions_ref = definitions_original_ref

        while definitions_queue:
            filename = definitions_queue.popleft()

            morphology = self._get_morphology(
                definitions_repo, definitions_absref, filename)

            visit(definitions_repo, definitions_ref, filename,
                  definitions_absref, definitions_tree, morphology)
            if morphology['kind'] == 'cluster':
                raise cliapp.AppException(
                    "Cannot build a morphology of type 'cluster'.")
            elif morphology['kind'] == 'system':
                definitions_queue.extend(
                    morphlib.util.sanitise_morphology_path(s['morph'])
                    for s in morphology['strata'])
            elif morphology['kind'] == 'stratum':
                if morphology['build-depends']:
                    definitions_queue.extend(
                        morphlib.util.sanitise_morphology_path(s['morph'])
                        for s in morphology['build-depends'])
                for c in morphology['chunks']:
                    if 'morph' not in c:
                        path = morphlib.util.sanitise_morphology_path(
                            c.get('morph', c['name']))
                        chunk_in_source_repo_queue.append(
                            (c['repo'], c['ref'], path))
                        continue
                    chunk_in_definitions_repo_queue.append(
                        (c['repo'], c['ref'], c['morph']))

        for repo, ref, filename in chunk_in_definitions_repo_queue:
            if (repo, ref) not in resolved_trees:
                commit_sha1, tree_sha1 = self.resolve_ref(repo, ref)
                resolved_commits[repo, ref] = commit_sha1
                resolved_trees[repo, commit_sha1] = tree_sha1
            absref = resolved_commits[repo, ref]
            tree = resolved_trees[repo, absref]
            key = (definitions_repo, definitions_absref, filename)
            morphology = self._get_morphology(*key)
            visit(repo, ref, filename, absref, tree, morphology)

        for repo, ref, filename in chunk_in_source_repo_queue:
            if (repo, ref) not in resolved_trees:
                commit_sha1, tree_sha1 = self.resolve_ref(repo, ref)
                resolved_commits[repo, ref] = commit_sha1
                resolved_trees[repo, commit_sha1] = tree_sha1
            absref = resolved_commits[repo, ref]
            tree = resolved_trees[repo, absref]
            key = (repo, absref, filename)
            morphology = self._get_morphology(*key)
            visit(repo, ref, filename, absref, tree, morphology)


def create_source_pool(lrc, rrc, repo, ref, filename,
                       original_ref=None, update_repos=True,
                       status_cb=None):
    '''Find all the sources involved in building a given system.

    Given a system morphology, this function will traverse the tree of stratum
    and chunk morphologies that the system points to and create appropriate
    Source objects. These are added to a new SourcePool object, which is
    returned.

    Note that Git submodules are not considered 'sources' in the current
    implementation, and so they must be handled separately.

    The 'lrc' and 'rrc' parameters specify the local and remote Git repository
    caches used for resolving the sources.

    '''
    pool = morphlib.sourcepool.SourcePool()

    def add_to_pool(reponame, ref, filename, absref, tree, morphology):
        sources = morphlib.source.make_sources(reponame, ref,
                                               filename, absref,
                                               tree, morphology)
        for source in sources:
            pool.add(source)

    resolver = SourceResolver(lrc, rrc, update_repos, status_cb)
    resolver.traverse_morphs(repo, ref, [filename],
                             visit=add_to_pool,
                             definitions_original_ref=original_ref)
    return pool
