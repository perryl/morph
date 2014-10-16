#!/usr/bin/env python
#
# Create a Baserock .lorry file for a given Python package
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

from __future__ import print_function

import subprocess
import requests
import json
import sys
import shutil
import tempfile
import xmlrpclib

import parser.requirements # todo add this as a submodule

PYPI_URL = 'http://pypi.python.org/pypi'

def warn(*args, **kwargs):
    print('%s:' % sys.argv[0], *args, file=sys.stderr, **kwargs)

def error(*args, **kwargs):
    warn(*args, **kwargs)
    sys.exit(1)

def fetch_package_metadata(package_name):
    try:
        return requests.get('%s/%s/json' % (PYPI_URL, package_name)).json()
    except Exception as e:
        error("Couldn't fetch package metadata: ", e)

def find_repo_type(url):
    print('Finding repo type for %s' % url)

    vcss = [('git', 'clone'), ('hg', 'clone'),
            ('svn', 'checkout'), ('bzr', 'branch')]

    for (vcs, vcs_command) in vcss:
        print('Trying %s %s' % (vcs, vcs_command))
        tempdir = tempfile.mkdtemp()

        p = subprocess.Popen([vcs, vcs_command, url], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, cwd=tempdir)

        _, _ = p.communicate()
        shutil.rmtree(tempdir)

        if p.returncode == 0:
            print('%s is a %s repo' % (url, vcs))
            return vcs

    print("%s doesn't seem to be a repo" % url)

    return None

def get_compression(url):
    bzip = 'bzip2'
    gzip = 'gzip'
    lzma = 'lzma'

    m = {'tar.gz': gzip, 'tgz': gzip, 'tar.Z': gzip,
           'tar.bz2': bzip, 'tbz2': bzip,
           'tar.lzma': lzma, 'tar.xz': lzma, 'tlz': lzma, 'txz': lzma}

    for x in [1, 2]:
        ext = '.'.join(url.split('.')[-x:])
        if ext in m: return m[ext]

    return None

# Assumption: url passed to this function must have a 'standard' tar extension
def make_tarball_lorry(name, url):
    lorry = {'type': 'tarball', 'url': url}
    compression = get_compression(url)
    if compression:
        lorry['compression'] = compression

    return json.dumps({name.lower() + "-tarball": lorry},
                      indent=4, sort_keys=True)

def ask_user(client, xs, fn, prompt='--> '):
    for n, x in enumerate(xs, 1):
        print('[%s]: %s' % (n, fn(x)))
    print('')

    s = raw_input(prompt)
    choice = int(s) if s.isdigit() else None
    choice = choice - 1 if choice != None and choice <= len(xs) else None

    if choice == None:
        print("Invalid choice", file=sys.stderr)
        sys.exit(1)

    return choice

def filter_urls(urls):
    allowed_extensions = ['tar.gz', 'tgz', 'tar.Z', 'tar.bz2', 'tbz2',
                          'tar.lzma', 'tar.xz', 'tlz', 'txz', 'tar']

    def allowed_extension(url):
        return ('.'.join(url['url'].split('.')[-2:]) in allowed_extensions
            or url['url'].split('.')[-1:] in allowed_extensions)

    return filter(allowed_extension, urls)

# TODO: find a nicer way to do this
def specs_satisfied(version, specs):
    opmap = {'==' : lambda x, y: x == y, '!=' : lambda x, y: x != y,
             '<=' : lambda x, y: x <= y, '>=' : lambda x, y: x >= y,
             '<': lambda x, y: x < y, '>' : lambda x, y: x > y}

    return all([opmap[op](version, sv) for (op, sv) in specs])

def generate_tarball_lorry(requirement):
    try:
        client = xmlrpclib.ServerProxy(PYPI_URL)
        releases = client.package_releases(requirement.name)
    except Exception as e:
        error("Couldn't fetch release data:", e)

    if len(releases) == 0:
        error("Couldn't find any releases for package %s" % requirement.name)

    releases = [v for v in releases if specs_satisfied(v, requirement.specs)]

    if len(releases) == 0:
        error("Couldn't find any releases that satisfy version constraints: %s"
              % requirement.specs)

    def get_description(release):
        return client.release_data(requirement.name,
                                   release)['name'] + ' ' + release

    choice = (ask_user(client, releases,
                       get_description, prompt='Select release: ')
                       if len(releases) > 1 else 0)
    release_version = releases[choice]

    print('Fetching urls for package %s with version %s'
          % (requirement.name, release_version))

    try:
        urls = client.release_urls(requirement.name, release_version)
    except Exception as e:
        error("Couldn't fetch release urls:", e)

    tarball_urls = filter_urls(urls)

    if len(tarball_urls) > 0:
        urls = tarball_urls
    elif len(urls) > 0:
        warn("None of these urls look like tarballs:")
        for url in urls:
            warn("\t%s", url)
        error("Cannot proceed")
    else:
        error("Couldn't find any download urls for package")

    choice = (ask_user(client, urls, lambda url: url['url'],
                       prompt='Select url: ') if len(urls) > 1 else 0)
    url = urls[choice]['url']

    return make_tarball_lorry(requirement.name, url)

def str_repo_lorry(package_name, repo_type, url):
    return json.dumps({package_name.lower(): {'type': repo_type, 'url': url}},
                      indent=4, sort_keys=True)

if __name__ == '__main__':
    max_args = 2

    if len(sys.argv) != max_args:
        # TODO explain the format of python requirements
        # warn the user that they probably want to quote their arg
        # > < will be interpreted as redirection by the shell
        print('usage: %s requirement'
              % sys.argv[0], file=sys.stderr)
        sys.exit(1)

    # TODO: We could take multiple reqs easily enough
    req = parser.requirements.parse(sys.argv[1]).next()

    metadata = fetch_package_metadata(req.name)
    info = metadata['info']

    repo_type = (find_repo_type(info['home_page'])
                 if 'home_page' in info else None)

    print(str_repo_lorry(req.name, repo_type, info['home_page'])
            if repo_type else generate_tarball_lorry(req))
