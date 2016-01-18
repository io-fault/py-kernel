"""
Public acccess to common Processing classes and process management classes.
"""

from ..fork import library as libfork
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
Controller = core.Controller

Resource = core.Resource
Extension = core.Extension
Device = core.Device

Transformer = core.Transformer
Functional = core.Functional
Reactor = core.Reactor # Transformer
Parallel = core.Parallel
Generator = core.Generator

Collect = core.Collect
Iterate = core.Iterate
Spawn = core.Spawn

Terminal = core.Terminal
Trace = core.Trace

Processor = core.Processor
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

	sysinv = libfork.Invocation.system()
	sp = process.Representation.spawn(sysinv, Unit, units, identity=ident)
	# import root function
	libfork.control(sp.boot)
