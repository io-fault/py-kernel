"""
Service management daemon for fault.io based applications.

By default, this script resolves the root service from the
&/env/FAULTD_DIRECTORY environment variable. This can be avoided by
importing the module, and using &initialize as a root for a Unit.
"""

import sys
import os

def initialize(unit):
	# Avoid import as it exec() if it's not the faultd hardlink.
	from .. import libroot
	from .. import libservice
	from .. import library

	# init listening interfaces
	library.core.Ports.load(unit)

	# No command line options atm. Maybe an override for the faultd directory.
	command_params = unit.context.process.invocation.parameters

	# Root Daemon Control
	root_sector = libroot.Control(libservice.identify_route())

	unit.place(root_sector, "control")
	root_sector.subresource(unit)
	unit.context.enqueue(root_sector.actuate)

if __name__ == '__main__':
	# Some redundancy here for supporting faultd hardlinks.
	# Hardlinks to python3 are used to make it possible
	# reveal more appropriate names in the process list.

	if os.environ.get('FAULTD') is None:
		# Initial Python Invocation
		# Resolve the hardlink and exec().
		params = sys.argv[1:]
		os.environ['FAULTD'] = str(os.getpid())
		os.environ['PYTHON'] = sys.executable

		from .. import libservice

		r = libservice.identify_route()
		rs = libservice.Service(r, 'root')
		if not rs.exists():
			rs.create('root')
			rs.executable = sys.executable # reveal original executable
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
