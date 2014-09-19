# Copyright (C) 2013 - 2014 Codethink Limited
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


'''Version information retrieved either from the package data, or the
   git repository the library is being run from.

   It is an error to run morph without this version information, since
   it makes it impossible to reproduce any Systems that are built.
'''


import subprocess
import os

import cliapp


try:
    import pkgutil
    version = pkgutil.get_data('morphlib', 'version')
    commit = pkgutil.get_data('morphlib', 'commit')
    tree = pkgutil.get_data('morphlib', 'tree')
    ref = pkgutil.get_data('morphlib', 'ref')
except IOError, e:
    from os.path import dirname
    def run_git(*args):
        command = ['git'] + list(args)
        p = subprocess.Popen(command,
                             cwd=os.path.dirname(__file__),
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        o = p.communicate()
        if p.returncode:
            raise subprocess.CalledProcessError(p.returncode,
                                                command)
        return o[0].strip()

    try:
        version = run_git('describe', '--abbrev=40', '--always',
                         '--dirty=-unreproducible',
                         '--match=DO-NOT-MATCH-ANY-TAGS')
        commit = run_git('rev-parse', 'HEAD^{commit}')
        tree = run_git('rev-parse', 'HEAD^{tree}')
        ref = run_git('rev-parse', '--symbolic-full-name', 'HEAD')
    except cliapp.AppException:
        raise cliapp.AppException("morphlib version could not be determined")
