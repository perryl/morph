# Copyright (C) 2015  Codethink Limited
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


import cliapp
import jsonschema
import yaml

import os

import morphlib


class Defaults(object):
    '''Represents predefined default values specific to Baserock definitions.

    '''
    def __init__(self, definitions_version, text=None):
        self._build_systems = {}
        self._split_rules = {}

        schema_path = os.path.join(morphlib.util.schemas_directory(),
                                   'defaults.json-schema')
        with open(schema_path) as f:
            self.schema = yaml.load(f)

        if text:
            self._build_systems, self._split_rules = self._parse(text)

    def _parse(self, text):
        build_systems = {}
        split_rules = {}

        # This reports errors against <string> rather than the actual filename,
        # which is sad.
        data = yaml.safe_load(text)

        if data is None:
            # It's OK to be empty, I guess.
            return build_systems, split_rules

        try:
            # It would be nice if this could give line numbers when it spotted
            # errors. Seems tricky.
            jsonschema.validate(data, self.schema)
        except jsonschema.ValidationError as e:
            raise cliapp.AppException('Invalid DEFAULTS file: %s' % e.message)

        build_system_data = data.get('build-systems', {})
        for name, commands in build_system_data.items():
            build_system = morphlib.buildsystem.BuildSystem()
            build_system.from_dict(name, commands)
            build_systems[name] = build_system

        # It would make sense to create artifactsplitrule.SplitRule instances
        # here, instead of an unlabelled data structure. That would need some
        # changes to source.make_sources() and the 'artifactsplitrule' module.
        split_rules_data = data.get('split-rules', {})
        for kind, rules in split_rules_data.items():
            split_rules[kind] = []
            for rule in rules:
                rule_unlabelled = (rule['artifact'], rule['include'])
                split_rules[kind].append(rule_unlabelled)

        return build_systems, split_rules

    def build_systems(self):
        return self._build_systems

    def split_rules(self):
        return self._split_rules
