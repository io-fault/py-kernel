"""
# Sector daemon used to manage a set of &.library.Sector instances
# that run a daemon process.
"""

def initialize(unit):
	"""
	# Initialize the sectord process inside the given &unit.

	# Load ports from the invocation configuration,
	# setup &.libdaemon.Control for control interfaces and forking.

	# The module paths provided as arguments will be used as sector
	# modules loaded into "/bin".
	"""

	import functools
	from .. import libdaemon
	from .. import library as libio

	from ...routes import library as libroutes

	# /dev/ports for listening sockets and datagrams.
	libio.Ports.connect(unit)

	proc = unit.context.process

	r = libroutes.File.from_cwd()
	unit.place(None, "dev", "service")

	ctl = libdaemon.Control()
	root_sector = libio.System.create(ctl)

	# &.libdaemon.Control.actuate does most of the work.
	unit.place(root_sector, "control")
	root_sector.subresource(unit)
	root_sector.actuate()

def main():
	"""
	# Execute as a sectord process.
	"""
	import os
	from .. import library as libio
	libio.execute('sectord', **{
		os.environ.get('SERVICE_NAME', 'sectord'): (initialize,)
	})

if __name__ == '__main__':
	main()
