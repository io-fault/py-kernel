"""
Public acccess to common Processing classes and process management classes.
"""
import sys

from ..system import library as libsys
from . import core
from . import process

# core exports
endpoint = core.endpoint
#Port = core.Port
Endpoint = core.Endpoint
Local = core.Local
Projection = core.Projection
Layer = core.Layer # Base class for all layer contexts
Interface = core.Interface
Connection = core.Connection

Resource = core.Resource
Extension = core.Extension
Device = core.Device

KernelPort = core.KernelPort
Transports = core.Transports

Transformer = core.Transformer
Functional = core.Functional
Reactor = core.Reactor # Transformer
Parallel = core.Parallel

Collect = core.Collect
Iterate = core.Iterate
Spawn = core.Spawn

Terminal = core.Terminal
Trace = core.Trace

Processor = core.Processor
Nothing = core.Nothing
Unit = core.Unit
Sector = core.Sector
Module = core.Module
Control = core.Control
Subprocess = core.Subprocess
Scheduler = core.Scheduler

# Common Processors inside Sectors
Coroutine = core.Coroutine
Flow = core.Flow
Thread = core.Thread
Call = core.Call
Protocol = core.Protocol
QueueProtocol = core.QueueProtocol

Null = core.Null

def context(max_depth=None):
	"""
	Finds the &Processor instance that caused the function to be invoked.

	Used to discover the execution context when it wasn't explicitly
	passed forward.
	"""
	global sys

	f = sys._getframe().f_back
	while f:
		if f.f_code.co_name == '_fio_fault_trap':
			# found the _fio_fault_trap method.
			# return the processor that caused this to be executed.
			return f.f_locals['self']
		f = f.f_back

	return None # (context) Processor is not available in this stack.

def pipeline(sector, kpipeline, input=None, output=None):
	"""
	Execute a &..system.library.KPipeline object building an IO instance
	from the input and output file descriptors associated with the
	first and last processes as described by its &..system.library.Pipeline.

	Additionally, a mapping of standard errors will be produced.
	Returns a tuple, `(input, output, stderrs)`.

	Where stderrs is a sequence of file descriptors of the standard error of each process
	participating in the pipeline.
	"""

	ctx = sector.context
	pl = kpipeline()

	try:
		input = ctx.acquire('output', pl.input)
		output = self.acquire('input', pl.output)

		stderr = list(self.acquire('input', pl.standard_errors))

		sp = Subprocess(*pl.process_identifiers)
	except:
		pl.void()
		raise

	return sp, input, output, stderr

def execute(*identity, **units):
	"""
	Initialize a &process.Representation to manage the invocation from the (operating) system.
	This is the appropriate way to invoke a &..io process from an executable module that
	wants more control over the initialization process than what is offered by
	&.libcommand.

	#!/pl/python
		libio.execute(unit_name = (unit_initialization,))

	Creates a &Unit instance that is passed to the initialization function where
	its hierarchy is then populated with &Sector instances.
	"""

	if identity:
		ident, = identity
	else:
		ident = 'root'

	sysinv = libsys.Invocation.system()
	sp = process.Representation.spawn(sysinv, Unit, units, identity=ident)
	# import root function
	libsys.control(sp.boot)
