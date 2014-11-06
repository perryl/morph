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


import cliapp

import collections
import cPickle
import json
import logging
import os

import morphlib
import pylru


class PickleCacheManager(object):
    '''Cache manager for PyLRU that reads and writes to Pickle files.

    The 'pickle' format is less than ideal in many ways and is actually
    slower than JSON in Python. However, the data we need to cache is keyed
    by tuples and in JSON a dict can only be keyed with strings. For now,
    using 'pickle' seems to be the least worst option.

    '''

    def __init__(self, filename, size):
        self.filename = filename
        self.size = size

    def _populate_cache_from_file(self, filename, cache):
        try:
            with open(filename, 'r') as f:
                data = cPickle.load(f)
            for key, value in data.iteritems():
                cache[str(key)] = value
        except (EOFError, IOError, cPickle.PickleError) as e:
            logging.warning('Failed to load cache %s: %s', self.filename, e)

    def load_cache(self):
        '''Create a pylru.lrucache object prepopulated with saved data.'''
        cache = pylru.lrucache(self.size)
        # There should be a more efficient way to do this, by hooking into
        # the json module directly.
        if os.path.exists(self.filename):
            self._populate_cache_from_file(self.filename, cache)
        return cache

    def save_cache(self, cache):
        '''Save the data from a pylru.lrucache object to disk.

        Any changes that have been made by other instances or processes since
        load_cache() was called will be overwritten.

        '''
        data = {}
        for key, value in cache.items():
            data[key] = value
        try:
            with open(self.filename, 'w') as f:
                cPickle.dump(data, f)
        except (IOError, cPickle.PickleError) as E:
            logging.warning('Failed to save cache to %s: %s', self.filename, e)


class SourceResolver(object):
    '''Provides a way of resolving the graph of sources for a given system.

    There are three levels of caching involved in resolving the sources to
    build.

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

    The third layer of caching is a simple commit SHA1 -> tree SHA mapping. It
    turns out that even if all repos are available locally, running
    'git rev-parse' on hundreds of repos requires a lot of IO and can take
    several minutes. Likewise, on a slow network connection it is time
    consuming to keep querying the remote repo cache. This third layer of
    caching works around both of those issues.

    The need for 3 levels of caching highlights design inconsistencies in
    Baserock, but for now it is worth the effort to maintain this code to save
    users from waiting 7 minutes each time that they want to build. The level 3
    cache is fairly simple because commits are immutable, so there is no danger
    of this cache being stale as long as it is indexed by commit SHA1. Due to
    the policy in Baserock of always using a commit SHA1 (rather than a named
    ref) in the system definitions, it makes repeated builds of a system very
    fast as no resolution needs to be done at all.

    '''

    def __init__(self, local_repo_cache, remote_repo_cache,
                 tree_cache_manager, update_repos, status_cb=None):
        self.lrc = local_repo_cache
        self.rrc = remote_repo_cache
        self.tree_cache_manager = tree_cache_manager

        self.update = update_repos

        self.status = status_cb

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

    def traverse_morphs(self, definitions_repo, definitions_ref,
                        system_filenames,
                        visit=lambda rn, rf, fn, arf, m: None,
                        definitions_original_ref=None):
        morph_factory = morphlib.morphologyfactory.MorphologyFactory(
            self.lrc, self.rrc, self.status)
        definitions_queue = collections.deque(system_filenames)
        chunk_in_definitions_repo_queue = []
        chunk_in_source_repo_queue = []

        resolved_commits = {}

        resolved_trees = self.tree_cache_manager.load_cache()

        resolved_morphologies = {}

        # Resolve the (repo, ref) pair for the definitions repo, cache result.
        definitions_absref, definitions_tree = self.resolve_ref(
            definitions_repo, definitions_ref)

        if definitions_original_ref:
            definitions_ref = definitions_original_ref

        while definitions_queue:
            filename = definitions_queue.popleft()

            key = (definitions_repo, definitions_absref, filename)
            if not key in resolved_morphologies:
                resolved_morphologies[key] = morph_factory.get_morphology(*key)
            morphology = resolved_morphologies[key]

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
            if not key in resolved_morphologies:
                resolved_morphologies[key] = morph_factory.get_morphology(*key)
            morphology = resolved_morphologies[key]
            visit(repo, ref, filename, absref, tree, morphology)

        for repo, ref, filename in chunk_in_source_repo_queue:
            if (repo, ref) not in resolved_trees:
                commit_sha1, tree_sha1 = self.resolve_ref(repo, ref)
                resolved_commits[repo, ref] = commit_sha1
                resolved_trees[repo, commit_sha1] = tree_sha1
            absref = resolved_commits[repo, ref]
            tree = resolved_trees[repo, absref]
            key = (repo, absref, filename)
            if key not in resolved_morphologies:
                resolved_morphologies[key] = morph_factory.get_morphology(*key)
            morphology = resolved_morphologies[key]
            visit(repo, ref, filename, absref, tree, morphology)

        self.tree_cache_manager.save_cache(resolved_trees)


def create_source_pool(app, lrc, rrc, repo, ref, filename,
                       original_ref=None):
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

    update_repos = not app.settings['no-git-update']

    tree_cache_manager = PickleCacheManager(
        os.path.join(app.settings['cachedir'], 'trees.cache.pickle'), 10000)

    resolver = SourceResolver(lrc, rrc, tree_cache_manager, update_repos,
                              app.status)
    resolver.traverse_morphs(repo, ref, [filename],
                             visit=add_to_pool,
                             definitions_original_ref=original_ref)
    return pool
