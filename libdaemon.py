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

/sys - Control Signalling Interface
	/interrupt
		Interrupt the application sectors causing near immediate shutdown.
	/terminate
		Terminate the application sectors allowing exant work to complete.
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
import typing
import xml.etree.ElementTree as xmllib

from . import library as libio
from . import http

from ..chronometry import library as libtime
from ..routes import library as libroutes
from ..system import library as libsys
from ..web import libhttpd
from ..xml import libfactor

xml_namespaces = {
	"s": "http://fault.io/xml/io.sectors",
}

def restrict_stdio(route):
	"""
	Initialize the file descriptors used for standard I/O
	to point to (system:path)`/dev/null`, and standard error
	to the file selected by the given &route.
	"""
	# rootd logs stderr to critical.log in case of fatal errors.
	with route.open('ab') as f:
		os.dup2(f.fileno(), 2)
	with open(os.devnull) as f:
		os.dup2(f.fileno(), 1)
		os.dup2(f.fileno(), 0)

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
	def interrupt(self, resource, parameters):
		"""
		Issue an &Sector.interrupt to all the execution sectors.
		"""

		for units in libio.system.__process_index__.values():
			unit = units[None]
			unit.result = libsys.SystemExit.exiting_for_restart
			for exe in list(unit.u_hierarchy['bin']):
				sector = unit.u_index[('bin', exe)]
				sector.interrupt()
				unit.exited(sector)

		return 'terminating\n'

	@libhttpd.Resource.method()
	def terminate(self, resource, parameters):
		"""
		Issue &Unit.terminate after the Connection's Sector exits.
		"""

		for units in libio.system.__process_index__.values():
			unit = units[None]
			unit.result = libsys.SystemExit.exiting_for_restart
			for exe in list(unit.u_hierarchy['bin']):
				sector = unit.u_index[('bin', exe)]
				sector.terminate()

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

def extract_sectors_config(document):
	global xml_namespaces

	xr = xmllib.XML(document)
	find = lambda x: xr.find(x, xml_namespaces)
	findall = lambda x: xr.findall(x, xml_namespaces)

	libelements = findall("s:library")
	ifelements = findall("s:interface")
	dist = xr.attrib.get("concurrency", None)

	if libelements:
		libs = [
			(x.attrib["libname"], x.attrib["fullname"])
			for x in list(libelements)
		]
		libs = dict(libs)
	else:
		libs = None

	ifelements = list(ifelements)
	interfaces = {
		ifelement.attrib["identifier"]: set(
			itertools.chain.from_iterable([
				[
					(
						#x.attrib["transport"],
						addrspace.attrib["type"],
						alloc.attrib["address"], alloc.attrib["port"]
					)
					for alloc in addrspace
				]
				for addrspace in ifelement
			])
		)
		for ifelement in ifelements
	}

	struct = {
		'libraries': libs,
		'interfaces': interfaces,
		'concurrency': None if dist is None else int(dist),
	}

	return struct

def serialize_sectors(struct,
		encoding="ascii",
		namespace=xml_namespaces['s'],
		chain=itertools.chain.from_iterable,
	):
	import collections
	from ..xml import library as libxml
	ifs = {}

	for slot, allocs in struct.get('interfaces', ()).items():
		slot_allocs = ifs[slot] = collections.defaultdict(list)
		for alloc in allocs:
			slot_allocs[alloc.protocol].append((alloc.address, alloc.port))

	xmlctx = libxml.Serialization()

	return xmlctx.root('sectors',
		chain((
			xmlctx.element('libraries',
				chain(
					xmlctx.element('module', None, ('libname', x), ('fullname', fn))
					for x, fn in (struct.get('libraries', None) or {}).items()
				)
			),
			chain(
				xmlctx.element('interface',
					chain(
						xmlctx.element('address.space',
							chain(
								xmlctx.element('allocate', None,
									('address', address),
									('port', port)
								)
								for address, port in allocs
							),
							('type', addrspace),
						)
						for addrspace, allocs in spaces.items()
					),
					('identifier', slot),
				)
				for slot, spaces in ifs.items()
			),
		)),
		('concurrency', struct.get('concurrency')),
		namespace = namespace,
	)

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
		cidstr = cid.fullpath

		unit = self.context.association()
		ports = unit.ports

		for bsector, root, origin in rt_load_argument_sectors(unit):
			bsector.acquire(libio.Call.partial(root, bsector))

		# The control interface must be shut down in the forks.
		# The interchange is voided the moment we get into the fork,
		# despite the presence of Flows accepting sockets, the
		# traffic instance in the subprocess will know nothing about it.
		ports.bind(('control', 0), libio.endpoint('local', cidstr, "0"))
		self.ctl_install_control(0)

		xml = self.route / 'sectors.xml'
		# Bind the requested interfaces from invocation.xml
		structs = extract_sectors_config(xml.load())
		for slot, binds in structs['interfaces'].items():
			ports.bind(slot, *list(itertools.starmap(libio.endpoint, binds)))

		# forking
		forks = self.concurrency = structs['concurrency']

		if forks:
			# acquire file system sockets before forking.
			# allows us to avoid some synchronizing logic after forking.
			for i in range(1, forks+1):
				ports.bind(('control', i), libio.endpoint('local', cidstr, str(i)))

			for i in range(1, forks+1):
				self.ctl_fork(i, initial=True)
		else:
			# normally rootd
			self.ctl_subactuate()

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
		if fid < self.concurrency:
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

class ServiceCommands(object):
	"""
	Commands for manipulating a sectors.xml file.
	"""

	report = \
	"""
			Concurrency: {dist}
			Requirements: {reqs}
			Environment: {envvars}
			Interfaces: {ifs}
	"""

	if_command_synopsis = {
		'lib': "[LIBRARY_NAME MODULE_PATH ...]",
		'if': "interface-slot-name type:(local|ip4|ip6) addr-1 port-1 addr-2 port-2 ..."
	}
	#'if http +octets://v4.ip/port/address -octets://v6.ip/port/address'

	@staticmethod
	def set_concurrency(srv, level):
		"""
		Number of forks to create when spawning sectord based services.
		"""

		srv.concurrency = int(level)

	@staticmethod
	def libraries_delta(srv, *reqs):
		"""
		Remove the given parameters from the list of libraries.
		"""
		for k, v in zip(pairs[::2], pairs[1::2]):
			srv.libraries[k] = v

		for r in reqs:
			del srv.libraries[k]

	@staticmethod
	def interface_delta(srv, slot, atype, *binds):
		"""
		Add a set of interface bindings to the selected slot.
		"""

		bind_set = srv.interfaces.setdefault(slot, set())

		for (addr, port) in zip(binds[::2], binds[1::2]):
			bind_set.add((atype, addr, port))
