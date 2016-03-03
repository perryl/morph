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
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import csv
import glob
import inspect
import json
import os
import shutil
import tempfile
import warnings

import cliapp

import morphlib

class SystemManifestsPlugin(cliapp.Plugin):

    def enable(self):
        self.app.add_subcommand(
            'generate-manifest-csv', self.manifests,
            arg_synopsis='REPO REF MORPH [MORPH]...')
        self.app.settings.choice(['check-license'],
                                 ['all-files', 'single-file'],
                                 'indicates whether just a license file '
                                 'should be looked at, or if all files '
                                 'in each chunk should be looked at for '
                                 'licensing information. Takes '
                                 '`single-file` or `all-files` for the '
                                 'two methods, respectively. Defaults to '
                                 'all-files, although this is much slower.',
                                 group='manifest options')

    def disable(self):
        pass

    def manifests(self, args):
        '''Generate manifest(s) for the given system(s).

        Command line arguments:

        * `REPO` is a git repository URL.
        * `REF` is a branch or other commit reference in that repository.
        * `MORPH` is a system morphology name at that ref.

        This command produces CSV files in the current working directory
        named MORPH-manifest.csv, where MORPH is the system filename.

        These CSVs contain the chunk name, a version guess, the license as
        defined by COPYING or LICENSE, a list of all licenses used in the
        chunk (unless --check-license=single-file is set) and the upstream
        URL based on the configured trove-host's lorries repo.

        Note that this command is pretty slow, even with --check-license set
        to single-file it will take about half an hour to generate a manifest
        for a build-system. With --check-license set to all-files (the default)
        it will take a long time.

        You pass it a list of systems to generate manifests for.

          $ morph generate-manifest-csv . HEAD \
                systems/devel-system-x86_64-generic.morph \
                systems/xfce-system.morph

        '''

        if len(args) < 3:
            raise cliapp.AppException(
                'Usage: morph generate-manifest-csv REPO REF MORPH...')

        repo, ref = args[0], args[1]
        system_filenames = map(morphlib.util.sanitise_morphology_path,
                               args[2:])

        self.lrc, self.rrc = morphlib.util.new_repo_caches(self.app)
        self.resolver = morphlib.artifactresolver.ArtifactResolver()

        for system_filename in system_filenames:
            self.system_manifest(repo, ref, system_filename)

    @staticmethod
    def find_artifact_by_name(artifacts_list, filename):
        for a in artifacts_list:
            if a.source.filename == filename:
                return a
        raise ValueError()

    def system_manifest(self, repo, ref, system_filename):
        '''Generate manifest for given system.'''

        self.app.status(
            msg='Creating source pool for %(system)s',
            system=system_filename, chatty=True)
        source_pool = morphlib.sourceresolver.create_source_pool(
            self.lrc, self.rrc, repo, ref, [system_filename],
            cachedir=self.app.settings['cachedir'],
            update_repos = not self.app.settings['no-git-update'],
            status_cb=self.app.status)

        self.app.status(
            msg='Resolving artifacts for %(system)s',
            system=system_filename, chatty=True)
        root_artifacts = self.resolver.resolve_root_artifacts(source_pool)

        system_artifact = self.find_artifact_by_name(root_artifacts,
                                                     system_filename)

        self.app.status(
            msg='Computing cache keys for %(system)s',
            system=system_filename, chatty=True)
        build_env = morphlib.buildenvironment.BuildEnvironment(
            self.app.settings, system_artifact.source.morphology['arch'])
        ckc = morphlib.cachekeycomputer.CacheKeyComputer(build_env)

        # FIXME: This should be fixed in morphloader.
        morphlib.util.fix_chunk_build_mode(system_artifact)

        aliases = self.app.settings['repo-alias']
        resolver = morphlib.repoaliasresolver.RepoAliasResolver(aliases)

        try:
            trove_id = self.app.settings['trove-id'][0]
        except IndexError:
            trove_id = None
        with morphlib.util.temp_dir(dir=self.app.settings['tempdir']) as td:
            lorries = get_lorry_repos(td, self.lrc, self.app.status, trove_id,
                                      self.app.settings['trove-host'])
            manifest = Manifest(system_artifact.name, td, self.app.status,
                                self.lrc)

            old_prefix = self.app.status_prefix
            sources = set(a.source for a in system_artifact.walk()
                          if a.source.morphology['kind'] == 'chunk'
                          and a.source.morphology['build-mode'] != 'bootstrap')
            for i, source in enumerate(sources, start=1):
                source.cache_key = ckc.compute_key(source)
                source.cache_id = ckc.get_cache_id(source)
                name = source.morphology['name']
                ref = source.original_ref

                cached = self.lrc.get_updated_repo(source.repo_name, ref)

                new_prefix = '[%d/%d][%s] ' % (i, len(sources), name)
                self.app.status_prefix = old_prefix + new_prefix
                manifest.add_chunk(self.app, name, source.repo_name, ref,
                                   cached, resolver, lorries)
            self.app.status_prefix = old_prefix


def run_licensecheck(filename):
    morphlib_dirname = os.path.dirname(inspect.getfile(morphlib))
    licensecheck_path = os.path.join(morphlib_dirname, 'licensecheck.pl')
    output = cliapp.runcmd(['perl', licensecheck_path, '-l',
                            '500', filename])
    if not output:
        return 'UNKNOWN'
    else:
        return output[len(filename) + 2:].strip()

def checkout_repo(lrc, repo, dest, ref='master'):
    cached = lrc.get_updated_repo(repo, ref)
    if not os.path.exists(dest):
        morphlib.gitdir.checkout_from_cached_repo(repo, ref, dest)

def load_lorries(dir):
    lorries = []
    lorry_files = []
    config_file = os.path.join(dir, 'lorry-controller.conf')
    with open(config_file, 'r') as conf:
        config = json.load(conf)
    for stanza in config:
        if stanza['type'] != 'lorries':
            continue
        for base_pattern in stanza['globs']:
            pattern = os.path.join(dir, base_pattern)
            lorry_files.extend(glob.glob(pattern))

    for f in lorry_files:
        with open(f, 'r') as lorry:
            lorries.append(json.load(lorry))
    return lorries

def get_lorry_for_chunk(chunk_url, lorries):
    if 'delta/' in chunk_url:
        chunk_name = chunk_url.split('delta/', 1)[-1]
    else:
        chunk_name = chunk_url.split(':', 1)[-1]
    for lorry in lorries:
        if chunk_name in lorry:
            return lorry[chunk_name]

def get_main_license(dir): # pragma: no cover
    license = 'UNKNOWN'
    if os.path.exists(os.path.join(dir, 'COPYING')):
        license_file = os.path.join(dir, 'COPYING')
    elif os.path.exists(os.path.join(dir, 'LICENSE')):
        license_file = os.path.join(dir, 'LICENSE')
    else:
        return license
    return run_licensecheck(license_file)

def get_all_licenses(dir): # pragma: no cover
    license_list = []
    for dirpath, dirname, filenames in os.walk(dir):
        for filename in filenames:
            try:
                license = run_licensecheck(os.path.join(dirpath, filename))
            except cliapp.AppException:
                continue
            if not license in license_list:
                license_list.append(license)
    return license_list

def get_upstream_address(chunk_url, lorries, status):
    lorry = get_lorry_for_chunk(chunk_url, lorries)
    try:
        return lorry['url']
    except TypeError:
        status(msg='Lorry for %(chunk)s not found.', chunk=chunk_url)
        return chunk_url
    except KeyError:
        status(msg='Lorry for %(chunk)s has no "url" field.',
               chunk=chunk_url)
        return 'UNKNOWN'

def get_lorry_repos(tempdir, lrc, status, trove_id, trove_host):
    lorries = []
    try:
        baserock_lorry_repo = 'baserock:local-config/lorries'
        lorrydir = os.path.join(tempdir, 'baserock-lorries')
        baserock_lorrydir = checkout_repo(lrc, baserock_lorry_repo, lorrydir)
        lorries.extend(load_lorries(lorrydir))
    except morphlib.localrepocache.NoRemote as e:
        status(msg="WARNING: Could not find lorries from git.baserock.org, "
                   "expected to find them on %(trove)s at %(reponame)s",
               trove=trove_host, reponame = e.reponame)

    if trove_id:
        try:
            trove_lorry_repo =  ('http://%s/git/%s/local-config/lorries' %
                                 (trove_host, trove_id))
            lorrydir = os.path.join(tempdir, '%s-lorries' % trove_id)
            trove_lorrydir = checkout_repo(lrc, trove_lorry_repo, lorrydir)
            lorries.extend(load_lorries(lorrydir))
        except morphlib.localrepocache.NoRemote as e:
            status(msg="WARNING: Could not find lorries repo on %(trove)s "
                       "at %(reponame)s",
                   trove=trove_host, reponame=e.reponame)
    else:
        status(msg="WARNING: Not looking in %(trove)s's local-config/lorries "
                   "repo as trove-id was not configured.", trove=trove_host)

    return lorries


class Manifest(object):
    """Writes out a manifest of what's included in a system."""

    def __init__(self, system_name, tempdir, status_cb, lrc):
        self.tempdir = tempdir
        self.status = status_cb
        self.lrc = lrc
        path = os.path.join(os.getcwd(), system_name + '-manifest.csv')
        self.status(msg='Creating %(path)s', path=path)
        self.file = open(path, 'wb')
        self.writer = csv.writer(self.file, quoting=csv.QUOTE_ALL)

    def _write_chunk(self, chunk_name, version_guess,
                     license, license_list, upstream):
        self.writer.writerow([chunk_name, version_guess,
                              license, license_list, upstream])

    def add_chunk(self, app, chunk_name, chunk_url, ref,
                  cached_repo, resolver, lorries):
        self.status(msg='Inspecting chunk: %(chunk)s', chunk=chunk_name)
        self.status(msg='Guessing version', chatty=True)
        version_guess = cached_repo.version_guess(ref)

        dir = os.path.join(self.tempdir, chunk_name)
        try:
            self.status(msg='Checking out chunk repo into %(dir)s at %(ref)s',
                        dir=dir, ref=ref, chatty=True)
            gd = morphlib.gitdir.checkout_from_cached_repo(
                cached_repo, ref, dir)
            gd.update_submodules(app)

            self.status(msg='Getting license info', chatty=True)
            license = get_main_license(dir)
            if app.settings['check-license'] == 'all-files':
                license_list = get_all_licenses(dir)
            else:
                self.status(msg='WARNING: Not looking at individual file '
                                'licenses as check-license was not set to '
                                '`all-files`.')
                license_list = 'UNKNOWN'

            self.status(msg='Getting upstream location', chatty=True)
            upstream = get_upstream_address(chunk_url, lorries, self.status)
            if upstream == chunk_url:
                upstream = '%s (no lorry)' % resolver.pull_url(upstream)

            self._write_chunk(chunk_name, version_guess, license,
                              license_list, upstream)
        finally:
            shutil.rmtree(dir)
