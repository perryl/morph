#!/usr/bin/env python

from __future__ import print_function

import requests
import json
import sys

expected_content_type = 'text/html'

r = requests.get('https://pypi.python.org/simple')

if r.status_code != 200:
	print("Couldn't fetch list of packages", file=sys.stderr)
	sys.exit(1)

content_type, _ = r.headers['content-type'].split(';')

if content_type != expected_content_type:
	print("Cannot parse input data: expected %s and got %s"
		  % (expected_content_type, content_type), file=sys.stderr)

lines = [line for line in r.text.split('\n') if re.match('<a href=')]

for line in lines:
	print(line)