# Copyright (C) 2012-2016  Codethink Limited
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


import morphlib


class Source(object):

    '''Represent the source to be built.

    Has the following properties:

    * ``repo`` -- the git repository which contains the source
    * ``repo_name`` -- name of the git repository which contains the source
    * ``original_ref`` -- the git ref provided by the user or a morphology
    * ``sha1`` -- the absolute git commit id for the revision we use
    * ``tree`` -- the SHA1 of the tree corresponding to the commit
    * ``morphology`` -- the in-memory representation of the morphology we use
    * ``filename`` -- basename of the morphology filename
    * ``cache_id`` -- a dict describing the components of the cache key
    * ``cache_key`` -- a cache key to uniquely identify the artifact
    * ``dependencies`` -- list of Artifacts that need to be built beforehand
    * ``split_rules`` -- rules for splitting the source's produced artifacts
    * ``artifacts`` -- the set of artifacts this source produces.

    '''

    def __init__(self, name, repo_name, original_ref, sha1, tree, morphology,
            filename, split_rules):
        self.name = name
        self.repo = None
        self.repo_name = repo_name
        self.original_ref = original_ref
        self.sha1 = sha1
        self.tree = tree
        self.morphology = morphology
        self.filename = filename
        self.cache_id = None
        self.cache_key = None
        self.dependencies = []

        self.split_rules = split_rules
        self.artifacts = None

    def __str__(self):  # pragma: no cover
        return '%s|%s|%s|%s' % (self.repo_name,
                                self.original_ref,
                                self.filename,
                                self.name)

    def __repr__(self): # pragma: no cover
        return 'Source(%s)' % str(self)

    def basename(self): # pragma: no cover
        return '%s.%s' % (self.cache_key, str(self.morphology['kind']))

    def add_dependency(self, artifact): # pragma: no cover
        if artifact not in self.dependencies:
            self.dependencies.append(artifact)
        if self not in artifact.dependents:
            artifact.dependents.append(self)

    def depends_on(self, artifact): # pragma: no cover
        '''Do we depend on ``artifact``?'''
        return artifact in self.dependencies


def make_sources(reponame, ref, filename, absref, tree, morphology,
                 default_split_rules={}):
    kind = morphology['kind']
    if kind in ('system', 'chunk'):
        unifier = getattr(morphlib.artifactsplitrule,
                          'unify_%s_matches' % kind)
        split_rules = unifier(morphology,
                              default_rules=default_split_rules.get(kind, {}))
        # chunk and system sources are named after the morphology
        source_name = morphology['name']
        source = morphlib.source.Source(source_name, reponame, ref,
                                        absref, tree, morphology,
                                        filename, split_rules)
        source.artifacts = {name: morphlib.artifact.Artifact(source, name)
                     for name in split_rules.artifacts}
        yield source
    elif kind == 'stratum': # pragma: no cover
        unifier = morphlib.artifactsplitrule.unify_stratum_matches
        split_rules = unifier(morphology,
                              default_rules=default_split_rules.get(kind, {}))
        for name in split_rules.artifacts:
            source = morphlib.source.Source(
                name, # stratum source name is artifact name
                reponame, ref, absref, tree, morphology, filename,
                # stratum sources need to match the unified
                # split rules, so they know to yield the match
                # to a different source
                split_rules)
            source.artifacts = {name: morphlib.artifact.Artifact(source, name)}
            yield source
    else:
        # cluster morphologies don't have sources
        pass
