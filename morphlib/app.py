# Copyright (C) 2011-2014  Codethink Limited
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
import collections
import logging
import os
import sys
import time
import urlparse
import warnings
import extensions

import morphlib

class InvalidUrlError(cliapp.AppException):

    def __init__(self, parameter, url):
        cliapp.AppException.__init__(
            self, 'Value %s for argument %s is not a url' %
            (url, parameter))

defaults = {
    'trove-host': 'git.baserock.org',
    'trove-id': [],
    'repo-alias': [
        ('freedesktop='
            'git://anongit.freedesktop.org/#'
            'ssh://git.freedesktop.org/'),
        ('gnome='
            'git://git.gnome.org/%s#'
            'ssh://git.gnome.org/git/%s'),
        ('github='
            'git://github.com/%s#'
            'ssh://git@github.com/%s'),
    ],
    'cachedir': os.path.expanduser('~/.cache/morph'),
    'max-jobs': morphlib.util.make_concurrency()
}


class Morph(cliapp.Application):

    def add_settings(self):
        self.settings.boolean(['verbose', 'v'],
                              'show what is happening in much detail')
        self.settings.boolean(['quiet', 'q'],
                              'show no output unless there is an error')

        self.settings.boolean(['help', 'h'],
                              'show this help message and exit') 
        self.settings.boolean(['help-all'],
                              'show help message including hidden subcommands')

        self.settings.string(['build-ref-prefix'],
                             'Prefix to use for temporary build refs',
                             metavar='PREFIX',
                             default=None)
        self.settings.string(['trove-host'],
                             'hostname of Trove instance',
                             metavar='TROVEHOST',
                             default=defaults['trove-host'])
        self.settings.string_list(['trove-id', 'trove-prefix'],
                                  'list of URL prefixes that should be '
                                  'resolved to Trove',
                                  metavar='PREFIX, ...',
                                  default=defaults['trove-id'])

        group_advanced = 'Advanced Options'
        self.settings.boolean(['no-git-update'],
                              'do not update the cached git repositories '
                              'automatically',
                              group=group_advanced)
        self.settings.string_list(['repo-alias'],
                                  'list of URL prefix definitions, in the '
                                  'form: example=git://git.example.com/%s'
                                  '#git@git.example.com/%s',
                                  metavar='ALIAS=PREFIX#PULL#PUSH',
                                  default=defaults['repo-alias'],
                                  group=group_advanced)
        self.settings.string(['cache-server'],
                             'HTTP URL of the morph cache server to use. '
                             'If not provided, defaults to '
                             'http://TROVEHOST:8080/',
                             metavar='URL',
                             default=None,
                             group=group_advanced)
        self.settings.string(
            ['artifact-cache-server'],
            'HTTP URL for the artifact cache server; '
            'if not set, then the cache-server setting is used instead',
            metavar='URL',
            default=None,
            group=group_advanced)
        self.settings.string(
            ['git-resolve-cache-server'],
            'HTTP URL for the git ref resolving cache server; '
            'if not set, then the cache-server setting is used instead',
            metavar='URL',
            default=None,
            group=group_advanced)
        self.settings.string(['tarball-server'],
                             'base URL to download tarballs. '
                             'If not provided, defaults to '
                             'http://TROVEHOST/tarballs/',
                             metavar='URL',
                             default=None,
                             group=group_advanced)

        group_build = 'Build Options'
        self.settings.integer(['max-jobs'],
                              'run at most N parallel jobs with make (default '
                              'is to a value based on the number of CPUs '
                              'in the machine running morph',
                              metavar='N',
                              default=defaults['max-jobs'],
                              group=group_build)
        self.settings.boolean(['no-ccache'], 'do not use ccache',
                              group=group_build)
        self.settings.boolean(['no-distcc'],
                              'do not use distcc (default: true)',
                              group=group_build, default=True)
        self.settings.boolean(['push-build-branches'],
                              'always push temporary build branches to the '
                              'remote repository',
                              group=group_build)

        group_storage = 'Storage Options'
        self.settings.string(['tempdir'],
                             'temporary directory to use for builds '
                             '(this is separate from just setting $TMPDIR '
                             'or /tmp because those are used internally '
                             'by things that cannot be on NFS, but '
                             'this setting can point at a directory in '
                             'NFS)',
                             metavar='DIR',
                             default=None,
                             group=group_storage)
        self.settings.string(['cachedir'],
                             'cache git repositories and build results in DIR',
                             metavar='DIR',
                             group=group_storage,
                             default=defaults['cachedir'])
        self.settings.string(['compiler-cache-dir'],
                             'cache compiled objects in DIR/REPO. If not '
                             'provided, defaults to CACHEDIR/ccache/',
                             metavar='DIR',
                             group=group_storage,
                             default=None)
        # The tempdir default size of 4G comes from the staging area needing to
        # be the size of the largest known system, plus the largest repository,
        # plus the largest working directory.
        # The largest system is 2G, linux is the largest git repository at
        # 700M, the checkout of this is 600M. This is rounded up to 4G because
        # there are likely to be file-system overheads.
        self.settings.bytesize(['tempdir-min-space'],
                               'Immediately fail to build if the directory '
                               'specified by tempdir has less space remaining '
                               'than SIZE bytes (default: %default)',
                               metavar='SIZE',
                               group=group_storage,
                               default='4G')
        # The cachedir default size of 4G comes from twice the size of the
        # largest system artifact.
        # It's twice the size because it needs space for all the chunks that
        # make up the system artifact as well.
        # The git cache and ccache are also kept in cachedir, but it's hard to
        # estimate size needed for the git cache, and it tends to not grow
        # too quickly once everything is checked out.
        # ccache is self-managing so does not need much extra attention
        self.settings.bytesize(['cachedir-min-space'],
                               'Immediately fail to build if the directory '
                               'specified by cachedir has less space '
                               'remaining than SIZE bytes (default: %default)',
                               metavar='SIZE',
                               group=group_storage,
                               default='4G')

    def check_time(self):
        # Check that the current time is not far in the past.
        if time.localtime(time.time()).tm_year < 2012:
            raise morphlib.Error(
                'System time is far in the past, please set your system clock')

    def setup(self):
        self.status_prefix = ''

        self.add_subcommand('help-extensions', self.help_extensions)

    def process_args(self, args):
        self.check_time()

        if self.settings['help']:
            self.help(args)
            sys.exit(0)

        if self.settings['help-all']:
            self.help_all(args)
            sys.exit(0)

        if self.settings['build-ref-prefix'] is None:
            if self.settings['trove-id']:
                self.settings['build-ref-prefix'] = os.path.join(
                        self.settings['trove-id'][0], 'builds')
            else:
                self.settings['build-ref-prefix'] = "baserock/builds"

        # Combine the aliases into repo-alias before passing on to normal
        # command processing.  This means everything from here on down can
        # treat settings['repo-alias'] as the sole source of prefixes for git
        # URL expansion.
        self.settings['repo-alias'] = morphlib.util.combine_aliases(self)
        if self.settings['cache-server'] is None:
            self.settings['cache-server'] = 'http://%s:8080/' % (
                self.settings['trove-host'])
        if self.settings['tarball-server'] is None:
            self.settings['tarball-server'] = 'http://%s/tarballs/' % (
                self.settings['trove-host'])
        if self.settings['compiler-cache-dir'] is None:
            self.settings['compiler-cache-dir'] = os.path.join(
                    self.settings['cachedir'], 'ccache')
        if self.settings['tempdir'] is None:
            tmpdir_base = os.environ.get('TMPDIR', '/tmp')
            tmpdir = os.path.join(tmpdir_base, 'morph_tmp')
            self.settings['tempdir'] = tmpdir

        if self.settings['tarball-server']:
            url_split = urlparse.urlparse(self.settings['tarball-server'])
            if not (url_split.netloc and
                    url_split.scheme in ('http', 'https', 'file')):
                raise InvalidUrlError('tarball-server',
                                      self.settings['tarball-server'])

        if 'MORPH_DUMP_PROCESSED_CONFIG' in os.environ:
            self.settings.dump_config(sys.stdout)
            sys.exit(0)

        tmpdir = self.settings['tempdir']
        for required_dir in (os.path.join(tmpdir, 'chunks'),
                             os.path.join(tmpdir, 'staging'),
                             os.path.join(tmpdir, 'failed'),
                             os.path.join(tmpdir, 'deployments'),
                             self.settings['cachedir']):
            if not os.path.exists(required_dir):
                os.makedirs(required_dir)

        cliapp.Application.process_args(self, args)

    def setup_plugin_manager(self):
        cliapp.Application.setup_plugin_manager(self)

        self.pluginmgr.locations += os.path.join(
            os.path.dirname(morphlib.__file__), 'plugins')

        s = os.environ.get('MORPH_PLUGIN_PATH', '')
        self.pluginmgr.locations += s.split(':')

        self.hookmgr = cliapp.HookManager()
        self.hookmgr.new('new-build-command', cliapp.FilterHook())

    def itertriplets(self, args):
        '''Generate repo, ref, filename triples from args.'''

        if (len(args) % 3) != 0:
            raise cliapp.AppException('Argument list must have full triplets')

        while args:
            assert len(args) >= 2, args
            yield args[0], args[1], args[2]
            args = args[3:]

    def create_source_pool(self, lrc, rrc, triplet):
        pool = morphlib.sourcepool.SourcePool()

        def add_to_pool(reponame, ref, filename, absref, tree, morphology):
            source = morphlib.source.Source(reponame, ref, absref, tree,
                                            morphology, filename)
            pool.add(source)

        self.traverse_morphs([triplet], lrc, rrc,
                             update=not self.settings['no-git-update'],
                             visit=add_to_pool)
        return pool

    def resolve_ref(self, lrc, rrc, reponame, ref, update=True):
        '''Resolves commit and tree sha1s of the ref in a repo and returns it.

        If update is True then this has the side-effect of updating
        or cloning the repository into the local repo cache.
        '''
        absref = None
        if lrc.has_repo(reponame):
            repo = lrc.get_repo(reponame)
            if update:
                self.status(msg='Updating cached git repository %(reponame)s',
                            reponame=reponame)
                repo.update()
            absref, tree = repo.resolve_ref(ref)
        elif rrc is not None:
            try:
                absref, tree = rrc.resolve_ref(reponame, ref)
                if absref is not None:
                    self.status(msg='Resolved %(reponame)s %(ref)s via remote '
                                'repo cache',
                                reponame=reponame,
                                ref=ref,
                                chatty=True)
            except BaseException, e:
                logging.warning('Caught (and ignored) exception: %s' % str(e))
        if absref is None:
            if update:
                self.status(msg='Caching git repository %(reponame)s',
                            reponame=reponame)
                repo = lrc.cache_repo(reponame)
                repo.update()
            else:
                repo = lrc.get_repo(reponame)
            absref, tree = repo.resolve_ref(ref)
        return absref, tree

    def traverse_morphs(self, triplets, lrc, rrc, update=True,
                        visit=lambda rn, rf, fn, arf, m: None):
        morph_factory = morphlib.morphologyfactory.MorphologyFactory(lrc, rrc,
                                                                     self)
        queue = collections.deque(triplets)
        updated_repos = set()
        resolved_refs = {}
        resolved_morphologies = {}

        # assume that the first triplet is a morphology from the definitions
        # repo, then load everything from there
        morphs_repo, morphs_ref, _ = triplets[0]

        while queue:
            reponame, ref, filename = queue.popleft()
            update_repo = update and morphs_repo not in updated_repos

            # Resolve the (repo, ref) reference, cache result.
            reference = (morphs_repo, morphs_ref)
            if not reference in resolved_refs:
                resolved_refs[reference] = self.resolve_ref(
                        lrc, rrc, morphs_repo, morphs_ref, update_repo)
            absref, tree = resolved_refs[reference]

            updated_repos.add(morphs_repo)

            # Fetch the (repo, ref, filename) morphology, cache result.
            reference = (morphs_repo, absref, filename)
            if not reference in resolved_morphologies:
                resolved_morphologies[reference] = \
                    morph_factory.get_morphology(morphs_repo, absref, filename)
            morphology = resolved_morphologies[reference]

            if reponame != morphs_repo or ref != morphs_ref:
                update_repo = update and reponame not in updated_repos
                absref, tree = self.resolve_ref(
                        lrc, rrc, reponame, ref, update_repo)
                updated_repos.add(reponame)
            visit(reponame, ref, filename, absref, tree, morphology)
            if morphology['kind'] == 'cluster':
                raise cliapp.AppException(
                    "Cannot build a morphology of type 'cluster'.")
            elif morphology['kind'] == 'system':
                queue.extend((s.get('repo') or reponame,
                              s.get('ref') or ref,
                              s['morph'])
                             for s in morphology['strata'])
            elif morphology['kind'] == 'stratum':
                if morphology['build-depends']:
                    queue.extend((s.get('repo') or reponame,
                                  s.get('ref') or ref,
                                  s['morph'])
                                 for s in morphology['build-depends'])
                queue.extend((c['repo'], c['ref'], c['morph'])
                             for c in morphology['chunks'])

    def cache_repo_and_submodules(self, cache, url, ref, done):
        subs_to_process = set()
        subs_to_process.add((url, ref))
        while subs_to_process:
            url, ref = subs_to_process.pop()
            done.add((url, ref))
            cached_repo = cache.cache_repo(url)
            cached_repo.update()

            try:
                submodules = morphlib.git.Submodules(self, cached_repo.path,
                                                     ref)
                submodules.load()
            except morphlib.git.NoModulesFileError:
                pass
            else:
                for submod in submodules:
                    if (submod.url, submod.commit) not in done:
                        subs_to_process.add((submod.url, submod.commit))

    def status(self, **kwargs):
        '''Show user a status update.

        The keyword arguments are formatted and presented to the user in
        a pleasing manner. Some keywords are special:

        * ``msg`` is the message text; it can use ``%(foo)s`` to embed the
          value of keyword argument ``foo``
        * ``chatty`` should be true when the message is only informative,
          and only useful for users who want to know everything (--verbose)
        * ``error`` should be true when it is an error message

        All other keywords are ignored unless embedded in ``msg``.
        
        The ``self.status_prefix`` string is prepended to the output.
        It is set to the empty string by default.

        '''

        assert 'msg' in kwargs
        text = self.status_prefix + (kwargs['msg'] % kwargs)

        error = kwargs.get('error', False)
        chatty = kwargs.get('chatty', False)
        quiet = self.settings['quiet']
        verbose = self.settings['verbose']

        if error:
            logging.error(text)
        elif chatty:
            logging.debug(text)
        else:
            logging.info(text)

        ok = verbose or error or (not quiet and not chatty)
        if ok:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
            self.output.write('%s %s\n' % (timestamp, text))
            self.output.flush()

    def runcmd(self, argv, *args, **kwargs):
        if 'env' not in kwargs:
            kwargs['env'] = dict(os.environ)

        if 'print_command' in kwargs:
            print_command = kwargs['print_command']
            del kwargs['print_command']
        else:
            print_command = True

        # convert the command line arguments into a string
        commands = [argv] + list(args)
        for command in commands:
            if isinstance(command, list):
                for i in xrange(0, len(command)):
                    command[i] = str(command[i])
        commands = [' '.join(command) for command in commands]

        # print the command line
        if print_command:
            self.status(msg='# %(cmdline)s',
                        cmdline=' | '.join(commands),
                        chatty=True)

        # Log the environment.
        prev = getattr(self, 'prev_env', {})
        morphlib.util.log_dict_diff(self, kwargs['env'], prev)
        self.prev_env = kwargs['env']

        # run the command line
        return cliapp.Application.runcmd(self, argv, *args, **kwargs)

    def parse_args(self, args, configs_only=False):
        return self.settings.parse_args(args,
                         configs_only=configs_only,
                         arg_synopsis=self.arg_synopsis,
                         cmd_synopsis=self.cmd_synopsis,
                         compute_setting_values=self.compute_setting_values,
                         add_help_option=False)

    def _help(self, show_all):
        pp = self.settings.build_parser(
            configs_only=True,
            arg_synopsis=self.arg_synopsis,
            cmd_synopsis=self.cmd_synopsis,
            all_options=show_all,
            add_help_option=False)
        text = pp.format_help()
        self.output.write(text)

    def _help_topic(self, topic):
        build_ref_prefix = self.settings['build-ref-prefix']
        if topic in self.subcommands:
            usage = self._format_usage_for(topic)
            description = self._format_subcommand_help(topic)
            text = '%s\n\n%s' % (usage, description)
            self.output.write(text)
        elif topic in extensions.list_extensions(build_ref_prefix):
            name, kind = os.path.splitext(topic)
            try:
                with extensions.get_extension_filename(build_ref_prefix,
                        name,
                        kind + '.help', executable=False) as fname:
                    with open(fname, 'r') as f:
                        help_data = morphlib.yamlparse.load(f.read())
                        print help_data['help']
            except extensions.ExtensionError:
                    raise cliapp.AppException(
                            'Help not available for extension %s' % topic)
        else:
            raise cliapp.AppException(
                    'Unknown subcommand or extension %s' % topic)

    def help(self, args): # pragma: no cover
        '''Print help.'''
        if args:
            self._help_topic(args[0])
        else:
            self._help(False)

    def help_all(self, args): # pragma: no cover
        '''Print help, including hidden subcommands.'''
        self._help(True)

    def help_extensions(self, args):
        exts = extensions.list_extensions(self.settings['build-ref-prefix'])
        template = "Extensions:\n    %s\n"
        ext_string = '\n    '.join(exts)
        self.output.write(template % (ext_string))
