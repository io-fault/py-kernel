"""
Sector Daemon management library.

In order to manage a daemon's execution, control interfaces must be support to manage
initialization and termination sequences.

Additionally, libdaemon provides a message bus for communicating with other daemons of the
same configuration.



#!text
	/sectors [/bin/ contains the unactuated module set; /control is sectord]
	|- worker1 [/bin/ contains the actuated module set; /control is sectord with non-zero fork_id]
	|- worker2
	|- ...
	|- workerN
	/daemon
	|- [Arbitrary process tree.]
	...
	/root [psuedo service representing the root service]

[ Features ]

	- Set of forked processes or one if distribution is one.
	- Arbitration for locks.

/control - Control Signalling Interface
	/terminate
		Power Down the [system] Process
	/inject
		Introspection Interface; debugging; profiling

/circulate - Broadcasting Interface
	/coprocess
		Channel to other Processes in the daemon. (maybe virtual/implicit)
	/site
		System Sets are closely connected (same system or network)
	/application
		Set of sites; the entire graph

/message - Direct Messaging
	/fork-id
		.
	/site/machine-id/fork-id
		.
	/graph/site-id/machine-id/fork-id
		.
"""

import os
import sys
import functools
import collections
import itertools

from . import library as libio
from . import libhttp

from ..routes import library as libroutes
from ..system import library as libsys

class Commands(libhttp.Index):
	"""
	HTTP Control API used by control (Host) connections.
	"""

	def __init__(self):
		pass

	@libhttp.Resource.method()
	def inject(self, resource, parameters) -> str:
		"""
		Inject arbitrary code for introspective purposes.
		"""

		return None

	@libhttp.Resource.method()
	def report(self, resource, parameters):
		"""
		Build a report describing the process.
		"""

		return None

	@libhttp.Resource.method()
	def timestamp(self, resource, parameters):
		"Return the faultd's perception of time."
		return libtime.now().select("iso")

	@libhttp.Resource.method()
	def terminate(self, resource, parameters):
		"""
		Issue &Unit.terminate after the Connection's Sector exits.
		"""

		unit = self.context.association()
		unit.result = libsys.SystemExit.exiting_for_restart

		self.atexit(lambda x: unit.terminate())

		return 'terminating\n'

	@libhttp.Resource.method()
	def __resource__(self, resource, path, query, px):
		pass

class Control(libio.Control):
	"""
	Control Sector that manages the concurrency of an IO process.
	"""

	def __init__(self, modules):
		super().__init__()

		self.modules = modules
		self.fork_id = None # > 0 in slaves
		self.fork_id_to_subprocess = {}
		self.subprocess_to_fork_id = {}

		# FUTURE connections to coprocesses
		self.connections = {}

	def exit(self, unit):
		# Clean up file system socket on exit.

		fss = self.route / 'if' / str(self.fork_id)
		fss.void()

	def fork_exit(self, sub):
		"""
		Called when a fork exits with the &Subprocess instance as its parameter.
		"""

		fid = self.subprocess_to_fork_id.pop(sub)
		self.fork_id_to_subprocess[fid] = None

		# Restart Immediately if it's still within the distribution.
		if fid < self.service.concurrency:
			self.fork(fid)

	def fork(self, fid, initial=False):
		"""
		Fork the process using the given &fid as its identifier.
		"""
		assert self.fork_id == 0 # should only be called by master

		pid = self.context.process.fork(functools.partial(self.forked, fid, initial))

		subprocess = libio.Subprocess(pid)

		self.subprocess_to_fork_id[subprocess] = fid
		self.fork_id_to_subprocess[fid] = subprocess

		self.dispatch(subprocess)
		subprocess.atexit(self.fork_exit)

	def forked(self, fork_id, initial=False):
		"""
		Initial invocation of a newly forked process. Indirectly invoked by &fork.
		"""

		unit = self.context.association()

		self.fork_id = fork_id
		os.environ["SECTORS"] = str(fork_id)

		# Setup control before subactuate
		self.control(fork_id)

		ports = unit.ports

		# close out the control interfaces of the parent and siblings
		s = set(range(self.service.concurrency+1))
		s.discard(fork_id)
		for x in s:
			ports.discard(('control', x))

		# The process needs to connect to the other forked processes
		# The initial indicator tells
		if initial:
			# connect using a specific pattern
			# 1: 2, 3, 4, ..., n
			# 2: 3, 4, ..., n
			# 3: 4, ...., n
			# 4: ..., n
			# n: none (all others have connected to it)

			pass
		else:
			# connect to all coprocesses

			pass

		self.subactuate()

	def control(self, fid:int):
		"""
		Acquire the control interface and associate it with an libhttp.Interface().

		[ Parameters ]
		/fid
			The fork-id; the number associated with the fork.
		"""

		control_host = libhttp.Host({'/sys/': Commands()}, 'control')

		hi = libhttp.Interface(('control', fid), libhttp.Interface.accept)
		hi.install(control_host)
		self.dispatch(hi)

	def subactuate(self):
		"""
		Called to actuate the primary functionality Sectors installed into "/bin".
		Separated from &actuate for supporting forks.
		"""

		unit = self.context.association()
		enqueue = self.context.enqueue
		enqueue(self.context._flush_attachments)

		exe_index = unit.hierarchy['bin']

		for x in exe_index:
			exe = unit.index[('bin', x)]
			enqueue(exe.actuate)

	def place_sectors(self, override=None, Sector=libio.Module):
		unit = self.context.association()

		if override is None:
			inv = self.context.process.invocation
			args = inv.parameters['system']['arguments']
		else:
			override = args

		# Path to SectorModules
		for sectors_module in args:
			sm = Sector()
			sm.subresource(unit)
			Sector.requisite(sm, libroutes.Import.from_fullname(sectors_module))
			unit.place(sm, 'bin', sectors_module)

	def actuate(self):
		assert self.fork_id is None # forks should not call actuate. ever.
		self.fork_id = 0 # root is zero
		super().actuate()

		# stdout is closed; redirect print to stderr with a prefix
		import builtins
		dprint = builtins.print

		def errprint(*args, **kw):
			'Override for print to default to standard error and qualify origin in output.'
			global libsys, sys
			nonlocal dprint, self

			kw.setdefault('file', sys.stderr)
			kw.setdefault('flush', True)
			sid = self.context.association().identity
			fid = self.fork_id
			pid = libsys.current_process_id

			dprint("[builtins.print(%s:%d/%d)]:"%(sid,fid,pid), *args, **kw)

		builtins.print=errprint

		self.route = libroutes.File.from_cwd()

		cid = (self.route / 'if')
		cid.init("directory")

		# address portion of the local socket
		cid = cid.fullpath

		unit = self.context.association()
		ports = unit.ports
		self.service = unit.index[("service",)]

		self.place_sectors()

		# The control interface must be shut down in the forks.
		# The interchang is voided the moment we get into the fork,
		# despite the presence of Flows accepting sockets, the
		# traffic instance in the subprocess will know nothing about it.
		ports.bind(('control', 0), libio.endpoint('local', cid, "0"))
		self.control(0)

		# Bind the requested interfaces from invocation.xml
		for slot, binds in self.service.interfaces.items():
			ports.bind(slot, *itertools.starmap(libio.endpoint, binds))

		forks = self.service.concurrency
		if not forks or forks == 1:
			# Directly actuate; only one process in this sectord.
			self.context.enqueue(self.subactuate)
		else:
			# forking

			# acquire file system sockets before forking.
			# allows us to avoid some synchronizing logic after forking.
			for i in range(1, forks+1):
				ports.bind(('control', i), libio.endpoint('local', cid, str(i)))

			for i in range(1, forks+1):
				self.fork(i, initial=True)
