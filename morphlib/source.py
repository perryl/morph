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
    * ``artifacts`` -- the set of artifacts this source produces.
    * ``split_rules`` -- rules for splitting the source's produced artifacts

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
        self.artifacts = {name: morphlib.artifact.Artifact(self, name)
                          for name in self.split_rules.artifacts}

    def __str__(self):  # pragma: no cover
        return '%s|%s|%s' % (self.repo_name,
                             self.original_ref,
                             self.filename)
