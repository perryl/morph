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
import logging

import morphlib


class SourceResolver(object):
    '''Provides a way of resolving the graph of sources for a given system.'''

    def __init__(self, lrc, rrc, status_cb):
        self.lrc = lrc
        self.rrc = rrc

        self.status = status_cb

    def resolve_ref(self, reponame, ref, update=True):
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating
        or cloning the repository into the local repo cache.
        '''
        absref = None

        if self.lrc.has_repo(reponame):
            repo = self.lrc.get_repo(reponame)
            if update and repo.requires_update_for_ref(ref):
                self.status(msg='Updating cached git repository %(reponame)s '
                            'for ref %(ref)s', reponame=reponame, ref=ref)
                repo.update()
            # If the user passed --no-git-update, and the ref is a SHA1 not
            # available locally, this call will raise an exception.
            absref, tree = repo.resolve_ref(ref)
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
            if update:
                self.status(msg='Caching git repository %(reponame)s',
                            reponame=reponame)
                repo = self.lrc.cache_repo(reponame)
                repo.update()
            else:
                repo = self.lrc.get_repo(reponame)
            absref, tree = repo.resolve_ref(ref)
        return absref, tree

    def traverse_morphs(self, definitions_repo, definitions_ref,
                        system_filenames, update=True,
                        visit=lambda rn, rf, fn, arf, m: None,
                        definitions_original_ref=None):
        morph_factory = morphlib.morphologyfactory.MorphologyFactory(
            self.lrc, self.rrc, self.status)
        definitions_queue = collections.deque(system_filenames)
        chunk_in_definitions_repo_queue = []
        chunk_in_source_repo_queue = []
        resolved_refs = {}
        resolved_morphologies = {}

        # Resolve the (repo, ref) pair for the definitions repo, cache result.
        definitions_absref, definitions_tree = self.resolve_ref(
            definitions_repo, definitions_ref, update)

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
            if (repo, ref) not in resolved_refs:
                resolved_refs[repo, ref] = self.resolve_ref(repo, ref, update)
            absref, tree = resolved_refs[repo, ref]
            key = (definitions_repo, definitions_absref, filename)
            if not key in resolved_morphologies:
                resolved_morphologies[key] = morph_factory.get_morphology(*key)
            morphology = resolved_morphologies[key]
            visit(repo, ref, filename, absref, tree, morphology)

        for repo, ref, filename in chunk_in_source_repo_queue:
            if (repo, ref) not in resolved_refs:
                resolved_refs[repo, ref] = self.resolve_ref(repo, ref, update)
            absref, tree = resolved_refs[repo, ref]
            key = (repo, absref, filename)
            if key not in resolved_morphologies:
                resolved_morphologies[key] = morph_factory.get_morphology(*key)
            morphology = resolved_morphologies[key]
            visit(repo, ref, filename, absref, tree, morphology)


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

    resolver = SourceResolver(lrc, rrc, app.status)
    resolver.traverse_morphs(repo, ref, [filename],
                             update=not app.settings['no-git-update'],
                             visit=add_to_pool,
                             definitions_original_ref=original_ref)
    return pool
