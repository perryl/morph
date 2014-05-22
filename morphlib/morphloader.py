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


import collections
import logging
import warnings
import yaml

import morphlib


class MorphologyObsoleteFieldWarning(UserWarning):

    def __init__(self, morphology, spec, field):
        self.kind = morphology['kind']
        self.morphology_name = morphology.get('name', '<unknown>')
        self.stratum_name = spec.get('alias', spec['morph'])
        self.field = field

    def __str__(self):
        format_string = ('%(kind)s morphology %(morphology_name)s refers to '
                         'stratum %(stratum_name)s with the %(field)s field. '
                         'Defaulting to null.')
        return format_string % self.__dict__


class MorphologySyntaxError(morphlib.Error):

    def __init__(self, morphology, errmsg):
        self.msg = 'Syntax error in morphology %s:\n%s' % (morphology, errmsg)


class NotADictionaryError(morphlib.Error):

    def __init__(self, morphology):
        self.msg = 'Not a dictionary: morphology %s' % morphology


class UnknownKindError(morphlib.Error):

    def __init__(self, kind, morphology):
        self.msg = (
            'Unknown kind %s in morphology %s' % (kind, morphology))


class MissingFieldError(morphlib.Error):

    def __init__(self, field, morphology_name):
        self.field = field
        self.morphology_name = morphology_name
        self.msg = (
            'Missing field %s from morphology %s' % (field, morphology_name))


class InvalidFieldError(morphlib.Error):

    def __init__(self, field, morphology_name):
        self.field = field
        self.morphology_name = morphology_name
        self.msg = (
            'Field %s not allowed in morphology %s' % (field, morphology_name))


class InvalidTypeError(morphlib.Error):

    def __init__(self, field, expected, actual, morphology_name):
        self.field = field
        self.expected = expected
        self.actual = actual
        self.morphology_name = morphology_name
        self.msg = (
            'Field %s expected type %s, got %s in morphology %s' %
            (field, expected, actual, morphology_name))


class ObsoleteFieldsError(morphlib.Error):

    def __init__(self, fields, morphology):
        self.msg = (
           'Morphology %s uses obsolete fields: %s' % 
           (morphology, ' '.join(fields)))

class UnknownArchitectureError(morphlib.Error):

    def __init__(self, arch, morphology):
        self.msg = (
            'Unknown architecture %s in morphology %s' % (arch, morphology))


class NoBuildDependenciesError(morphlib.Error):

    def __init__(self, stratum_name, chunk_name, morphology):
        self.msg = (
            'Stratum %s has no build dependencies for chunk %s in %s' %
                (stratum_name, chunk_name, morphology))


class NoStratumBuildDependenciesError(morphlib.Error):

    def __init__(self, stratum_name, morphology):
        self.msg = (
            'Stratum %s has no build dependencies in %s' %
                (stratum_name, morphology))


class EmptyStratumError(morphlib.Error):

    def __init__(self, stratum_name, morphology):
        self.msg = (
            'Stratum %s has no chunks in %s' %
                (stratum_name, morphology))


class DuplicateChunkError(morphlib.Error):

    def __init__(self, stratum_name, chunk_name):
        self.stratum_name = stratum_name
        self.chunk_name = chunk_name
        morphlib.Error.__init__(
            self, 'Duplicate chunk %(chunk_name)s '\
                  'in stratum %(stratum_name)s' % locals())


class EmptyRefError(morphlib.Error):

    def __init__(self, ref_location, morphology):
        self.ref_location = ref_location
        self.morphology = morphology
        morphlib.Error.__init__(
            self, 'Empty ref found for %(ref_location)s '\
                  'in %(morphology)s' % locals())


class ChunkSpecRefNotStringError(morphlib.Error):

    def __init__(self, ref_value, chunk_name, stratum_name):
        self.ref_value = ref_value
        self.chunk_name = chunk_name
        self.stratum_name = stratum_name
        morphlib.Error.__init__(
            self, 'Ref %(ref_value)s for %(chunk_name)s '\
                  'in stratum %(stratum_name)s is not a string' % locals())


class SystemStrataNotListError(morphlib.Error):

    def __init__(self, system_name, strata_type):
        self.system_name = system_name
        self.strata_type = strata_type
        typename = strata_type.__name__
        morphlib.Error.__init__(
            self, 'System %(system_name)s has the wrong type for its strata: '\
                  '%(typename)s, expected list' % locals())


class DuplicateStratumError(morphlib.Error):

    def __init__(self, system_name, stratum_name):
        self.system_name = system_name
        self.stratum_name = stratum_name
        morphlib.Error.__init__(
            self, 'Duplicate stratum %(stratum_name)s '\
                  'in system %(system_name)s' % locals())


class SystemStratumSpecsNotMappingError(morphlib.Error):

    def __init__(self, system_name, strata):
        self.system_name = system_name
        self.strata = strata
        morphlib.Error.__init__(
            self, 'System %(system_name)s has stratum specs '\
                  'that are not mappings.' % locals())


class EmptySystemError(morphlib.Error):

    def __init__(self, system_name):
        morphlib.Error.__init__(
            self, 'System %(system_name)s has no strata.' % locals())


class MultipleValidationErrors(morphlib.Error):

    def __init__(self, name, errors):
        self.name = name
        self.errors = errors
        self.msg = 'Multiple errors when validating %(name)s:'
        for error in errors:
            self.msg += ('\t' + str(error))


class DuplicateDeploymentNameError(morphlib.Error):

    def __init__(self, duplicates):
        morphlib.Error.__init__(
            self, 'Cluster morphology contains the following non-unique '
            'deployment names:\n    %s' % '\n'.join(duplicates))


class OrderedDumper(yaml.SafeDumper):
    keyorder = (
        'name',
        'kind',
        'description',
        'arch',
        'strata',
        'configuration-extensions',
        'morph',
        'repo',
        'ref',
        'unpetrify-ref',
        'build-depends',
        'build-mode',
        'artifacts',
        'max-jobs',
        'products',
        'chunks',
        'build-system',
        'pre-configure-commands',
        'configure-commands',
        'post-configure-commands',
        'pre-build-commands',
        'build-commands',
        'post-build-commands',
        'pre-install-commands',
        'install-commands',
        'post-install-commands',
        'artifact',
        'include',
        'systems',
        'deploy',
        'type',
        'location',
    )

    @classmethod
    def _iter_in_global_order(cls, mapping):
        for key in cls.keyorder:
            if key in mapping:
                yield key, mapping[key]
        for key in sorted(mapping.iterkeys()):
            if key not in cls.keyorder:
                yield key, mapping[key]

    @classmethod
    def _represent_dict(cls, dumper, mapping):
        return dumper.represent_mapping('tag:yaml.org,2002:map',
                                        cls._iter_in_global_order(mapping))

    def __init__(self, *args, **kwargs):
        yaml.SafeDumper.__init__(self, *args, **kwargs)
        self.add_representer(dict, self._represent_dict)


class MorphologyLoader(object):

    '''Load morphologies from disk, or save them back to disk.'''

    _required_fields = {
        'chunk': [
            'name',
        ],
        'stratum': [
            'name',
        ],
        'system': [
            'name',
            'arch',
            'strata',
        ],
        'cluster': [
          'name',
          'systems',
        ],
    }

    _obsolete_fields = {
        'system': [
            'system-kind',
            'disk-size',
        ],
    }

    _static_defaults = {
        'chunk': {
            'description': '',
            'pre-configure-commands': [],
            'configure-commands': [],
            'post-configure-commands': [],
            'pre-build-commands': [],
            'build-commands': [],
            'post-build-commands': [],
            'pre-test-commands': [],
            'test-commands': [],
            'post-test-commands': [],
            'pre-install-commands': [],
            'install-commands': [],
            'post-install-commands': [],
            'devices': [],
            'products': [],
            'max-jobs': None,
            'build-system': 'manual',
        },
        'stratum': {
            'chunks': [],
            'description': '',
            'build-depends': [],
            'products': [],
        },
        'system': {
            'description': '',
            'arch': None,
            'configuration-extensions': [],
        },
        'cluster': {
            'description': '',
        },
    }

    def parse_morphology_text(self, text, whence):
        '''Parse a textual morphology.

        The text may be a string, or an open file handle.

        Return the new Morphology object, or raise an error indicating
        the problem. This method does minimal validation: a syntactically
        correct morphology is fine, even if none of the fields are
        valid. It also does not set any default values for any of the
        fields. See validate and set_defaults.

        whence is where the morphology text came from. It is used
        in exception error messages.

        '''

        try:
            obj = yaml.safe_load(text)
        except yaml.error.YAMLError as e:
            raise MorphologySyntaxError(whence, e)

        if not isinstance(obj, dict):
            raise NotADictionaryError(whence)

        return morphlib.morph3.Morphology(obj)

    def load_from_string(self, string, filename='string'):
        '''Load a morphology from a string.

        Return the Morphology object.

        '''

        m = self.parse_morphology_text(string, filename)
        m.filename = filename
        self.validate(m)
        self.set_defaults(m)
        return m

    def load_from_file(self, filename):
        '''Load a morphology from a named file.

        Return the Morphology object.

        '''

        with open(filename) as f:
            text = f.read()
        return self.load_from_string(text, filename=filename)

    def save_to_string(self, morphology):
        '''Return normalised textual form of morphology.'''

        return yaml.dump(morphology.data, Dumper=OrderedDumper,
                         default_flow_style=False)

    def save_to_file(self, filename, morphology):
        '''Save a morphology object to a named file.'''

        text = self.save_to_string(morphology)
        with morphlib.savefile.SaveFile(filename, 'w') as f:
            f.write(text)

    def validate(self, morph):
        '''Validate a morphology.'''

        # Validate that the kind field is there.
        self._require_field('kind', morph)

        # The rest of the validation is dependent on the kind.

        # FIXME: move validation of clusters from morph2 to
        # here, and use morphload to load the morphology
        kind = morph['kind']
        if kind not in ('system', 'stratum', 'chunk', 'cluster'):
            raise UnknownKindError(morph['kind'], morph.filename)

        required = ['kind'] + self._required_fields[kind]
        obsolete = self._obsolete_fields.get(kind, [])
        allowed = self._static_defaults[kind].keys()
        self._require_fields(required, morph)
        self._deny_obsolete_fields(obsolete, morph)
        self._deny_unknown_fields(required + allowed, morph)

        getattr(self, '_validate_%s' % kind)(morph)

    def _validate_cluster(self, morph):
        # Deployment names must be unique within a cluster
        deployments = set()
        duplicates = set()
        for system in morph['systems']:
            sys_ids = [sys_id for sys_id, _ in system['deploy'].iteritems()]
            duplicates.update(set.intersection(set(deployments), set(sys_ids)))
            deployments.update(sys_ids)
        if duplicates:
            raise DuplicateDeploymentNameError(duplicates)

    def _validate_system(self, morph):
        # A system must contain at least one stratum
        strata = morph['strata']
        if (not isinstance(strata, collections.Iterable)
            or isinstance(strata, collections.Mapping)):

            raise SystemStrataNotListError(morph['name'],
                                           type(strata))

        if not strata:
            raise EmptySystemError(morph['name'])

        if not all(isinstance(o, collections.Mapping) for o in strata):
            raise SystemStratumSpecsNotMappingError(morph['name'], strata)

        # All stratum names should be unique within a system.
        names = set()
        for spec in strata:
            name = spec.get('alias', spec['morph'])
            if name in names:
                raise DuplicateStratumError(morph['name'], name)
            names.add(name)

        # Validate stratum spec fields
        self._validate_stratum_specs_fields(morph, 'strata')

        # We allow the ARMv7 little-endian architecture to be specified
        # as armv7 and armv7l. Normalise.
        if morph['arch'] == 'armv7':
            morph['arch'] = 'armv7l'

        # Architecture name must be known.
        if morph['arch'] not in morphlib.valid_archs:
            raise UnknownArchitectureError(morph['arch'], morph.filename)

    def _validate_stratum(self, morph):
        # Require at least one chunk.
        if len(morph.get('chunks', [])) == 0:
            raise EmptyStratumError(morph['name'], morph.filename)

        # All chunk names must be unique within a stratum.
        names = set()
        for spec in morph['chunks']:
            name = spec.get('alias', spec['name'])
            if name in names:
                raise DuplicateChunkError(morph['name'], name)
            names.add(name)

        # All chunk refs must be strings.
        for spec in morph['chunks']:
            if 'ref' in spec:
                ref = spec['ref']
                if ref == None:
                    raise EmptyRefError(
                        spec.get('alias', spec['name']), morph.filename)
                elif not isinstance(ref, basestring):
                    raise ChunkSpecRefNotStringError(
                        ref, spec.get('alias', spec['name']), morph.filename)

        # Require build-dependencies for the stratum itself, unless
        # it has chunks built in bootstrap mode.
        if 'build-depends' not in morph:
            for spec in morph['chunks']:
                if spec.get('build-mode') in ['bootstrap', 'test']:
                    break
            else:
                raise NoStratumBuildDependenciesError(
                    morph['name'], morph.filename)

        # Validate build-dependencies if specified
        self._validate_stratum_specs_fields(morph, 'build-depends')

        # Require build-dependencies for each chunk.
        for spec in morph['chunks']:
            if 'build-depends' not in spec:
                raise NoBuildDependenciesError(
                    morph['name'],
                    spec.get('alias', spec['name']),
                    morph.filename)

    @classmethod
    def _validate_chunk(cls, morphology):
        errors = []

        if 'products' in morphology:
            cls._validate_products(morphology['name'],
                                   morphology['products'], errors)

        if len(errors) == 1:
            raise errors[0]
        elif errors:
            raise MultipleValidationErrors(morphology['name'], errors)

    @classmethod
    def _validate_products(cls, morphology_name, products, errors):
        '''Validate the products field is of the correct type.'''
        if (not isinstance(products, collections.Iterable)
            or isinstance(products, collections.Mapping)):
            raise InvalidTypeError('products', list,
                                   type(products), morphology_name)

        for spec_index, spec in enumerate(products):

            if not isinstance(spec, collections.Mapping):
                e = InvalidTypeError('products[%d]' % spec_index,
                                     dict, type(spec), morphology_name)
                errors.append(e)
                continue

            cls._validate_products_spec_fields_exist(morphology_name,
                                                     spec_index, spec, errors)

            if 'include' in spec:
                cls._validate_products_specs_include(
                    morphology_name, spec_index, spec['include'], errors)

    product_spec_required_fields = ('artifact', 'include')
    @classmethod
    def _validate_products_spec_fields_exist(
        cls, morphology_name, spec_index, spec, errors):

        given_fields = sorted(spec.iterkeys())
        missing = (field for field in cls.product_spec_required_fields
                   if field not in given_fields)
        for field in missing:
            e = MissingFieldError('products[%d].%s' % (spec_index, field),
                                  morphology_name)
            errors.append(e)
        unexpected = (field for field in given_fields
                      if field not in cls.product_spec_required_fields)
        for field in unexpected:
            e = InvalidFieldError('products[%d].%s' % (spec_index, field),
                                  morphology_name)
            errors.append(e)

    @classmethod
    def _validate_products_specs_include(cls, morphology_name, spec_index,
                                         include_patterns, errors):
        '''Validate that products' include field is a list of strings.'''
        # Allow include to be most iterables, but not a mapping
        # or a string, since iter of a mapping is just the keys,
        # and the iter of a string is a 1 character length string,
        # which would also validate as an iterable of strings.
        if (not isinstance(include_patterns, collections.Iterable)
            or isinstance(include_patterns, collections.Mapping)
            or isinstance(include_patterns, basestring)):

            e = InvalidTypeError('products[%d].include' % spec_index, list,
                                 type(include_patterns), morphology_name)
            errors.append(e)
        else:
            for pattern_index, pattern in enumerate(include_patterns):
                pattern_path = ('products[%d].include[%d]' %
                                (spec_index, pattern_index))
                if not isinstance(pattern, basestring):
                    e = InvalidTypeError(pattern_path, str,
                                         type(pattern), morphology_name)
                    errors.append(e)

    @classmethod
    def _warn_obsolete_field(cls, morphology, spec, field):
        warnings.warn(MorphologyObsoleteFieldWarning(morphology, spec, field),
                      stacklevel=2)

    @classmethod
    def _validate_stratum_specs_fields(cls, morphology, specs_field):
        for spec in morphology.get(specs_field, None) or []:
            for obsolete_field in ('repo', 'ref'):
                if obsolete_field in spec:
                    cls._warn_obsolete_field(morphology, spec, obsolete_field)

    def _require_field(self, field, morphology):
        if field not in morphology:
            raise MissingFieldError(field, morphology.filename)

    def _require_fields(self, fields, morphology):
        for field in fields:
            self._require_field(field, morphology)

    def _deny_obsolete_fields(self, fields, morphology):
        obsolete_ones = [x for x in morphology if x in fields]
        if obsolete_ones:
            raise ObsoleteFieldsError(obsolete_ones, morphology.filename)

    def _deny_unknown_fields(self, allowed, morphology):
        for field in morphology:
            if field not in allowed:
                raise InvalidFieldError(field, morphology.filename)

    def set_defaults(self, morphology):
        '''Set all missing fields in the morpholoy to their defaults.

        The morphology is assumed to be valid.

        '''

        kind = morphology['kind']
        defaults = self._static_defaults[kind]
        for key in defaults:
            if key not in morphology:
                morphology[key] = defaults[key]

        getattr(self, '_set_%s_defaults' % kind)(morphology)

    def unset_defaults(self, morphology):
        '''If a field is equal to its default, delete it.

        The morphology is assumed to be valid.

        '''

        kind = morphology['kind']
        defaults = self._static_defaults[kind]
        for key in defaults:
            if key in morphology and morphology[key] == defaults[key]:
                del morphology[key]

        if kind in ('system', 'stratum', 'cluster'):
            getattr(self, '_unset_%s_defaults' % kind)(morphology)

    @classmethod
    def _set_stratum_specs_defaults(cls, morphology, specs_field):
        for spec in morphology.get(specs_field, None) or []:
            for obsolete_field in ('repo', 'ref'):
                if obsolete_field in spec:
                    del spec[obsolete_field]

    @classmethod
    def _unset_stratum_specs_defaults(cls, morphology, specs_field):
        for spec in morphology.get(specs_field, []):
            for obsolete_field in ('repo', 'ref'):
                if obsolete_field in spec:
                    del spec[obsolete_field]

    def _set_cluster_defaults(self, morph):
        for system in morph.get('systems', []):
            if 'deploy-defaults' not in system:
                system['deploy-defaults'] = {}
            if 'deploy' not in system:
                system['deploy'] = {}

    def _unset_cluster_defaults(self, morph):
        for system in morph.get('systems', []):
            if 'deploy-defaults' in system and system['deploy-defaults'] == {}:
                del system['deploy-defaults']
            if 'deploy' in system and system['deploy'] == {}:
                del system['deploy']

    def _set_system_defaults(self, morph):
        self._set_stratum_specs_defaults(morph, 'strata')

    def _unset_system_defaults(self, morph):
        self._unset_stratum_specs_defaults(morph, 'strata')

    def _set_stratum_defaults(self, morph):
        for spec in morph['chunks']:
            if 'repo' not in spec:
                spec['repo'] = spec['name']
            if 'morph' not in spec:
                spec['morph'] = spec['name']
        self._set_stratum_specs_defaults(morph, 'build-depends')

    def _unset_stratum_defaults(self, morph):
        for spec in morph['chunks']:
            if 'repo' in spec and spec['repo'] == spec['name']:
                del spec['repo']
            if 'morph' in spec and spec['morph'] == spec['name']:
                del spec['morph']
        self._unset_stratum_specs_defaults(morph, 'strata')

    def _set_chunk_defaults(self, morph):
        if morph['max-jobs'] is not None:
            morph['max-jobs'] = int(morph['max-jobs'])

