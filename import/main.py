#!/usr/bin/python
# Import foreign packaging systems into Baserock
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
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import cliapp
import morphlib
import networkx

import contextlib
import copy
import json
import logging
import os
import time

from logging import debug


@contextlib.contextmanager
def cwd(path):
    old_cwd = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old_cwd)


class LorrySet(object):
    '''Manages a set of .lorry files.

    The structure of .lorry files makes the code a little more confusing than
    I would like. A lorry "entry" is a dict of one entry mapping name to info.
    A lorry "file" is a dict of one or more of these entries merged together.
    If it were a list of entries with 'name' fields, the code would be neater.

    '''
    def __init__(self, lorries_path):
        self.path = lorries_path

        if os.path.exists(lorries_path):
            self.data = self.parse_all_lorries()
        else:
            os.makedirs(lorries_path)
            self.data = {}

    def all_lorry_files(self):
        for dirpath, dirnames, filenames in os.walk(self.path):
            for filename in filenames:
                if filename.endswith('.lorry'):
                    yield os.path.join(dirpath, filename)

    def parse_all_lorries(self):
        lorry_set = {}
        for lorry_file in self.all_lorry_files():
            with open(lorry_file, 'r') as f:
                lorry = json.load(f)

            lorry_items = lorry.items()

            for key, value in lorry_items:
                if key in lorry_set:
                    raise Exception(
                        '%s: duplicates existing lorry %s' % (lorry_file, key))

            lorry_set.update(lorry_items)

        return lorry_set

    def get_lorry(self, name):
        return {name: self.data[name]}

    def find_lorry_for_package(self, kind, package_name):
        key = 'x-products-%s' % kind
        for name, lorry in self.data.iteritems():
            products = lorry.get(key, [])
            for entry in products:
                if entry == package_name:
                    return {name: lorry}

        return None

    def _check_for_conflicts_in_standard_fields(self, existing, new):
        '''Ensure that two lorries for the same project do actually match.'''
        for field, value in existing.iteritems():
            if field.startswith('x-'):
                continue
            if field == 'url':
                # FIXME: need a much better way of detecting whether the URLs
                # are equivalent ... right now HTTP vs. HTTPS will cause an
                # error, for example!
                matches = (value.rstrip('/') == new[field].rstrip('/'))
            else:
                matches = (value == new[field])
            if not matches:
                raise Exception(
                    'Lorry %s conflicts with existing entry %s at field %s' %
                    (new, existing, field))

    def _merge_products_fields(self, existing, new):
        '''Merge the x-products- fields from new lorry into an existing one.'''
        is_product_field = lambda x: x.startswith('x-products-')

        existing_fields = [f for f in existing.iterkeys() if
                           is_product_field(f)]
        new_fields = [f for f in new.iterkeys() if f not in existing_fields and
                      is_product_field(f)]

        for field in existing_fields:
            existing[field].extend(new[field])
            existing[field] = list(set(existing[field]))

        for field in new_fields:
            existing[field] = new[field]

    def add(self, filename, lorry_entry):
        logging.debug('Adding %s to lorryset', filename)

        filename = os.path.join(self.path, '%s.lorry' % filename)

        assert len(lorry_entry) == 1

        project_name = lorry_entry.keys()[0]
        info = lorry_entry.values()[0]

        if len(project_name) == 0:
            raise cliapp.AppException(
                'Invalid lorry %s: %s' % (filename, lorry_entry))

        if project_name in self.data:
            stored_lorry = self.get_lorry(project_name)

            self._check_for_conflicts_in_standard_fields(
                stored_lorry[project_name], lorry_entry[project_name])
            self._merge_products_fields(
                stored_lorry[project_name], lorry_entry[project_name])
            lorry_entry = stored_lorry
        else:
            self.data[project_name] = info

        with morphlib.savefile.SaveFile(filename, 'w') as f:
            json.dump(lorry_entry, f, indent=4)


# FIXME: this tool extends the morphology format to store
# packaging-system-specific dependency information. Here is a hack to make that
# work. Long term, we must either make 'dependency' field an official thing, or
# communicate the dependency information in a separate way (which would be a
# bit more code than this, I think).
class MorphologyLoader(morphlib.morphloader.MorphologyLoader):
    pass
MorphologyLoader._static_defaults['chunk']['x-build-dependencies-rubygems'] = []
MorphologyLoader._static_defaults['chunk']['x-runtime-dependencies-rubygems'] = []


class MorphologySet(morphlib.morphset.MorphologySet):
    def __init__(self, path):
        super(MorphologySet, self).__init__()

        self.path = path
        self.loader = MorphologyLoader()

        if os.path.exists(path):
            self.load_all_morphologies()
        else:
            os.makedirs(path)

    def load_all_morphologies(self):
        logging.info('Loading all .morph files under %s', self.path)

        class FakeGitDir(morphlib.gitdir.GitDirectory):
            '''Ugh

            This is here because the default constructor will search up the
            directory heirarchy until it finds a '.git' directory, but that
            may be totally the wrong place for our purpose: we don't have a
            Git directory at all.

            '''
            def __init__(self, path):
                self.dirname = path
                self._config = {}

        gitdir = FakeGitDir(self.path)
        finder = morphlib.morphologyfinder.MorphologyFinder(gitdir)
        loader = MorphologyLoader()
        for filename in (f for f in finder.list_morphologies()
                         if not gitdir.is_symlink(f)):
            text = finder.read_morphology(filename)
            morph = loader.load_from_string(text, filename=filename)
            morph.repo_url = None  # self.root_repository_url
            morph.ref = None  # self.system_branch_name
            self.add_morphology(morph)

    def get_morphology(self, repo_url, ref, filename):
        return self._get_morphology(repo_url, ref, filename)

    def save_morphology(self, filename, morphology):
        self.add_morphology(morphology)
        morphology_to_save = copy.copy(morphology)
        self.loader.unset_defaults(morphology_to_save)
        filename = os.path.join(self.path, filename)
        self.loader.save_to_file(filename, morphology_to_save)


class GitDirectory(morphlib.gitdir.GitDirectory):
    def has_ref(self, ref):
        try:
            self._rev_parse(ref)
            return True
        except morphlib.gitdir.InvalidRefError:
            return False


class BaserockImportException(cliapp.AppException):
    pass


class Package(object):
    '''A package in the processing queue.

    In order to provide helpful errors, this item keeps track of what
    packages depend on it, and hence of why it was added to the queue.

    '''
    def __init__(self, name, version):
        self.name = name
        self.version = version
        self.required_by = []
        self.morphology = None
        self.is_build_dep = False
        self.version_in_use = version

    def __cmp__(self, other):
        return cmp(self.name, other.name)

    def __repr__(self):
        return '<Package %s-%s>' % (self.name, self.version)

    def __str__(self):
        if len(self.required_by) > 0:
            required_msg = ', '.join(self.required_by)
            required_msg = ', required by: ' + required_msg
        else:
            required_msg = ''
        return '%s-%s%s' % (self.name, self.version, required_msg)

    def add_required_by(self, item):
        self.required_by.append('%s-%s' % (item.name, item.version))

    def match(self, name, version):
        return (self.name==name and self.version==version)

    def set_morphology(self, morphology):
        self.morphology = morphology

    def set_is_build_dep(self, is_build_dep):
        self.is_build_dep = is_build_dep

    def set_version_in_use(self, version_in_use):
        self.version_in_use = version_in_use


def find(iterable, match):
    return next((x for x in iterable if match(x)), None)


class BaserockImportApplication(cliapp.Application):
    def add_settings(self):
        self.settings.string(['lorries-dir'],
                             'location for Lorry files',
                             metavar='PATH',
                             default=os.path.abspath('./lorries'))
        self.settings.string(['definitions-dir'],
                             'location for morphology files',
                             metavar='PATH',
                             default=os.path.abspath('./definitions'))
        self.settings.string(['checkouts-dir'],
                             'location for Git checkouts',
                             metavar='PATH',
                             default=os.path.abspath('./checkouts'))

    def setup(self):
        self.add_subcommand('rubygems', self.import_rubygems,
                            arg_synopsis='GEM_NAME')

    def setup_logging_formatter_for_file(self):
        # You need recent cliapp for this to work, with commit "Split logging
        # setup into further overrideable methods".
        return logging.Formatter("main: %(levelname)s: %(message)s")

    def setup_logging_for_import_plugins(self):
        log = self.settings['log']

        if log == '/dev/stdout':
            # The plugins output results on /dev/stdout, logs would interfere
            debug('Redirecting import plugin logs to /dev/stderr')
            log = '/dev/stderr'

        os.environ['BASEROCK_IMPORT_LOG'] = log
        os.environ['BASEROCK_IMPORT_LOG_LEVEL'] = self.settings['log-level']

    def process_args(self, args):
        if len(args) == 0:
            # Cliapp default is to just say "ERROR: must give subcommand" if
            # no args are passed, I prefer this.
            args = ['help']

        self.setup_logging_for_import_plugins()
        super(BaserockImportApplication, self).process_args(args)

    def status(self, msg, *args):
        print msg % args
        logging.info(msg % args)

    def run_import_plugin(self, command, **kwargs):
        log = self.settings['log']

        if log == '/dev/stdout':
            # The plugins output results on /dev/stdout, logs would interfere
            debug('Redirecting import plugin logs to /dev/stderr')
            log = '/dev/stderr'

        extra_env = kwargs.get('extra_env', {})
        extra_env['BASEROCK_IMPORT_LOG'] = log
        extra_env['BASEROCK_IMPORT_LOG_LEVEL'] = self.settings['log-level']
        kwargs['extra_env'] = extra_env

        #cliapp.runcmd(

    def import_rubygems(self, args):
        '''Import one or more RubyGems.'''
        if len(args) != 1:
            raise cliapp.AppException(
                'Please pass the name of a RubyGem on the commandline.')

        self.import_package_and_all_dependencies('rubygems', args[0])

    def process_dependency_list(self, current_item, deps, to_process,
                                processed, these_are_build_deps):
        # All deps are added as nodes to the 'processed' graph. Runtime
        # dependencies only need to appear in the stratum, but build
        # dependencies have ordering constraints, so we add edges in
        # the graph for build-dependencies too.

        for dep_name, dep_version in deps.iteritems():
            dep_package = find(
                processed, lambda i: i.match(dep_name, dep_version))

            if dep_package is None:
                # Not yet processed
                queue_item = find(
                    to_process, lambda i: i.match(dep_name, dep_version))
                if queue_item is None:
                    queue_item = Package(dep_name, dep_version)
                    to_process.append(queue_item)
                dep_package = queue_item

            dep_package.add_required_by(current_item)

            if these_are_build_deps or current_item.is_build_dep:
                # A runtime dep of a build dep becomes a build dep
                # itself.
                dep_package.set_is_build_dep(True)
                processed.add_edge(dep_package, current_item)

    def import_package_and_all_dependencies(self, kind, goal_name,
                                            goal_version='master'):
        start_time = time.time()
        start_displaytime = time.strftime('%x %X %Z', time.localtime())

        logging.info('Import of %s %s started %s', kind, goal_name,
                     start_displaytime)

        lorry_set = LorrySet(self.settings['lorries-dir'])
        morph_set = MorphologySet(self.settings['definitions-dir'])

        chunk_dir = os.path.join(morph_set.path, 'strata', goal_name)
        if not os.path.exists(chunk_dir):
            os.makedirs(chunk_dir)

        to_process = [Package(goal_name, goal_version)]
        processed = networkx.DiGraph()

        errors = {}

        while len(to_process) > 0:
            current_item = to_process.pop()
            name = current_item.name
            version = current_item.version

            try:
                lorry = self.find_or_create_lorry_file(lorry_set, kind, name)

                source_repo, url = self.fetch_or_update_source(lorry)

                checked_out_version, ref = self.checkout_source_version(
                    source_repo, name, version)
                current_item.set_version_in_use(checked_out_version)
                chunk_morph = self.find_or_create_chunk_morph(
                    morph_set, goal_name, kind, name, checked_out_version,
                    source_repo, url, ref)

                current_item.set_morphology(chunk_morph)

                build_deps = chunk_morph['x-build-dependencies-%s' % kind]
                runtime_deps = chunk_morph['x-runtime-dependencies-%s' % kind]
            except BaserockImportException as e:
                self.status('%s', e)
                errors[current_item] = e
                build_deps = runtime_deps = {}

            processed.add_node(current_item)

            self.process_dependency_list(
                current_item, build_deps, to_process, processed, True)
            self.process_dependency_list(
                current_item, runtime_deps, to_process, processed, False)

        if len(errors) > 0:
            for package, exception in errors.iteritems():
                self.status('\n%s: %s', package.name, exception)
            self.status(
                '\nErrors encountered, not generating a stratum morphology.')
            self.status(
                'See the README files for guidance.')
        else:
            self.generate_stratum_morph_if_none_exists(processed, goal_name)

        duration = time.time() - start_time
        end_displaytime = time.strftime('%x %X %Z', time.localtime())

        logging.info('Import of %s %s ended %s (took %i seconds)', kind,
                     goal_name, end_displaytime, duration)

    def generate_lorry_for_package(self, kind, name):
        tool = '%s.to_lorry' % kind
        self.status('Calling %s to generate lorry for %s', tool, name)
        try:
            lorry_text = cliapp.runcmd([os.path.abspath(tool), name])
        except cliapp.AppException as e:
            raise BaserockImportException(e.msg.rstrip())
        lorry = json.loads(lorry_text)
        return lorry

    def find_or_create_lorry_file(self, lorry_set, kind, name):
        # Note that the lorry file may already exist for 'name', but lorry
        # files are named for project name rather than package name. In this
        # case we will generate the lorry, and try to add it to the set, at
        # which point LorrySet will notice the existing one and merge the two.
        lorry = lorry_set.find_lorry_for_package(kind, name)

        if lorry is None:
            lorry = self.generate_lorry_for_package(kind, name)

            if len(lorry) != 1:
                raise Exception(
                    'Expected generated lorry file with one entry.')

            lorry_filename = lorry.keys()[0]

            if lorry_filename == '':
                raise cliapp.AppException(
                    'Invalid lorry data for %s: %s' % (name, lorry))

            lorry_set.add(lorry_filename, lorry)
        else:
            lorry_filename = lorry.keys()[0]
            logging.info(
                'Found existing lorry file for %s: %s', name, lorry_filename)

        return lorry

    def fetch_or_update_source(self, lorry):
        assert len(lorry) == 1
        lorry_entry = lorry.values()[0]

        url = lorry_entry['url']
        reponame = os.path.basename(url.rstrip('/'))
        repopath = os.path.join(self.settings['checkouts-dir'], reponame)

        # FIXME: we should use Lorry here, so that we can import other VCSes.
        # But for now, this hack is fine!
        if os.path.exists(repopath):
            self.status('Updating repo %s', url)

            # FIXME: doesn't update the source right now, to save time.
            #cliapp.runcmd(['git', 'remote', 'update', 'origin'],
            #              cwd=repopath)
        else:
            self.status('Cloning repo %s', url)
            try:
                cliapp.runcmd(['git', 'clone', '--quiet', url, repopath])
            except cliapp.AppException as e:
                raise BaserockImportException(e.msg.rstrip())

        repo = GitDirectory(repopath)
        if repo.dirname != repopath:
            # Work around strange/unintentional behaviour in GitDirectory class
            # when 'repopath' isn't actually a Git repo at all.
            logging.error(
                'Got git directory %s for %s!', repo.dirname, repopath)
            raise cliapp.AppException(
                '%s exists but is not the root of a Git repository' % repopath)
        return repo, url

    def checkout_source_version(self, source_repo, name, version):
        # FIXME: we need to be a bit smarter than this. Right now we assume
        # that 'version' is a valid Git ref.

        possible_names = [
            version,
            'v%s' % version,
            '%s-%s' % (name, version)
        ]

        for tag_name in possible_names:
            if source_repo.has_ref(tag_name):
                source_repo.checkout(tag_name)
                ref = tag_name
                break
        else:
            #raise BaserockImportException(
            #    'Could not find ref for %s version %s.' % (name, version))
            logging.error(
                "Couldn't find tag %s in repo %s. I'm going to cheat and "
                "use 'master' for now.", tag_name, source_repo)
            source_repo.checkout('master')
            ref = version = 'master'

        return version, ref

    def generate_chunk_morph_for_package(self, kind, source_repo, name,
                                         filename):
        tool = '%s.to_chunk' % kind
        self.status('Calling %s to generate chunk morph for %s', tool, name)
        try:
            text = cliapp.runcmd(
                [os.path.abspath(tool), source_repo.dirname, name])
        except cliapp.AppException as e:
            raise BaserockImportException(e.msg.rstrip())

        loader = MorphologyLoader()
        return loader.load_from_string(text, filename)

    def find_or_create_chunk_morph(self, morph_set, goal_name, kind, name,
                                   version, source_repo, repo_url, named_ref):
        morphology_filename = 'strata/%s/%s-%s.morph' % (
            goal_name, name, version)
        sha1 = source_repo.resolve_ref_to_commit(named_ref)
        morphology = morph_set.get_morphology(
            repo_url, sha1, morphology_filename)

        if morphology is None:
            # Existing chunk morphologies loaded from disk don't contain the repo
            # and ref information. That's stored in the stratum morph. So the
            # first time we touch a chunk morph we need to set this info.
            logging.debug("Didn't find morphology for %s|%s|%s", repo_url,
                          sha1, morphology_filename)
            morphology = morph_set.get_morphology(
                None, None, morphology_filename)

            if morphology is None:
                logging.debug("Didn't find morphology for None|None|%s",
                              morphology_filename)
                morphology = self.generate_chunk_morph_for_package(
                    kind, source_repo, name, morphology_filename)
                morph_set.save_morphology(morphology_filename, morphology)

            morphology.repo_url = repo_url
            morphology.ref = sha1
            morphology.named_ref = named_ref

        return morphology

    def generate_stratum_morph_if_none_exists(self, graph, goal_name):
        filename = os.path.join(
            self.settings['definitions-dir'], 'strata', '%s.morph' % goal_name)

        if os.path.exists(filename):
            self.status(msg='Found stratum morph for %s at %s, not overwriting'
                        % (goal_name, filename))
            return

        self.status(msg='Generating stratum morph for %s' % goal_name)

        order = reversed(sorted(graph.nodes()))
        chunk_packages = networkx.topological_sort(graph, nbunch=order)
        chunk_entries = []

        for package in chunk_packages:
            m = package.morphology
            if m is None:
                raise cliapp.AppException('No morphology for %s' % package)

            def format_build_dep(name, version):
                dep_package = find(graph, lambda p: p.match(name, version))
                return '%s-%s' % (name, dep_package.version_in_use)

            build_depends = [
                format_build_dep(name, version) for name, version in
                m['x-build-dependencies-rubygems'].iteritems()
            ]

            entry = {
                'name': m['name'],
                'repo': m.repo_url,
                'ref': m.ref,
                'unpetrify-ref': m.named_ref,
                'morph': m.filename,
                'build-depends': build_depends,
            }
            chunk_entries.append(entry)

        stratum_name = goal_name
        stratum = {
            'name': stratum_name,
            'kind': 'stratum',
            'description': 'Autogenerated by Baserock import tool',
            'build-depends': [
                {'morph': 'strata/ruby.morph'}
            ],
            'chunks': chunk_entries,
        }

        loader = morphlib.morphloader.MorphologyLoader()
        morphology = loader.load_from_string(json.dumps(stratum),
                                             filename=filename)

        loader.unset_defaults(morphology)
        loader.save_to_file(filename, morphology)


app = BaserockImportApplication(progname='import')
app.run()
