# Copyright (C) 2011-2016  Codethink Limited
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


'''Baserock library.'''


# Import yaml if available. This can go away once Baserock has made a
# release that includes yaml (also in its staging filler).
try:
    import yaml
except ImportError:
    got_yaml = False
    class YAMLError(Exception):
        pass
else:
    got_yaml = True
    YAMLError = yaml.YAMLError


import cliapp

import gitversion

__version__ = gitversion.version


# List of architectures that Morph supports
valid_archs = ['armv5l', 'armv7l', 'armv7lhf', 'armv7b', 'testarch', 'x86_32',
               'x86_64', 'ppc64', 'armv8l64', 'armv8b64', 'mips32l',
               'mips32b', 'mips64l', 'mips64b']

class Error(cliapp.AppException):

    '''Base for all morph exceptions that cause user-visible messages.'''


import artifact
import artifactcachereference
import artifactresolver
import artifactsplitrule
import branchmanager
import bins
import buildbranch
import buildcommand
import buildenvironment
import buildsystem
import builder
import cachekeycomputer
import cmdline_parse_utils
import defaults
import definitions_repo
import definitions_version
import extensions
import extractedtarball
import fsutils
import git
import gitdir
import gitindex
import localartifactcache
import mountableimage
import morphologyfinder
import morphology
import morphloader
import morphset
import remoteartifactcache
import repoaliasresolver
import repocache
import savefile
import source
import sourcepool
import sourceresolver
import stagingarea
import stopwatch
import util

import yamlparse

import writeexts

import app  # this needs to be last
