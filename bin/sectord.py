"""
fault.io sector daemon. Primarily depends on &.io.libdaemon.
"""

import sys
import os

def initialize(unit):
	"""
	Initialize the sectord process.

	Load ports from the invocation configuration,
	setup libdaemon.Control for control interfaces and forking.

	The module paths provided as arguments will be used as sector
	modules loaded into "/bin".
	"""

	from .. import libdaemon
	from .. import libservice
	from .. import library

	from ...routes import library as routeslib

	# /dev/ports
	library.core.Ports.load(unit)

	proc = unit.context.process
	modules = proc.invocation.parameters

	r = routeslib.File.from_cwd()
	s = libservice.Service(r.container, r.identity)
	s.load() # parameters

	root_sector = libdaemon.Control(modules)
	unit.place(root_sector, "control")
	unit.place(s, "service")
	root_sector.subresource(unit)
	root_sector.actuate()

if __name__ == '__main__':
	from .. import library
	library.execute('sectord', **{
		os.environ.get('SERVICE_NAME', 'sectord'): (initialize,)
	})
