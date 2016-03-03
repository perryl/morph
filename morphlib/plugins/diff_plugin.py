# -*- coding: utf-8 -*-
# Copyright © 2015  Codethink Limited
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


import cliapp

from morphlib.buildcommand import BuildCommand
from morphlib.cmdline_parse_utils import (definition_lists_synopsis,
                                          parse_definition_lists)
from morphlib.morphologyfinder import MorphologyFinder
from morphlib.morphloader import MorphologyLoader
from morphlib.morphset import MorphologySet
from morphlib.util import new_repo_caches


class DiffPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'diff', self.diff,
            arg_synopsis=definition_lists_synopsis(at_least=2, at_most=2))

    def disable(self):
        pass

    def make_source_dict(self, kind, sourcepool):
            return {source.morphology['name']: source
                    for source in sourcepool
                    if source.morphology['kind'] == kind}

    def _check_for_presence_change(self, from_sources, to_sources):
        for name in to_sources:
            if name not in from_sources:
                self.app.output.write('{} was added\n'.format(name))

        for name in from_sources:
            if name not in to_sources:
                self.app.output.write('{} was removed\n'.format(name))

    def _check_for_repo_ref_changes(self, names, from_sources, to_sources):
        for name in names:
            from_source = from_sources[name]
            to_source = to_sources[name]

            if from_source.repo_name != to_source.repo_name:
                self.app.output.write(
                        '{} repo changed from {} to {}\n'.format(
                        name, from_source.repo_name, to_source.repo_name))

            if from_source.original_ref != to_source.original_ref:
                from_repo, to_repo = (self.bc.lrc.get_updated_repo(s.repo_name,
                                                                   ref=s.sha1)
                                        for s in (from_source, to_source))

                from_desc = from_repo.version_guess(from_source.sha1)
                to_desc = to_repo.version_guess(to_source.sha1)

                self.app.output.write(
                    '{} ref changed from {} to {}\n'.format(name, from_desc,
                                                            to_desc))

    def diff(self, args):
        '''Show the difference between definitions.

        When given two definition file specifiers, prints the logical
        differences between the definitions.

        '''
        # NOTE: It would be more useful to have this operate at the graphed
        #       dependency level, so you could use it to compare two different
        #       systems, and avoid duplicated logic to interpret how
        #       definitions are parsed.
        #       However at the time of writing the data model does not support:
        #       1.  Separately loading definition files from (repo, ref) and
        #           having the loaded definitions being shared between computed
        #           sources.
        #       2.  Parsing definitions for multiple systems together.
        #           This is because parameters from the parent definition (i.e.
        #           arch) are passed down to included definitions, but this is
        #           not taken into account for the lookup table, which is keyed
        #           on name, so it can't handle two chunks with the same name
        #           but different architectures.
        from_spec, to_spec = parse_definition_lists(args=args,
                                                    names=('from', 'to'))

        self.bc = BuildCommand(self.app)

        def get_systems((reponame, ref, definitions)):
            'Convert a definition path list into a list of systems'
            ml = MorphologyLoader()
            repo = self.bc.lrc.get_updated_repo(reponame, ref=ref)
            mf = MorphologyFinder(gitdir=repo, ref=ref)
            # We may have been given an empty set of definitions as input, in
            # which case we instead use every we find.
            if not definitions:
                definitions = mf.list_morphologies()
            system_paths = set()
            for definition in definitions:
                m = ml.parse_morphology_text(mf.read_file(definition),
                                             definition)
                if m.get('kind') == 'system' or 'strata' in m:
                    system_paths.add(definition)
            return reponame, ref, system_paths
        from_repo, from_ref, from_paths = get_systems(from_spec)
        to_repo, to_ref, to_paths = get_systems(to_spec)

        # This abuses Sources because they conflate the ideas of "logical
        # structure of the input of what we want to build" and the structure of
        # what the output of that would be.
        # If we were to pass the produced source pools to the artifact graphing
        # code then they would become an invalid structure of the output,
        # because the graphing code cannot handle multiple systems.
        from_sp = self.bc.create_source_pool(repo_name=from_repo, ref=from_ref,
                                        filenames=from_paths)
        to_sp = self.bc.create_source_pool(repo_name=to_repo, ref=to_ref,
                                      filenames=to_paths)

        from_by_name = {}
        to_by_name = {}
        kinds = ('stratum', 'chunk')

        for kind in kinds:
            from_by_name[kind] = self.make_source_dict(kind, from_sp)
            to_by_name[kind] = self.make_source_dict(kind, to_sp)

            self._check_for_presence_change(from_by_name[kind],
                                            to_by_name[kind])

        # Only want to compare between chunks
        # the system branches have in common
        names = (name for name in from_by_name['chunk']
                         if name in to_by_name['chunk'])

        self._check_for_repo_ref_changes(names, from_by_name['chunk'],
                                         to_by_name['chunk'])
