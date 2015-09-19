"""
Command Execution Unit

Provides the necessary infrastructure for implementing and executing
command scripts.
"""

import sys
import inspect

from . import library

def init(unit):
	"""
	Initialize the unit with a new sector running the command's main.
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

def execute():
	"""
	Ran by script.
	"""

	library.execute(command=(init,))
