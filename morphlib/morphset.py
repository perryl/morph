# Copyright (C) 2013-2014  Codethink Limited
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
#
# =*= License: GPL-2 =*=


import morphlib


class StratumNotInSystemError(morphlib.Error):

    def __init__(self, system_name, stratum_name):
        self.msg = (
            'System %s does not contain %s' % (system_name, stratum_name))


class StratumNotInSetError(morphlib.Error):

    def __init__(self, stratum_name):
        self.msg = 'Stratum %s is not in MorphologySet' % stratum_name


class ChunkNotInStratumError(morphlib.Error):

    def __init__(self, stratum_name, chunk_name):
        self.msg = (
            'Stratum %s does not contain %s' % (stratum_name, chunk_name))


class MorphologySet(object):

    '''Store and manipulate a set of Morphology objects.'''

    def __init__(self):
        self.morphologies = []

    def add_morphology(self, morphology):
        '''Add a morphology object to the set, unless it's there already.'''

        triplet = (
            morphology.repo_url,
            morphology.ref,
            morphology.filename
        )
        for existing in self.morphologies:
            existing_triplet = (
                existing.repo_url,
                existing.ref,
                existing.filename
            )
            if existing_triplet == triplet:
                return

        self.morphologies.append(morphology)

    def has(self, repo_url, ref, filename):
        '''Does the set have a morphology for the given triplet?'''
        return self._get_morphology(repo_url, ref, filename) is not None

    def _get_morphology(self, repo_url, ref, filename):
        for m in self.morphologies:
            if (m.repo_url == repo_url and
                m.ref == ref and
                m.filename == filename):
                return m
        return None

    def _find_spec(self, specs, wanted_name):
        for spec in specs:
            name = spec.get('morph', spec.get('name'))
            if name == wanted_name:
                return spec.get('repo'), spec.get('ref'), name
        return None, None, None

    def get_stratum_in_system(self, system_morph, stratum_name):
        '''Return morphology for a stratum that is in a system.

        If the stratum is not in the system, raise StratumNotInSystemError.
        If the stratum morphology has not been added to the set,
        raise StratumNotInSetError.

        '''

        repo_url, ref, morph = self._find_spec(
            system_morph['strata'], stratum_name)
        if (repo_url, ref, morph) == (None, None, None):
            raise StratumNotInSystemError(system_morph['name'], stratum_name)
        m = self._get_morphology(repo_url or system_morph.repo_url,
                                 ref or system_morph.ref,
                                 '%s.morph' % morph)
        if m is None:
            raise StratumNotInSetError(stratum_name)
        return m

    def get_chunk_triplet(self, stratum_morph, chunk_name):
        '''Return the repo url, ref, morph name triplet for a chunk.

        Given a stratum morphology, find the triplet used to refer to
        a given chunk. Note that because of how the chunk may be
        referred to using either name or morph fields in the morphology,
        the morph field (or its computed value) is always returned.
        Note also that the morph field, not the filename, is returned.

        Raise ChunkNotInStratumError if the chunk is not found in the
        stratum.

        '''

        repo_url, ref, morph = self._find_spec(
            stratum_morph['chunks'], chunk_name)
        if (repo_url, ref, morph) == (None, None, None):
            raise ChunkNotInStratumError(stratum_morph['name'], chunk_name)
        return repo_url, ref, morph

    def traverse_specs(self, cb_process, cb_filter=lambda s: True):
        '''Higher-order function for processing every spec.
        
        This traverses every spec in all the morphologies, so all chunk,
        stratum and stratum-build-depend specs are visited.

        It is to be passed one or two callbacks. `cb_process` is given
        a spec, which it may alter, but if it does, it must return True.

        `cb_filter` is given the morphology, the kind of spec it is
        working on in addition to the spec itself.

        `cb_filter` is expected to decide whether to run `cb_process`
        on the spec.

        Arguably this could be checked in `cb_process`, but it can be less
        logic over all since `cb_process` need not conditionally return.

        If any specs have been altered, at the end of iteration, any
        morphologies in the MorphologySet that are referred to by an
        altered spec are also changed.

        This requires a full iteration of the MorphologySet, so it is not a
        cheap operation.

        A coroutine was attempted, but it required the same amount of
        code at the call site as doing it by hand.
        
        '''

        altered_references = {}

        def process_spec_list(m, kind):
            specs = m[kind]
            for spec in specs:
                if cb_filter(m, kind, spec):
                    orig_spec = (spec.get('repo'), spec.get('ref'),
                                 spec['morph'])
                    dirtied = cb_process(m, kind, spec)
                    if dirtied:
                        m.dirty = True
                        altered_references[orig_spec] = spec

        for m in self.morphologies:
            if m['kind'] == 'system':
                process_spec_list(m, 'strata')
            elif m['kind'] == 'stratum':
                process_spec_list(m, 'build-depends')
                process_spec_list(m, 'chunks')

        for m in self.morphologies:
            tup = (m.repo_url, m.ref, m.filename[:-len('.morph')])
            if tup in altered_references:
                spec = altered_references[tup]
                if m.ref != spec.get('ref'):
                    m.ref = spec.get('ref')
                    m.dirty = True
                assert (m.filename == spec['morph'] + '.morph'
                        or m.repo_url == spec.get('repo')), \
                       'Moving morphologies is not supported.'

    def change_ref(self, repo_url, orig_ref, morph_filename, new_ref):
        '''Change a triplet's ref to a new one in all morphologies in a ref.

        Change orig_ref to new_ref in any morphology that references the
        original triplet. This includes stratum build-dependencies.

        '''

        def wanted_spec(m, kind, spec):
            return (spec.get('repo') == repo_url and
                    spec.get('ref') == orig_ref and
                    spec['morph'] + '.morph' == morph_filename)

        def process_spec(m, kind, spec):
            spec['unpetrify-ref'] = spec.get('ref')
            spec['ref'] = new_ref
            return True

        self.traverse_specs(process_spec, wanted_spec)

    def list_refs(self):
        '''Return a set of all the (repo, ref) pairs in the MorphologySet.

        This does not dirty the morphologies so they do not need to be
        written back to the disk.

        '''
        known = set()

        def wanted_spec(m, kind, spec):
            return (spec.get('repo'), spec.get('ref')) not in known

        def process_spec(m, kind, spec):
            known.add((spec.get('repo'), spec.get('ref')))
            return False

        self.traverse_specs(process_spec, wanted_spec)

        return known

    def repoint_refs(self, repo_url, new_ref):
        '''Change all specs which refer to (repo, *) to (repo, new_ref).
        
        This is stunningly similar to change_ref, with the exception of
        ignoring the morphology name and ref fields.

        It is intended to be used before chunks are petrified

        '''
        def wanted_spec(m, kind, spec):
            return spec.get('repo') == repo_url

        def process_spec(m, kind, spec):
            if 'unpetrify-ref' not in spec:
                spec['unpetrify-ref'] = spec.get('ref')
            spec['ref'] = new_ref
            return True

        self.traverse_specs(process_spec, wanted_spec)

    def petrify_chunks(self, resolutions):
        '''Update _every_ chunk's ref to the value resolved in resolutions.

        `resolutions` must be a {(repo, ref): resolved_ref}

        This is subtly different to change_ref, since that works on
        changing a single spec including its filename, and the morphology
        those specs refer to, while petrify_chunks is interested in changing
        _all_ the refs.

        '''

        def wanted_chunk_spec(m, kind, spec):
            # Do not attempt to petrify non-chunk specs.
            # This is not handled by previous implementations, and
            # the details are tricky.
            if not (m['kind'] == 'stratum' and kind == 'chunks'):
                return
            ref = spec.get('ref')
            return (not morphlib.git.is_valid_sha1(ref)
                    and (spec.get('repo'), ref) in resolutions)

        def process_chunk_spec(m, kind, spec):
            tup = (spec.get('repo'), spec.get('ref'))
            spec['unpetrify-ref'] = spec.get('ref')
            spec['ref'] = resolutions[tup]
            return True

        self.traverse_specs(process_chunk_spec, wanted_chunk_spec)

    def unpetrify_all(self):
        '''If a spec is petrified, unpetrify it.

        '''

        def wanted_spec(m, kind, spec):
            return ('unpetrify-ref' in spec and
                    morphlib.git.is_valid_sha1(spec.get('ref')))
        def process_spec(m, kind, spec):
            spec['ref'] = spec.pop('unpetrify-ref')
            return True

        self.traverse_specs(process_spec, wanted_spec)
