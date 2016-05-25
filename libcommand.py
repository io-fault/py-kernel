"""
System Command Execution of a &.library.Unit.

Provides the construction of &.library.Unit instance for an
application that is to be ran as a system command.
"""

import sys
import inspect
import functools

from . import library as libio

def initialize(unit):
	"""
	Initialize the unit with a new sector running the command's main.
	If main is a generator, it will be invoked as a coroutine.
	"""
	global libio

	# main/only sector; no (daemon) control interfaces
	s = libio.Sector()
	s.subresource(unit)
	unit.place(s, "bin", "main")

	mod = sys.modules['__main__']
	main = mod.main
	libs = getattr(mod, 'libraries', ())

	for name in libs:
		# XXX: need some environment configuration for managing default libraries.
		if 0:
			unit.link(name)
			lib = libio.Library.from_fullname(path)
			unit.place(lib, "lib", name)

	if inspect.isgeneratorfunction(main):
		main_proc = libio.Coroutine(main)
	else:
		main_proc = libio.Call.partial(main)

	enqueue = unit.context.enqueue
	enqueue(s.actuate)
	enqueue(functools.partial(s.dispatch, main_proc))

def execute(name='__main__'):
	"""
	Ran by script depending on libcommand:

	#!/pl/python
		if __name__ == '__main__':
			libcommand.execute()
	"""

	libio.execute(command=(initialize,))
