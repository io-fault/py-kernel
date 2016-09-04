"""
Sector Daemon management library.

In order to manage a daemon's execution, control interfaces must be supported to manage
initialization and termination sequences. &.libdaemon provides access to these control
interfaces so that the implementation can focus on regular operations.

&.libdaemon also provides a message bus for message passing and synchronization primitives
among process forks. Given appropriate configuration, groups outside the daemon's set
can be specified to allow message passing and synchronization across sites.

[ Features ]

	- Set of forked processes or one if distribution is one.
	- Arbitration for fork-local synchronization.

/control - Control Signalling Interface
	/terminate
		Power Down the [system] Process by terminating the root sectors.
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
import importlib

from . import library as libio
from . import http

from ..chronometry import library as libtime
from ..routes import library as libroutes
from ..system import library as libsys
from ..web import libhttpd

class Commands(libhttpd.Index):
	"""
	HTTP Control API used by control (Host) connections.
	"""

	def __init__(self):
		pass

	@libhttpd.Resource.method()
	def inject(self, resource, parameters) -> str:
		"""
		Inject arbitrary code for introspective purposes.
		"""

		return None

	@libhttpd.Resource.method()
	def report(self, resource, parameters):
		"""
		Build a report describing the process.
		"""

		return '\n'.join([
			'\n'.join(libio.format(unit.identity, unit))

			for unit in [
				x[None] for x in
				libio.system.__process_index__.values()
			]
		])

	@libhttpd.Resource.method()
	def timestamp(self, resource, parameters):
		"""
		Return the faultd's perception of time.
		"""
		return libtime.now().select("iso")

	@libhttpd.Resource.method()
	def terminate(self, resource, parameters):
		"""
		Issue &Unit.terminate after the Connection's Sector exits.
		"""

		unit = self.context.association()
		unit.result = libsys.SystemExit.exiting_for_restart

		self.atexit(lambda x: unit.terminate())

		return 'terminating\n'

	@libhttpd.Resource.method()
	def __resource__(self, resource, path, query, px):
		pass

def rt_load_unit_sector(unit, sector_import, Sector=None, location=('bin',)):
	"""
	Load a sector into (iri)`rt://unit/bin` named by the module's full name
	and the following attribute path.
	"""
	global libio, libroutes, importlib

	# Path to SectorModules
	sr, attpath = libroutes.Import.from_attributes(sector_import)
	mod = importlib.import_module(str(sr))

	s = (Sector or libio.Sector)()
	s.subresource(unit)
	unit.place(s, 'bin', sector_import)
	s.actuate()

	y = mod
	for x in attpath:
		y = getattr(y, x)

	return s, y, sector_import

def rt_load_argument_sectors(unit):
	"""
	Load the initialization selections from the system arguments as sectors.
	"""
	global libio, libroutes, rt_load_unit_sector

	inv = unit.context.process.invocation
	args = inv.parameters['system']['arguments']

	for sectors_module in args:
		yield rt_load_unit_sector(unit, sectors_module)

class Control(libio.Interface):
	"""
	Control processor that manages the concurrency of an IO process and the control
	interfaces thereof.

	&Control handles both the controlling process and the workers
	created with (system:manual)&fork calls.
	"""

	def __init__(self):
		super().__init__()

		self.fork_id = None # > 0 in slaves
		self.fork_id_to_subprocess = {}
		self.subprocess_to_fork_id = {}

		# FUTURE connections to coprocesses
		self.connections = {}

	def actuate(self):
		assert self.fork_id is None # forks should not call actuate. ever.
		self.fork_id = 0 # root is zero
		super().actuate()

		unit = self.controller
		unit.atexit(self.ctl_sectors_exit)

		# Manage termination of fork processes.
		#self.context.process.system_event_connect(('signal', 'terminate'), self, self.system_terminate)

		# stdout is closed; redirect print to stderr with a prefix
		import builtins
		dprint = builtins.print

		def errprint(*args, **kw):
			"""
			Override for print to default to standard error and qualify origin in output.
			"""
			global libsys, sys
			nonlocal dprint, self

			kw.setdefault('file', sys.stderr)
			kw.setdefault('flush', True)
			sid = self.context.association().identity
			fid = self.fork_id
			pid = libsys.current_process_id
			iso = libtime.now().select('iso')

			dprint("%s [builtins.print(%s:%d/%d)]"%(iso, sid, fid, pid), *args, **kw)

		builtins.print = errprint

		self.route = libroutes.File.from_cwd()

		cid = (self.route / 'if')
		cid.init("directory")

		# address portion of the local socket
		cid = cid.fullpath

		unit = self.context.association()
		ports = unit.ports
		self.service = unit.u_index[('dev', 'service',)]

		for bsector, root, origin in rt_load_argument_sectors(unit):
			bsector.acquire(libio.Call.partial(root, bsector))

		# The control interface must be shut down in the forks.
		# The interchange is voided the moment we get into the fork,
		# despite the presence of Flows accepting sockets, the
		# traffic instance in the subprocess will know nothing about it.
		ports.bind(('control', 0), libio.endpoint('local', cid, "0"))
		self.ctl_install_control(0)

		# Bind the requested interfaces from invocation.xml
		for slot, binds in self.service.interfaces.items():
			ports.bind(slot, *itertools.starmap(libio.endpoint, binds))

		# forking
		forks = self.concurrency = self.service.concurrency

		# acquire file system sockets before forking.
		# allows us to avoid some synchronizing logic after forking.
		for i in range(1, forks+1):
			ports.bind(('control', i), libio.endpoint('local', cid, str(i)))

		for i in range(1, forks+1):
			self.ctl_fork(i, initial=True)

	def ctl_sectors_exit(self, unit):
		"""
		Remove the control's interface socket before exiting the process.
		"""

		# Clean up file system socket on exit.
		fss = self.route / 'if' / str(self.fork_id)
		fss.void()

	def ctl_fork_exit(self, sub):
		"""
		Called when a fork's exit has been received by the controlling process.
		"""

		fid = self.subprocess_to_fork_id.pop(sub)
		self.fork_id_to_subprocess[fid] = None

		pid, delta = sub.only
		typ, code, cored = delta

		# Restart Immediately. This will eventually get throttled.
		if fid < self.service.concurrency:
			self.ctl_fork(fid)

	def ctl_fork(self, fid, initial=False):
		"""
		Fork the process using the given &fid as its identifier.
		"""
		assert self.fork_id == 0 # should only be called by master

		import signal as s

		filters = [functools.partial(s.signal, x, s.SIG_IGN) for x in (s.SIGTERM, s.SIGINT)]

		sed = self.context.process.system_event_disconnect
		#filters.append(functools.partial(sed, ('signal', 'terminal.query')))
		del sed, s

		pid = self.context.process.fork(filters, functools.partial(self.ctl_forked, fid, initial))
		del filters

		##
		# PARENT ONLY FROM HERE; child jumps into &ctl_forked
		##

		# Record forked process.
		subprocess = libio.Subprocess(pid)

		self.subprocess_to_fork_id[subprocess] = fid
		self.fork_id_to_subprocess[fid] = subprocess

		self.controller.dispatch(subprocess)
		subprocess.atexit(self.ctl_fork_exit)

	def ctl_forked(self, fork_id, initial=False):
		"""
		Initial invocation of a newly forked process.
		Indirectly invoked by &ctl_fork through &.system.Process.fork.
		"""

		self.fork_id = fork_id

		unit = self.context.association()

		# All necessary parameters from /dev/service should have been inherited.
		# Service is exclusive property of the controlling process.
		del unit.u_index[('dev', 'service',)]
		del self.service

		os.environ["SECTORS"] = str(fork_id)

		# Setup control interface before subactuate
		self.ctl_install_control(fork_id)

		ports = unit.ports

		# close out the control interfaces of the parent and siblings
		s = set(range(self.concurrency+1))
		s.discard(fork_id)
		for x in s:
			ports.discard(('control', x))

		# The process needs to connect to the other forked processes
		# The initial indicator tells
		if initial:
			# connect using a specific pattern
			# 1: 2, 3, 4, ..., n
			# 2: 3, 4, ..., n
			# 3: 4, ..., n
			# 4: ..., n (opened by priors)
			# n: none (all others have connected to it)

			pass
		else:
			# connect to all coprocesses

			pass

		self.ctl_subactuate()

	def ctl_install_control(self, fid:int):
		"""
		Setup the HTTP interface for controlling and monitoring the daemon.

		[ Parameters ]
		/fid
			The fork-id; the number associated with the fork.
		"""

		sector = self.controller
		host = self.ctl_host = libhttpd.Host()
		host.h_update_mounts({'/sys/': Commands()})
		host.h_update_names('control')
		host.h_options = {}

		si = libio.System(http.Server, host, host.h_route, (), ('control', fid))
		sector.process((host, si))

	def ctl_subactuate(self):
		"""
		Called to actuate the sector daemons installed into (rt:path)`/bin`

		Separated from &actuate for process forks.
		"""

		unit = self.context.association()
		enqueue = self.context.enqueue
		enqueue(self.context._sys_traffic_flush)

		exe_index = unit.u_hierarchy['bin']

		for x in exe_index:
			exe = unit.u_index[('bin', x)]
			enqueue(exe.actuate)

	def ctl_terminate_worker(self):
		"""
		"""
		pass

	def ctl_system_terminate(self):
		"""
		Received termination request from system.
		"""
		pass

	def ctl_system_interrupt(self):
		"""
		Received interrupt request from system.
		"""
		pass
