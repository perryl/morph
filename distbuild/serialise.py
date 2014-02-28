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

    def encode_artifact(artifact):
        artifact_dic = {
            # source? - that will be constructed during deserialisation
            'name': artifact.name,
            'cache_id': artifact.cache_id,
            'cache_key': artifact.cache_key,
            'dependencies': artifact.dependencies,
            'dependents': artifact.dependents,
            'metadata_version': artifact.metadata_version,
        }

    def encode_artifacts(artifacts):
        return {name: encode_artifact(artifact) 
            for (name, artifact) in artifacts.iteritems()}
    
    def encode_source(source):
        source_dic = {
            'repo': None,
            'repo_name': source.repo_name,
            'original_ref': source.original_ref,
            'sha1': source.sha1,
            'tree': source.tree,
            'morphology': encode_morphology(source.morphology),
            'filename': source.filename,
            'artifacts': encode_artifacts(source.artifacts),
        }
        if source.morphology['kind'] == 'chunk':
            source_dic['build_mode'] = source.build_mode
            source_dic['prefix'] = source.prefix
        return source_dic

    def encode_single_artifact(a, encoded):
        if artifact.source.morphology['kind'] == 'system':
            arch = artifact.source.morphology['arch']
        else:
            arch = artifact.arch
        return {
            'source': encode_source(a.source),
            'name': a.name,
            'cache_id': a.cache_id,
            'cache_key': a.cache_key,
            'dependencies': [encoded[d.cache_key]['cache_key']
                             for d in a.dependencies],
            'arch': arch,
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
    
    encoded = {}
    for a in traverse(artifact):
        if a.cache_key not in encoded:
            encoded[a.cache_key] = encode_single_artifact(a, encoded)

    encoded['_root'] = artifact.cache_key

    logging.debug('in serialise_artifact(): encoded: %s' %
        json.dumps(encoded))

    return json.dumps(encoded)


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

        source.artifacts = unserialise_source_artifacts(source,
            le_dict['artifacts'])

        if morphology['kind'] == 'chunk':
            source.build_mode = le_dict['build_mode']
            source.prefix = le_dict['prefix']
        return source
        
    def unserialise_single_artifact(le_dict):
        '''Convert dict into an Artifact object.
        
        Do not set dependencies, that will be dealt with later.
        
        '''

        source = unserialise_source(le_dict['source'])
        artifact = morphlib.artifact.Artifact(source, le_dict['name'])
        artifact.cache_id = le_dict['cache_id']
        artifact.cache_key = le_dict['cache_key']
        artifact.arch = le_dict['arch']
        return artifact

    logging.debug('in deserialise_artifact() encoded: %s' % encoded)

    with open('/tmp/%s', 'w') as f:
        f.write(encoded)

    le_dicts = json.loads(encoded)
    cache_keys = [k for k in le_dicts.keys() if k != '_root']
    artifacts = {}
    for cache_key in cache_keys:
        le_dict = le_dicts[cache_key]
        artifacts[cache_key] = unserialise_single_artifact(le_dict)
    for cache_key in cache_keys:
        le_dict = le_dicts[cache_key]
        artifact = artifacts[cache_key]
        artifact.dependencies = [artifacts[k] for k in le_dict['dependencies']]

    thing = artifacts[le_dicts['_root']]
    logging.debug('thing.basename(): %s' % thing.basename())

    return artifacts[le_dicts['_root']]

