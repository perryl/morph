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


import cliapp
import collections
import logging

import morphlib


class MutualDependencyError(cliapp.AppException):

    def __init__(self, a, b):
        cliapp.AppException.__init__(
            self, 'Cyclic dependency between %s and %s detected' % (a, b))


class DependencyOrderError(cliapp.AppException):

    def __init__(self, stratum_source, chunk, dependency_name):
        cliapp.AppException.__init__(
            self, 'In stratum %s, chunk %s references its dependency %s '
            'before it is defined' %
            (stratum_source, chunk, dependency_name))


class ArtifactResolver(object):

    '''Resolves sources into artifacts that would be build from the sources.

    This class takes a CacheKeyComputer and a SourcePool, analyses the
    sources and their dependencies and creates a list of artifacts
    (represented by Artifact objects) that are involved in building the
    sources in the pool.

    '''

    def __init__(self):
        self._added_artifacts = None
        self._source_pool = None

    def resolve_root_artifacts(self, source_pool): #pragma: no cover
        return [a for a in self._resolve_artifacts(source_pool)
                if not a.dependents]

    def _resolve_artifacts(self, source_pool):
        self._source_pool = source_pool
        self._added_artifacts = set()

        artifacts = self._resolve_artifacts_recursively()
        # TODO perform cycle detection, e.g. based on:
        # http://stackoverflow.com/questions/546655/finding-all-cycles-in-graph
        return artifacts

    def _resolve_artifacts_recursively(self):
        artifacts = []

        queue = self._create_initial_queue()
        while queue:
            source = queue.popleft()

            if source.morphology['kind'] == 'system': # pragma: no cover
                systems = [source.artifacts[name]
                           for name in source.split_rules.artifacts]

                for system in (s for s in systems
                               if s not in self._added_artifacts):
                    artifacts.append(system)
                    self._added_artifacts.add(system)

                resolved_artifacts = self._resolve_system_dependencies(
                    systems, source)

                for artifact in resolved_artifacts:
                    if not artifact in self._added_artifacts:
                        artifacts.append(artifact)
                        self._added_artifacts.add(artifact)
            elif source.morphology['kind'] == 'stratum':
                # Iterate split_rules.artifacts, rather than
                # artifacts.values() to preserve ordering
                strata = [source.artifacts[name]
                          for name in source.split_rules.artifacts
                          if name in source.artifacts]

                # If we were not given systems, return the strata here,
                # rather than have the systems return them.
                if not any(s.morphology['kind'] == 'system'
                           for s in self._source_pool):
                    for stratum in (s for s in strata
                                    if s not in self._added_artifacts):
                        artifacts.append(stratum)
                        self._added_artifacts.add(stratum)

                resolved_artifacts = self._resolve_stratum_dependencies(
                    strata, source)

                for artifact in resolved_artifacts:
                    if not artifact in self._added_artifacts:
                        artifacts.append(artifact)
                        self._added_artifacts.add(artifact)
            elif source.morphology['kind'] == 'chunk':
                chunks = [source.artifacts[name]
                          for name in source.split_rules.artifacts]
                # If we were only given chunks, return them here, rather than
                # have the strata return them.
                if not any(s.morphology['kind'] == 'stratum'
                           for s in self._source_pool):
                    for chunk in (c for c in chunks
                                  if c not in self._added_artifacts):
                        artifacts.append(chunk)
                        self._added_artifacts.add(chunk)

        return artifacts

    def _create_initial_queue(self):
        return collections.deque(self._source_pool)

    def _resolve_system_dependencies(self, systems, source): # pragma: no cover
        artifacts = []

        for info in source.morphology['strata']:
            for stratum_source in self._source_pool.lookup(
                info.get('repo') or source.repo_name,
                info.get('ref') or source.original_ref,
                morphlib.util.sanitise_morphology_path(info['morph'])):

                stratum_morph_name = stratum_source.morphology['name']

                matches, overlaps, unmatched = source.split_rules.partition(
                        ((stratum_morph_name, sta_name) for sta_name
                         in stratum_source.split_rules.artifacts))
                for system in systems:
                    for (stratum_name, sta_name) in matches[system.name]:
                        if sta_name in stratum_source.artifacts:
                            stratum_artifact = \
                                stratum_source.artifacts[sta_name]
                            source.add_dependency(stratum_artifact)
                            artifacts.append(stratum_artifact)

        return artifacts

    def _resolve_stratum_dependencies(self, strata, source):
        artifacts = []

        stratum_build_depends = []

        for stratum_info in source.morphology.get('build-depends') or []:
            for other_source in self._source_pool.lookup(
                stratum_info.get('repo') or source.repo_name,
                stratum_info.get('ref') or source.original_ref,
                morphlib.util.sanitise_morphology_path(stratum_info['morph'])):

                # Make every stratum artifact this stratum source produces
                # depend on every stratum artifact the other stratum source
                # produces.
                for sta_name in other_source.split_rules.artifacts:
                    # Strata have split rules for artifacts they don't build,
                    # since they need to know to yield a match to its sibling
                    if sta_name not in other_source.artifacts:
                        continue
                    other_stratum = other_source.artifacts[sta_name]

                    stratum_build_depends.append(other_stratum)

                    artifacts.append(other_stratum)

                    for stratum in strata:
                        if other_source.depends_on(stratum):
                            raise MutualDependencyError(stratum, other_stratum)

                        source.add_dependency(other_stratum)

        # 'name' here is the chunk artifact name
        name_to_processed_artifacts = {}

        for info in source.morphology['chunks']:
            filename = morphlib.util.sanitise_morphology_path(
                info.get('morph', info['name']))
            chunk_source = self._source_pool.lookup(
                info['repo'],
                info['ref'],
                filename)[0]

            chunk_name = chunk_source.name

            # Resolve now to avoid a search for the parent morphology later
            chunk_source.build_mode = info['build-mode']
            chunk_source.prefix = info['prefix']

            build_depends = info.get('build-depends', None)

            # Add our stratum's build depends as dependencies of this chunk
            for other_stratum in stratum_build_depends:
                chunk_source.add_dependency(other_stratum)

            # Add dependencies between chunks mentioned in this stratum
            for name in build_depends: # pragma: no cover
                if name not in name_to_processed_artifacts:
                    raise DependencyOrderError(
                        source, info['name'], name)
                other_artifacts = name_to_processed_artifacts[name]
                for other_artifact in other_artifacts:
                    chunk_source.add_dependency(other_artifact)

            # Add build dependencies between our stratum's artifacts
            # and the chunk artifacts produced by this stratum.
            matches, overlaps, unmatched = source.split_rules.partition(
                    ((chunk_name, ca_name) for ca_name
                     in chunk_source.split_rules.artifacts))
            for (chunk_name, ca_name) in matches[source.name]:
                chunk_artifact = chunk_source.artifacts[ca_name]
                source.add_dependency(chunk_artifact)
                # Only return chunks required to build strata we need
                if chunk_artifact not in artifacts:
                    artifacts.append(chunk_artifact)


            # Add these chunks to the processed artifacts, so other
            # chunks may refer to them.
            name_to_processed_artifacts[info['name']] = \
                [chunk_source.artifacts[n] for n
                 in chunk_source.split_rules.artifacts]

        return artifacts
