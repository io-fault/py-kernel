"""
System Command Execution &.library.Unit.

Provides the construction of &.library.Unit instance for an
application that is to be ran as a system command.
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

	#!/pl/python
		if __name__ == '__main__':
			libcommand.execute()
	"""

	library.execute(command=(initialize,))
