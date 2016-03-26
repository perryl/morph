# Copyright (C) 2015-2016  Codethink Limited
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
#
# =*= License: GPL-2 =*=


'''Functions for dealing with the definitions VERSION marker file.'''


import cliapp
import yaml

import morphlib


SUPPORTED_VERSIONS = [7, 8]


class DefinitionsVersionError(cliapp.AppException):
    pass


class UnknownVersionError(DefinitionsVersionError):  # pragma: no cover
    def __init__(self, version):
        DefinitionsVersionError.__init__(
            self, "Definitions format version %s is not supported" % version)


class InvalidVersionFileError(DefinitionsVersionError):  # pragma: no cover
    def __init__(self, text):
        DefinitionsVersionError.__init__(
            self, "invalid VERSION file: '%s'" % text)


def parse_version_file(version_text):
    '''Parse VERSION file and return the version of the format if:

    VERSION is a YAML file
    and it's a dict
    and has the key 'version'
    and the type stored in the 'version' key is an int

    otherwise returns None

    '''
    yaml_obj = yaml.safe_load(version_text)

    return (yaml_obj['version'] if yaml_obj is not None
                                and isinstance(yaml_obj, dict)
                                and 'version' in yaml_obj
                                and isinstance(yaml_obj['version'], int)

                                else None)


def check_version_file(version_text):  # pragma: no cover
    '''Check the VERSION information is valid and is a supported version.'''

    if version_text == None:
        raise InvalidVersionFileError()

    version = morphlib.definitions_version.parse_version_file(version_text)

    if version == None:
        raise InvalidVersionFileError(version_text)

    if version not in SUPPORTED_VERSIONS:
        raise UnknownVersionError(version)

    return version
