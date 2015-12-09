"""
Daemon management infrastructure.

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
	/sleep
		Cause the task queue to pause for the given interval
	/inject
		Introspection Interface; debugging; profiling

/circulate - Broadcasting Interface
	/daemon
		Channel to other Processes in the daemon. (maybe virtual/implicit)
	/site
		System Sets are closely connected (same system or network)
	/graph
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

from . import library
from . import http

from ..routes import library as routeslib
from ..fork import library as forklib


class HTTP(library.Sector):
	"""
	Request-Accept callbacks and job management for HTTP.
	"""

	@http.resource()
	def control_index(self, request, response, input):
		pass

	@http.resource(limit=0)
	def terminate(self, request, response, input):
		"""
		Issue &Unit.terminate after the Connection's Sector exits.
		"""

		unit = self.context.association()
		unit.result = forklib.SystemExit.exiting_for_restart

		self.atexit(lambda x: unit.terminate())

		return 'terminating\n'

	@http.resource(limit=1024)
	def sleep(self, request, response, input):
		pass

	@http.resource(limit=1024)
	def inject(self, request, response, input):
		pass

	@http.resource(limit=0)
	def circulate_index(self, request, response, input):
		pass

	@http.resource(limit=1024)
	def circulate_sectors(self, request, response, input):
		pass

	@http.resource(limit=0)
	def circulate_site(self, request, response, input):
		pass

	@http.resource()
	def circulate_graph(self, request, response, input):
		pass

	@http.resource()
	def report(self, request, response, input):
		pass

	index = {
		b'/control': control_index,
		b'/control/terminate': terminate,
		b'/control/sleep': sleep,
		b'/control/inject': inject,
		b'/control/report': report,

		# Message Injection
		b'/circulate': circulate_index,
		b'/circulate/sectors': circulate_sectors,
		b'/circulate/site': circulate_site,
		b'/circulate/graph': circulate_graph,
	}

	def http_request_accept(self, layer, partial=functools.partial):
		request = layer
		response = self.protocol.output_layer()

		ins = self.protocol.distribute
		out = self.protocol.serialize
		out.enqueue(response)

		out_connect = partial(out.connect, response)

		# conditionally provide flow connection callback.
		if request.length is not None:
			ins_connect = partial(ins.connect, request)
		else:
			# there is no content flow
			ins_connect = None

		method = self.index.get(layer.path)
		if method is None:
			response.initiate((request.version, b'404', b'NOT FOUND'))
			if request.terminal:
				response.add_headers([
					(b'Connection', b'close'),
				])

			notfound = b'No such resource.'
			response.add_headers([
				(b'Content-Type', b'text/plain'),
				(b'Content-Length', str(len(notfound)).encode('utf-8'),)
			])

			if request.content:
				ins_connect(library.Null)

			proc = library.Flow()
			i = library.Iterate()
			proc.requisite(i)
			self.dispatch(proc)
			out_connect(proc)
			proc.process([(notfound,)])
		else:
			proc = method(self, request, response, ins_connect, out_connect)
			if proc is not None:
				self.dispatch(proc)

	def http_request_closed(self, layer, flow):
		# called when the input flow of the request
		# has finished; flow will not receive any more events.
		if flow is not None:
			flow.terminate()

		print('request input close: ' + repr((layer, flow)))
		print(self.controller.processors)

	@classmethod
	def http_accept(Class, spawn, packet):
		"""
		Accept an HTTP connection for interacting with the daemon.
		"""

		source, event = packet
		sector = spawn.sector

		# event is a iterable of socket file descriptors
		for fd in event:
			cxn = Class()
			sector.dispatch(cxn)

			with cxn.xact() as xact:
				io = xact.acquire_socket(fd)
				p, fi, fo = http.server_v1(xact, cxn.http_request_accept, cxn.http_request_closed, *io)

				cxn.process((p, fi, fo))
				cxn.protocol = p

class Interface(library.Interface):
	"""
	Sectors Interface for managing interprocess message passing.
	"""

class Control(library.Control):
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

		sp = self.context.process.fork(functools.partial(self.forked, fid, initial))

		self.subprocess_to_fork_id[sp] = fid
		self.fork_id_to_subprocess[fid] = sp

		self.dispatch(sp)
		sp.atexit(self.fork_exit)

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

	def control(self, fid):
		"""
		Acquire the control interface and associate it with an http.Interface().
		"""

		hi = http.Interface()
		hi.requisite(('control', fid), HTTP.http_accept)

		self.dispatch(hi)

	def subactuate(self):
		"""
		Called to actuate the primary functionality Sectors installed into "/bin".
		Separated from &actuate for supporting forks.
		"""

		unit = self.context.association()
		enqueue = self.context.enqueue
		exe_index = unit.hierarchy['bin']

		for x in exe_index:
			exe = unit.index[('bin', x)]
			enqueue(exe.actuate)

	def place_sectors(self, override=None):
		unit = self.context.association()

		if override is None:
			inv = self.context.process.invocation
			args = inv.parameters['system']['arguments']
		else:
			override = args

		# Path to SectorModules
		for sectors_module in args:
			sm = library.core.Executable()
			sm.subresource(unit)
			sm.requisite(routeslib.Import.from_fullname(sectors_module))
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
			global forklib, sys
			nonlocal dprint, self

			kw.setdefault('file', sys.stderr)
			kw.setdefault('flush', True)
			sid = self.context.association().identity
			fid = self.fork_id
			pid = forklib.current_process_id

			dprint("[builtins.print(%s:%d/%d)]:"%(sid,fid,pid), *args, **kw)

		builtins.print=errprint

		self.route = routeslib.File.from_cwd()

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
		ports.bind(('control', 0), library.endpoint('local', cid, "0"))
		self.control(0)

		# Bind the requested interfaces from invocation.xml
		for slot, binds in self.service.interfaces.items():
			ports.bind(slot, *itertools.starmap(library.endpoint, binds))

		forks = self.service.concurrency
		if not forks or forks == 1:
			# Directly actuate; only one process in this sectord.
			self.context.enqueue(self.subactuate)
		else:
			# forking

			# acquire file system sockets before forking.
			# allows us to avoid some synchronizing logic after forking.
			for i in range(1, forks+1):
				ports.bind(('control', i), library.endpoint('local', cid, str(i)))

			for i in range(1, forks+1):
				self.fork(i, initial=True)
