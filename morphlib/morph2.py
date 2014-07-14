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


import re

import morphlib
from morphlib.util import OrderedDict, json

class Morphology(object):

    '''An in-memory representation of a morphology.

    This is a parsed version of the morphology, with rules for default
    values applied. No other processing.

    '''

    static_defaults = {
        'chunk': [
            ('description', ''),
            ('pre-configure-commands', None),
            ('configure-commands', None),
            ('post-configure-commands', None),
            ('pre-build-commands', None),
            ('build-commands', None),
            ('post-build-commands', None),
            ('pre-test-commands', None),
            ('test-commands', None),
            ('post-test-commands', None),
            ('pre-install-commands', None),
            ('install-commands', None),
            ('post-install-commands', None),
            ('devices', None),
            ('products', []),
            ('max-jobs', None),
            ('build-system', 'manual')
        ],
        'stratum': [
            ('chunks', []),
            ('description', ''),
            ('build-depends', None),
        ],
        'system': [
            ('strata', []),
            ('description', ''),
            ('arch', None),
            ('configuration-extensions', []),
        ],
        'cluster': [
            ('description', ''),
        ],
    }

    @staticmethod
    def _load_json(text):
        return json.loads(text, object_pairs_hook=OrderedDict)

    @staticmethod
    def _dump_json(obj, f):
        text = json.dumps(obj, indent=4)
        text = re.sub(" \n", "\n", text)
        f.write(text)
        f.write('\n')

    def __init__(self, text):
        self._dict, self._dumper = self._load_morphology_dict(text)
        self._set_defaults()
        self._validate_children()

    def __getitem__(self, key):
        return self._dict[key]

    def __contains__(self, key):
        return key in self._dict

    # Not covered by tests, since it's trivial, morph2 is going away
    # and only exists so the new morphology validation code can use it.
    def get(self, key, default=None): # pragma: no cover
        try:
            return self[key]
        except KeyError:
            return default

    def get_commands(self, which):
        '''Return the commands to run from a morphology or the build system'''
        if self[which] is None:
            attr = '_'.join(which.split('-'))
            bs = morphlib.buildsystem.lookup_build_system(self['build-system'])
            return getattr(bs, attr)
        else:
            return self[which]

    def keys(self):
        return self._dict.keys()

    def _load_morphology_dict(self, text):
        '''Load morphology, identifying whether it is JSON or YAML'''

        try:
            data = self._load_json(text)
            dumper = self._dump_json
        except ValueError as e:  # pragma: no cover
            data = morphlib.yamlparse.load(text)
            dumper = morphlib.yamlparse.dump

        if data is None:
            raise morphlib.YAMLError("Morphology is empty")
        if type(data) not in [dict, OrderedDict]:
            raise morphlib.YAMLError("Morphology did not parse as a dict")

        return data, dumper

    def _validate_children(self):
        if self['kind'] == 'system':
            names = set()
            for info in self['strata']:
                name = info.get('alias', info['morph'])
                if name in names:
                   raise ValueError('Duplicate stratum "%s"' % name)
                names.add(name)
        elif self['kind'] == 'stratum':
            names = set()
            for info in self['chunks']:
                name = info.get('alias', info['name'])
                if name in names:
                   raise ValueError('Duplicate chunk "%s"' % name)
                names.add(name)
        elif self['kind'] == 'cluster':
             if not 'systems' in self:
                 raise KeyError('"systems" not found')
             if not self['systems']:
                 raise ValueError('"systems" is empty')
             for system in self['systems']:
                 if 'morph' not in system:
                     raise KeyError('"morph" not found')
                 if 'deploy-defaults' in system:
                     if not isinstance(system['deploy-defaults'], dict):
                         raise ValueError('deploy defaults for morph "%s" '
                                          'are not a mapping: %r'
                                          % (system['morph'],
                                             system['deploy-defaults']))
                 if 'deploy' in system:
                     for system_id, deploy_params in system['deploy'].items():
                         if not isinstance(deploy_params, dict):
                             raise ValueError('deployment parameters for '
                                              'system "%s" are not a mapping:'
                                              ' %r'
                                              % (system_id, deploy_params))

    def _set_default_value(self, target_dict, key, value):
        '''Change a value in the in-memory representation of the morphology

        Record the default value separately, so that when writing out the
        morphology we can determine whether the change from the on-disk value
        was done at load time, or later on (we want to only write back out
        the later, deliberate changes).

        '''
        target_dict[key] = value
        target_dict['_orig_' + key] = value

    def _set_defaults(self):
        if 'max-jobs' in self:
            self._set_default_value(self._dict, 'max-jobs',
                                    int(self['max-jobs']))

        for name, value in self.static_defaults[self['kind']]:
            if name not in self._dict:
                self._set_default_value(self._dict, name, value)

        if self['kind'] == 'stratum':
            self._set_stratum_defaults()
        elif self['kind'] == 'cluster':
            self._set_cluster_defaults()

    def _set_stratum_defaults(self):
        for source in self['chunks']:
            if 'repo' not in source:
                self._set_default_value(source, 'repo', source['name'])
            if 'build-depends' not in source:
                self._set_default_value(source, 'build-depends', None)
            if 'build-mode' not in source:
                self._set_default_value(source, 'build-mode', 'staging')
            if 'prefix' not in source:
                self._set_default_value(source, 'prefix', '/usr')

    def _set_cluster_defaults(self):
        if 'systems' in self and self['systems']:
            for system in self['systems']:
                if 'deploy-defaults' not in system:
                    self._set_default_value(system,
                                            'deploy-defaults',
                                            dict())
                if 'deploy' not in system:
                    self._set_default_value(system,
                                            'deploy',
                                            dict())

    def lookup_child_by_name(self, name):
        '''Find child reference by its name.

        This lookup honors aliases.

        '''

        if self['kind'] == 'system':
            for info in self['strata']:
                source_name = info.get('alias', info['morph'])
                if source_name == name:
                    return info
        elif self['kind'] == 'stratum':
            for info in self['chunks']:
                source_name = info.get('alias', info['name'])
                if source_name == name:
                    return info
        raise KeyError('"%s" not found' % name)

    def _apply_changes(self, live_dict, original_dict):
        '''Returns a new dict updated with changes from the in-memory object

        This allows us to write out a morphology including only the changes
        that were done after the morphology was loaded -- not the changes done
        to set default values during construction.

        '''
        output_dict = {}

        for key in live_dict.keys():
            if key.startswith('_orig_'):
                continue

            value = self._apply_changes_for_key(key, live_dict, original_dict)
            # VILE HACK to preserve nulls in repo/ref fields
            if value is not None or key in ('repo', 'ref'):
                output_dict[key] = value
        return output_dict

    def _apply_changes_for_key(self, key, live_dict, original_dict):
        '''Return value to write out for one key, recursing if necessary'''

        live_value = live_dict.get(key, None)
        orig_value = original_dict.get(key, None)

        if type(live_value) in [dict, OrderedDict] and orig_value is not None:
            # Recursively apply changes for dict
            result = self._apply_changes(live_value, orig_value)
        elif type(live_value) is list and orig_value is not None:
            # Recursively apply changes for list (existing, then new items).
            result = []
            for i in range(0, min(len(orig_value), len(live_value))):
                if type(live_value[i]) in [dict, OrderedDict]:
                    item = self._apply_changes(live_value[i], orig_value[i])
                else:
                    item = live_value[i]
                result.append(item)
            for i in range(len(orig_value), len(live_value)):
                if type(live_value[i]) in [dict, OrderedDict]:
                    item = self._apply_changes(live_value[i], {})
                else:
                    item = live_value[i]
                result.append(item)
        else:
            # Simple values. Use original value unless it has been changed from
            # the default in memmory.
            if live_dict[key] == live_dict.get('_orig_' + key, None):
                result = original_dict.get(key, None)
            else:
                result = live_dict[key]
        return result

    def update_text(self, text, output_fd, convert_to=None):
        '''Write out in-memory changes to loaded morphology text

        Similar in function to update_file().

        '''
        original_dict, dumper = self._load_morphology_dict(text)

        if convert_to == 'json': # pragma: no cover
            dumper = self._dump_json
        elif convert_to == 'yaml': # pragma: no cover
            dumper = morphlib.yamlparse.dump

        output_dict = self._apply_changes(self._dict, original_dict)
        dumper(output_dict, output_fd)

    def update_file(self, filename, output_fd=None, **kws): # pragma: no cover
        '''Write out in-memory changes to on-disk morphology file

        This function reads the original morphology text from 'filename', so
        that it can avoid writing out properties that are set in memory
        to their default value but weren't specified by the user at all.

        '''
        with open(filename, 'r') as f:
            text = f.read()

        with output_fd or morphlib.savefile.SaveFile(filename, 'w') as f:
            self.update_text(text, f, **kws)
