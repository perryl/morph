# distbuild/serialise.py -- (de)serialise Artifact object graphs
#
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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA..


import json

import morphlib
import logging


morphology_attributes = [
    'needs_artifact_metadata_cached',
]


def serialise_artifact(artifact):
    '''Serialise an Artifact object and its dependencies into string form.'''

    def encode_morphology(morphology):
        result = {}
        for key in morphology.keys():
            result[key] = morphology[key]
        for x in morphology_attributes:
            result['__%s' % x] = getattr(morphology, x)
        return result
    
    def encode_source(source):
        source_dic = {
            'repo': None,
            'repo_name': source.repo_name,
            'original_ref': source.original_ref,
            'sha1': source.sha1,
            'tree': source.tree,
            'morphology': encode_morphology(source.morphology),
            'filename': source.filename,

            # dict keys are converted to strings by json
            # so we encode the artifact ids as strings
            'artifact_ids': [str(id(artifact)) for (_, artifact)
                in source.artifacts.iteritems()],
        }

        if source.morphology['kind'] == 'chunk':
            source_dic['build_mode'] = source.build_mode
            source_dic['prefix'] = source.prefix
        return source_dic

    def encode_single_artifact(a, artifacts, source_id):
        if artifact.source.morphology['kind'] == 'system':
            arch = artifact.source.morphology['arch']
        else:
            arch = artifact.arch

        return {
            'source_id': source_id,
            'name': a.name,
            'cache_id': a.cache_id,
            'cache_key': a.cache_key,
            'dependencies': [str(id(artifacts[id(d)]))
                for d in a.dependencies],
            'arch': arch
        }

    visited = set()
    def traverse(a):
        visited.add(a)
        for dep in a.dependencies:
            if dep in visited:
                continue
            for ret in traverse(dep):
                yield ret
        yield a
    

    artifacts = {}
    encoded_artifacts = {}
    encoded_sources = {}

    for a in traverse(artifact):
        if id(a.source) not in encoded_sources:
            if a.source.morphology['kind'] == 'chunk':
                for (_, sa) in a.source.artifacts.iteritems():
                    if id(sa) not in artifacts:
                        artifacts[id(sa)] = sa
                        encoded_artifacts[id(sa)] = encode_single_artifact(sa,
                            artifacts, id(a.source))
            else:
                # We create separate sources for strata and systems,
                # this is a bit of a hack, but needed to allow
                # us to build strata and systems independently

                s = a.source
                t = morphlib.source.Source(s.repo_name, s.original_ref,
                    s.sha1, s.tree, s.morphology, s.filename)

                t.artifacts = {a.name: a}
                a.source = t

            encoded_sources[id(a.source)] = encode_source(a.source)

        if id(a) not in artifacts:
            artifacts[id(a)] = a
            encoded_artifacts[id(a)] = encode_single_artifact(a, artifacts,
                id(a.source))

    encoded_artifacts['_root'] = str(id(artifact))

    return json.dumps({'sources': encoded_sources,
        'artifacts': encoded_artifacts})


def deserialise_artifact(encoded):
    '''Re-construct the Artifact object (and dependencies).
    
    The argument should be a string returned by ``serialise_artifact``.
    The reconstructed Artifact objects will be sufficiently like the
    originals that they can be used as a build graph, and other such
    purposes, by Morph.
    
    '''

    def unserialise_morphology(le_dict):
        '''Convert a dict into something that kinda acts like a Morphology.
        
        As it happens, we don't need the full Morphology so we cheat.
        Cheating is good.
        
        '''
        
        class FakeMorphology(dict):
        
            def get_commands(self, which):
                '''Get commands to run from a morphology or build system'''
                if self[which] is None:
                    attr = '_'.join(which.split('-'))
                    bs = morphlib.buildsystem.lookup_build_system(
                            self['build-system'])
                    return getattr(bs, attr)
                else:
                    return self[which]

        morphology = FakeMorphology(le_dict)
        for x in morphology_attributes:
            setattr(morphology, x, le_dict['__%s' % x])
            del morphology['__%s' % x]
        return morphology

    def unserialise_source_artifacts(source, artifacts_dict):
        '''Convert this dict into a list of artifacts'''
        return {a['name']: Artifact(source,
            a['name'],
            a['cache_id'],
            a['cache_key'],
            a['dependencies'],
            a['dependents'],
            a['metadata_version']) for a in artifacts_dict}

    def unserialise_source(le_dict):
        '''Convert a dict into a Source object.'''

        morphology = unserialise_morphology(le_dict['morphology'])
        source = morphlib.source.Source(le_dict['repo_name'],
                                        le_dict['original_ref'],
                                        le_dict['sha1'],
                                        le_dict['tree'],
                                        morphology,
                                        le_dict['filename'])

        if morphology['kind'] == 'chunk':
            source.build_mode = le_dict['build_mode']
            source.prefix = le_dict['prefix']
        return source
        
    def unserialise_single_artifact(artifact_dict, source):
        '''Convert dict into an Artifact object.
        
        Do not set dependencies, that will be dealt with later.
        
        '''

        artifact = morphlib.artifact.Artifact(source, artifact_dict['name'])
        artifact.cache_id = artifact_dict['cache_id']
        artifact.cache_key = artifact_dict['cache_key']
        artifact.arch = artifact_dict['arch']
        artifact.source = source

        return artifact

    le_dicts = json.loads(encoded)
    artifacts_dict = le_dicts['artifacts']
    sources_dict = le_dicts['sources']

    artifact_ids = ([artifacts_dict['_root']] +
        filter(lambda k: k != '_root', artifacts_dict.keys()))

    source_ids = [sid for sid in sources_dict.keys()]

    artifacts = {}
    sources = {}

    for source_id in source_ids:
        source_dict = sources_dict[source_id]
        sources[source_id] = unserialise_source(source_dict)

        # clear the source artifacts that get automatically generated
        # we want to add the ones that were sent to us
        sources[source_id].artifacts = {}
        source_artifacts = source_dict['artifact_ids']

        for artifact_id in source_artifacts:
            if artifact_id not in artifacts:
                artifact_dict = artifacts_dict[artifact_id]
                artifact = unserialise_single_artifact(artifact_dict,
                    sources[source_id])

                artifacts[artifact_id] = artifact

            key = artifacts[artifact_id].name
            sources[source_id].artifacts[key] = artifacts[artifact_id]

    # now add the dependencies
    for artifact_id in artifact_ids:
        artifact = artifacts[artifact_id]
        artifact.dependencies = [artifacts[aid] for aid in
            artifacts_dict[artifact_id]['dependencies']]

    return artifacts[artifacts_dict['_root']]
