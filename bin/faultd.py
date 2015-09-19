"""
Execute the fault (root) daemon for managing a set of services.
"""

import sys
import os

def initialize(unit):
	from .. import libroot
	from .. import libservice
	from .. import library

	# init listening interfaces
	library.core.Ports.load(unit)
	command_params = unit.context.process.invocation.parameters

	# Root Daemon Control
	root_sector = libroot.Control(libservice.identify_route())

	unit.place(root_sector, "control")
	root_sector.subresource(unit)
	unit.context.enqueue(root_sector.actuate)

if __name__ == '__main__':
	# Some redundancy here for supporting faultd hardlinks.

	if os.environ.get('FAULTD') is None:
		params = sys.argv[1:]
		os.environ['FAULTD'] = str(os.getpid())
		py = os.environ['PYTHON'] = sys.executable

		from .. import libservice
		r = libservice.identify_route()
		rs = libservice.Service(r, 'root')
		if not rs.exists():
			rs.create('root')
			rs.executable = sys.executable
			rs.enabled = True
			rs.parameters = ['-m', __package__+'.faultd'] + params
			rs.store()
		else:
			rs.prepare()

		rs.load()

		path, command = rs.execution()

		# execl in order to rename the process to faultd in the process list
		os.execl(path, *command)
		assert False # should not reach after execl

	from .. import library
	library.execute(faultd = (initialize,))
