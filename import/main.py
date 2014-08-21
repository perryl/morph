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

import contextlib
import json
import logging
import os
import sys

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
        key = 'x-%s-products' % kind
        for name, lorry in self.data.iteritems():
            products = lorry.get(key, [])
            if package_name in products:
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

        filename = os.path.join(self.path, '%s.lorry' % filename)

        assert len(lorry_entry) == 1

        project_name = lorry_entry.keys()[0]
        info = lorry_entry.values()[0]
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
MorphologyLoader._static_defaults['chunk']['x-dependencies-rubygem'] = []


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
        fake_gitdir = morphlib.gitdir.GitDirectory(self.path)
        finder = morphlib.morphologyfinder.MorphologyFinder(fake_gitdir)
        loader = MorphologyLoader()
        for filename in (f for f in finder.list_morphologies()
                         if not fake_gitdir.is_symlink(f)):
            text = finder.read_morphology(filename)
            morph = loader.load_from_string(text, filename=filename)
            morph.repo_url = None  # self.root_repository_url
            morph.ref = None  # self.system_branch_name
            self.add_morphology(morph)

    def get_morphology(self, filename):
        return self._get_morphology(None, None, filename)

    def save_morphology(self, filename, morphology):
        self.add_morphology(morphology)
        self.loader.save_to_file(os.path.join(self.path, filename), morphology)


class GitDirectory(morphlib.gitdir.GitDirectory):
    def has_ref(self, ref):
        try:
            self._rev_parse(ref)
            return True
        except morphlib.gitdir.InvalidRefError:
            return False


class BaserockImportException(cliapp.AppException):
    pass


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

    def setup_logging_format(self):
        # FIXME: due to a bug in cliapp, this method is actually
        # never called! :(
        return "main: %(levelname)s: %(message)s"

    def setup_logging_for_import_plugins(self):
        log = self.settings['log']

        if log == '/dev/stdout':
            # The plugins output results on /dev/stdout, logs would interfere
            debug('Redirecting import plugin logs to /dev/stderr')
            log = '/dev/stderr'

        os.environ['BASEROCK_IMPORT_LOG'] = log
        os.environ['BASEROCK_IMPORT_LOG_LEVEL'] = self.settings['log-level']

    def process_args(self, *args):
        self.setup_logging_for_import_plugins()
        super(BaserockImportApplication, self).process_args(*args)

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

    def cmd_rubygem(self, args):
        if len(args) != 1:
            raise cliapp.AppException(
                'Please pass the name of a RubyGem on the commandline.')

        #try:
        self.import_package_and_all_dependencies('rubygem', args[0])
        #except:
            #import pdb, traceback
            #print sys.format_exc
            #print traceback.print_tb(sys.exc_traceback)
            #pdb.post_mortem(sys.exc_traceback)

    def import_package_and_all_dependencies(self, kind, goal_name,
                                            goal_version='master'):
        class QueueItem(object):
            '''A package in the processing queue.

            In order to provide helpful errors, this item keeps track of what
            packages depend on it, and hence of why it was added to the queue.

            '''
            def __init__(self, name, version):
                self.name = name
                self.version = version
                self.required_by = []

            def __str__(self):
                if len(self.required_by) > 0:
                    required_msg = ', '.join(self.required_by)
                    required_msg = ', required by: ' + required_msg
                else:
                    required_msg = ''
                return '%s-%s%s' % (name, version, required_msg)

            def add_required_by(self, item):
                self.required_by.append('%s-%s' % (item.name, item.version))

            def match(self, name, version):
                return (self.name==name and self.version==version)

        def find(iterable, match):
            return next((x for x in iterable if match(x)), None)

        def enqueue_dependencies(deps, to_process, processed):
            for dep_name, dep_version in deps.iteritems():
                processed_queue_item = find(
                    processed, lambda i: i.match(dep_name, dep_version))
                if processed_queue_item is None:
                    queue_item = find(
                        to_process, lambda i: i.match(dep_name, dep_version))
                    if queue_item is None:
                        queue_item = QueueItem(dep_name, dep_version)
                        to_process.append(queue_item)
                    queue_item.add_required_by(current_item)
                else:
                    processed_queue_item.add_required_by(current_item)

        lorry_set = LorrySet(self.settings['lorries-dir'])
        morph_set = MorphologySet(self.settings['definitions-dir'])

        to_process = [QueueItem(goal_name, goal_version)]
        processed = []

        while len(to_process) > 0:
            current_item = to_process.pop()
            name = current_item.name
            version = current_item.version

            try:
                lorry = self.find_or_create_lorry_file(lorry_set, kind, name)

                source_repo = self.fetch_or_update_source(lorry)

                chunk_morph = self.find_or_create_chunk_morph(
                    morph_set, kind, name, version, source_repo)

                processed.append(current_item)

                deps = chunk_morph['x-dependencies-%s' % kind]
                enqueue_dependencies(deps, to_process, processed)
            except BaserockImportException:
                sys.stderr.write('Error processing package %s\n' % current_item)
                raise

        # Now: solve the dependencies and generate the bootstrap set!
        # generate the stratum!

    def generate_lorry_for_package(self, kind, name):
        tool = '%s.to_lorry' % kind
        self.status('Calling %s to generate lorry for %s', tool, name)
        lorry_text = cliapp.runcmd([os.path.abspath(tool), name])
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

            lorry_set.add(lorry_filename, lorry)

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
            cliapp.runcmd(['git', 'clone', url, repopath])

        repo = GitDirectory(repopath)
        return repo

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
                break
        else:
            logging.error(
                "Couldn't find tag %s in repo %s. I'm going to cheat and "
                "use 'master' for now.")
            source_repo.checkout('master')
            #raise BaserockImportException(
            #    'Could not find ref for %s version %s.' % (name, version))

    def generate_chunk_morph_for_package(self, kind, source_repo, name,
                                         filename):
        tool = '%s.to_chunk' % kind
        self.status('Calling %s to generate chunk morph for %s', tool, name)
        text = cliapp.runcmd([os.path.abspath(tool), source_repo.dirname,
                              name])

        loader = MorphologyLoader()
        return loader.load_from_string(text, filename)

    def find_or_create_chunk_morph(self, morph_set, kind, name, version,
                                   source_repo):
        morphology_filename = '%s-%s.morph' % (name, version)
        morphology = morph_set.get_morphology(morphology_filename)

        if morphology is None:
            self.checkout_source_version(source_repo, name, version)
            morphology = self.generate_chunk_morph_for_package(
                kind, source_repo, name, morphology_filename)
            morph_set.save_morphology(morphology_filename, morphology)

        return morphology


app = BaserockImportApplication(progname='import')
app.run()
