"""
Command Execution Unit

Support for modules intended to be fault.io based scripts.
"""

import sys
import inspect

from . import library

def initialize(unit):
	"""
	Initialize the unit with a new sector running the command's main.
	If main is a generator, it will be invoked as a coroutine.
	"""

	# main/only sector; no (daemon) control interfaces
	s = library.Sector()
	s.subresource(unit)
	unit.place(s, "bin", "main")

	mod = sys.modules['__main__']
	main = mod.main
	libs = getattr(mod, 'libraries', ())

	for name in libs:
		# XXX: need some environment configuration for managing default libraries.
		if 0:
			unit.link(name)
			lib = library.Library.from_fullname(path)
			unit.place(lib, "lib", name)

	if inspect.isgeneratorfunction(main):
		s.requisite(library.Coroutine.from_callable(main))
	else:
		s.requisite(library.Call(main))

	unit.context.enqueue(s.actuate)

def execute(name='__main__'):
	"""
	Ran by script depending on libcommand:

		if __name__ == '__main__':
			libcommand.execute()
	"""

	library.execute(command=(initialize,))
