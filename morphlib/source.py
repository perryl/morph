# Copyright (C) 2012-2014  Codethink Limited
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
    * ``split_rules`` -- rules for splitting the source's produced artifacts
    * ``artifacts`` -- the set of artifacts this source produces, or
                       None if it has not yet been set by the
                       ArtifactResolver.

    '''

    def __init__(self, repo_name, original_ref, sha1, tree, morphology,
            filename):
        self.repo = None
        self.repo_name = repo_name
        self.original_ref = original_ref
        self.sha1 = sha1
        self.tree = tree
        self.morphology = morphology
        self.filename = filename

        kind = morphology['kind']
        unifier = getattr(morphlib.artifactsplitrule,
                          'unify_%s_matches' % kind)
        self.split_rules = unifier(morphology)
        self.artifacts = None

    def __str__(self):  # pragma: no cover
        return '%s|%s|%s' % (self.repo_name,
                             self.original_ref,
                             self.filename[:-len('.morph')])

    def get_artifact(self, name): # pragma: no cover
        '''Get the artifact of this source named ``name``.

        This initialises a new Artifact object with this source as a
        parent, if it does not already exist.

        The same Artifact object is returned if the same name is given
        later.

        The set of Artifacts a Source has may be iterated over with the
        ``artifacts`` field, which has the sentinel value of ``None``
        if no Artifacts have been initialised yet.

        '''
        if self.artifacts is None:
            self.artifacts = {}
        try:
            return self.artifacts[name]
        except KeyError:
            a = morphlib.artifact.Artifact(self, name)
            self.artifacts[name] = a
            return a
