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


class MorphologySyntaxError(morphlib.Error):

    def __init__(self, morphology):
        self.msg = 'Syntax error in morphology %s' % morphology


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
