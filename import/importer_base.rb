#!/usr/bin/env ruby
#
# Base class for importers written in Ruby
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

require 'json'
require 'logger'
require 'yaml'

module Importer
  class Base
    def log
      @logger ||= create_logger
    end

    def error(message)
      log.error(message)
      STDERR.puts(message)
    end

    def write_lorry(file, lorry)
      format_options = { :indent => '    ' }
      file.puts(JSON.pretty_generate(lorry, format_options))
    end

    def write_morph(file, morph)
      file.write(YAML.dump(morph))
    end

    private

    def create_logger
      # Use the logger that was passed in from the 'main' import process, if
      # detected.
      log_fd = ENV['MORPH_LOG_FD']
      if log_fd
        log_stream = IO.new(Integer(log_fd), 'w')
        logger = Logger.new(log_stream)
        logger.level = Logger::DEBUG
        logger.formatter = proc { |severity, datetime, progname, msg| "#{msg}\n" }
      else
        logger = Logger.new('/dev/null')
      end
      logger
    end
  end
end
