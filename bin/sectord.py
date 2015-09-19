"""
fault.io sector daemon. Primarily depends on &.io.libdaemon.
"""

import sys
import os

def initialize(unit):
	"Initialize the sectord process."

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
	s.load()

	root_sector = libdaemon.Control(modules)
	unit.place(root_sector, "control")
	unit.place(s, "service")
	root_sector.subresource(unit)
	root_sector.actuate()

	from ...chronometry import library as timelib
	def dtask():
		sys.stderr.buffer.write(b"AH DEFERRED!\n")
		sys.stderr.buffer.write(os.environ.get("FGLOBAL").encode('utf-8')+b'\n')
		sys.stderr.flush()

	unit.scheduler.defer(timelib.Measure.of(second=4), dtask)

if __name__ == '__main__':
	from .. import library
	library.execute('sectord', **{
		os.environ.get('SERVICE_NAME', 'sectord'): (initialize,)
	})
