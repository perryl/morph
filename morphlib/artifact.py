# Copyright (C) 2012, 2013, 2014  Codethink Limited
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


class Artifact(object):

    '''Represent a build result generated from a source.

    Has the following properties:

    * ``source`` -- the source from which the artifact is built
    * ``name`` -- the name of the artifact
    * ``dependents`` -- list of Sources that need this Artifact to be built

    '''

    def __init__(self, source, name):
        self.source = source
        self.name = name
        self.dependents = []

    def basename(self):  # pragma: no cover
        return '%s.%s' % (self.source.basename(), str(self.name))

    @property
    def kind(self): #pragma: no cover
        return self.source.morphology['kind']

    def metadata_basename(self, metadata_name):  # pragma: no cover
        return '%s.%s' % (self.basename(), metadata_name)

    def __str__(self):  # pragma: no cover
        return '%s|%s' % (self.source, self.name)

    def __repr__(self): # pragma: no cover
        return 'Artifact(%s)' % str(self)


    def walk(self): # pragma: no cover
        '''Return list of an artifact and its build dependencies.
        
        The artifacts are returned in depth-first order: an artifact
        is returned only after all of its dependencies.
        
        '''
        
        done = set()
        
        def depth_first(a):
            if a not in done:
                done.add(a)
                for dep in a.source.dependencies:
                    for ret in depth_first(dep):
                        yield ret
                yield a

        return list(depth_first(self))
