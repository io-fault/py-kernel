"""
Root process for service management and scheduled processes.

libroot provides the primary support for &.bin.faultd which manages a scheduling daemon,
a set of service processes and a set of service Sectors assigned to a particular
group with its own configurable concurrency level.

Multiple instances of a faultd daemon may exist, but usually only one per-user is necessary.
The (fs)`$HOME/.faultd` directory is used by default, but can be adjusted by a command
line parameter. The daemon directory supplies all the necessary configuration,
so few options are available from system invocation.

It is important that the faultd directory exist on the same partition as the
Python executable. Hardlinks are used in order to provide accurate process names.

The daemon directory structure is a set of service directories managed by the instance with
"scheduled" and "root" reserved for the management of the administrative scheduler
and the spawning daemon itself.

.faultd/root/
	Created automatically to represent the faultd process.
	All files are instantiated as if it were a regular service.
	state is always ON
	invocation.xml written every boot to reflect its invocation

.faultd/root/
	type: sectors | daemon | command | root (reserved for libroot)
	enabled: True or False (whether or not its being executed)
	status: run state (executed|terminated|exception)
	invocation.xml: command and environment for service
	if/: directory of sockets; 0 refers to the master
		0-n
		Only guaranteed to be available for sectord and control types.
"""

import os
import sys
import signal
import functools
import itertools

from ..fork import library as libfork
from ..routes import library as libroutes
from ..chronometry import library as libtime

from . import libservice
from . import core
from . import library
from . import libhttp

class HTTP(library.Sector):
	"""
	HTTP Control Interface.

	Instances represent a connection.
	"""

	@libhttp.resource(limit=0)
	def http_sleep(self, request, response, input):
		"Send a stop signal associated with a timer to pause the process group."

		return "not implemented"

	@libhttp.resource(limit=0)
	def http_enable(self, request, response, input):
		"Enable the service, but do not start it."

		srv = request.managed.service
		path = request.subpath

		srv.enabled = True
		srv.store_enabled()

		return 'enabled'

	@libhttp.resource(limit=0)
	def http_disable(self, request, response, input):
		"Disable the service, but do not change its status."

		srv = request.managed.service
		path = request.subpath

		srv.enabled = False
		srv.store_enabled()

		return 'disabled'

	@libhttp.resource(limit=0)
	def http_signal(self, request, response, input):
		"Send the given signal to the process."

		srv = request.managed
		sig = request.parameters.get('signal', 'SIGINFO')
		if sig.isdigit():
			signo = int(sig)
		else:
			signo = signames[sig]

		if srv.status == 'executed':
			srv.subprocess.signal(signo)
			return 'service signalled'
		else:
			return 'signal not sent as service has not been executed'

	@libhttp.resource(limit=0)
	def http_stop(self, request, response, input):
		ms = request.managed

		if ms.service.enabled:
			ms.inhibit_recovery = True
		else:
			# don't bother
			ms.inhibit_recovery = None

		ms.subprocess.signal(signal.SIGTERM)
		return 'daemon signalled to terminate'

	@libhttp.resource(limit=0)
	def http_restart(self, request, response, input):
		ms = request.managed

		if ms.status != 'executed':
			return 'restart ineffective when not running'

		ms.inhibit_recovery = False
		ms.subprocess.signal(signal.SIGTERM)

		return 'daemon signalled to restart'

	@libhttp.resource(limit=0)
	def http_reload(self, request, response, input):
		ms = request.managed

		if ms.subprocess is not None:
			ms.subprocess.signal(signal.SIGHUP)
			return 'daemon signalled to reload using SIGHUP'
		else:
			return 'reload ineffective when service is not running'

	@libhttp.resource(limit=0)
	def http_replace(self, request, response, input):
		# substitute the sectord process (code/process update)
		# 1. write a substitution file to filesystem
		# 2. signal hup
		# 3. [sectord] check for substitution file on hup receive and begin natural halt
		# 4. [sectord] store environment state recording interfaces
		# 5. [sectord] exec to new process and load state from environment
		return 'substitute not supported'

	@libhttp.resource(limit=0)
	def http_start(self, request, response, input):
		"""
		Start the daemon unless it's already running; explicit starts ignore
		&libservice.Service.enabled.
		"""

		ms = request.managed

		if ms.status == 'executed':
			return "already running"
		else:
			return ms.invoke()

	@libhttp.resource(limit=0)
	def http_execute(self, request, response, input):
		"Execute the command associated with the service. Only applies to command types."

		ms = request.managed

		if ms.status == 'executed':
			return "already running"
		if ms.service.type != 'command':
			return 'not a command service'
		else:
			return ms.invoke()

	@libhttp.resource(limit=0)
	def http_report(self, request, response, input):
		pass

	@libhttp.resource(limit=0)
	def http_commands(self, request, response, input):
		return {k[0]: v.__doc__ for k, v in self.index.items() if k}

	@libhttp.resource(limit=0)
	def http_timestamp(self, request, response, input):
		return libtime.now().select("iso")+'\n'

	#http_if = libhttp.Mount(pkg, dir)

	# fault.io/signal?number=9
	# postgres/
	index = {
		(): http_report, # /service report (prioritize html)
		('report',): http_report,

		('',): http_commands, # /service/ command index
		('commands',): http_commands,

		('signal',): http_signal,

		('enable',): http_enable,
		('disable',): http_disable,

		('start',): http_start,
		('stop',): http_stop,
		('restart',): http_restart,
		('reload',): http_reload,
		('replace'): http_replace,

		('execute',): http_execute,
	}

	def method(self, request):
		if request.managed is None:
			return None

		meth = self.index.get(request.subpath)

		if meth is not None:
			return functools.partial(meth, self)

		return None

	@libhttp.resource(limit=0)
	def service_index(self, request, response, input):
		"Root path."

		return list(self.services)

	def http_request_accept(self, layer, partial=functools.partial, tuple=tuple):
		path_parts = layer.path.decode('utf-8').split('/')

		empty, service_name, *path = path_parts

		request = layer
		request.service_name = service_name
		request.subpath = tuple(path)
		request.managed = self.services.get(service_name)

		response = self.protocol.output_layer()

		ins = self.protocol.distribute
		out = self.protocol.serialize
		out.enqueue(response) # reserve spot in output queue

		out_connect = partial(out.connect, response)

		# conditionally provide flow connection callback.
		if request.length is not None:
			ins_connect = partial(ins.connect, request)
		else:
			# there is no content flow
			ins_connect = None

		path = request.path
		if path == b'/':
			method = functools.partial(self.service_index, self)
		elif path == b'/root/timestamp':
			method = functools.partial(self.http_timestamp, self)
		elif path == b'/fault':
			raise Exception("FAULT")
		else:
			method = self.method(request)

		if method is None:
			response.initiate((b'HTTP/1.1', b'404', b'NOT FOUND'))
			notfound = b'No such resource.'
			response.add_headers([
				(b'Content-Type', b'text/plain'),
				(b'Content-Length', str(len(notfound)).encode('utf-8'),)
			])

			if request.terminal:
				response.add_headers([
					(b'Connection', b'close'),
				])

			if request.content:
				ins_connect(library.Null)

			proc = library.Flow()
			i = library.Iterate()
			proc.requisite(i)
			proc.subresource(self)
			self.requisite(proc)
			out_connect(proc)
			proc.actuate()
			proc.process([(notfound,)])
			proc.terminate()
		else:
			proc = method(request, response, ins_connect, out_connect)
			if proc is not None:
				self.dispatch(proc)

	def http_request_closed(self, layer, flow):
		# called when the input flow of the request is closed
		if flow is not None:
			flow.terminate()

	@classmethod
	def http_accept(Class, spawn, packet, chain=itertools.chain):
		"""
		Accept HTTP connections for interacting with the daemon.
		"""

		source, event = packet
		sector = spawn.sector

		# service_name -> ManagedService
		services = sector.controller.services

		# event is a iterable of socket file descriptors
		for fd in chain(*event):
			cxn = Class()
			cxn.services = services
			sector.dispatch(cxn)

			with cxn.xact() as xact:
				io = xact.acquire_socket(fd)
				p, fi, fo = libhttp.server_v1(xact, cxn.http_request_accept, cxn.http_request_closed, *io)

				#cxn.requisite(p, fi, fo)
				cxn.dispatch(fo)
				cxn.dispatch(fi)
				cxn.dispatch(p)
				cxn.protocol = p
				fi.process(None)

class ServiceManager(library.Processor):
	"""
	Service daemon state and interface.

	Manages the interactions to daemons and commands.

	ServiceManager processors do not exit unless the service is *completely* removed
	by an administrative instruction; disabling a service does not remove it.
	They primarily respond to events in order to keep the daemon running.
	Secondarily, it provides the administrative interface.

	! WARNING:
		There is no exclusion primitive used to protect read or write operations,
		so there are race conditions.

	[ Properties ]

	/minimum_runtime
		Identifies the minimum time required to identify a successful start.

	/minimum_wait
		Identifies the minimum wait time before trying again.

	/maximum_wait
		Identifies the maximum wait time before trying again.
	"""

	# delay before faultd perceives the daemon as running
	minimum_runtime = libtime.Measure.of(second=3)
	minimum_wait = libtime.Measure.of(second=2)
	maximum_wait = libtime.Measure.of(second=32)

	def structure(self):
		p = [
			('status', self.status),
			('enabled', self.service.enabled),
			('service', self.service),
			('invocation', self.invocation),
		]

		if self.subprocess:
			sr = [('subprocess', self.subprocess)]
		else:
			sr = []

		return (p, sr)

	status = 'actuating'
	service = None
	root = None
	invocation = None
	subprocess = None
	inhibit_recovery = None
	exit_events = ()

	def requisite(self, service:libservice.Service, root):
		self.service = service
		self.root = root # global environment

	def actuate(self):
		self.exit_events = []
		self.status = 'terminated'
		self.last_invocation = None

		super().actuate()

		self.update()
		self.last_known_time = libtime.now()
		srv = self.service

		if srv.enabled and srv.type in ('daemon', 'sectors'):
			self.invoke()

		return self

	def invoke(self):
		"""
		Invoke the service daemon or command.
		Does nothing if &status is `'executed'`.
		"""

		if self.service.type == 'root':
			# totally ignore invocations for root services.
			return 'root is already invoked'

		if self.status == 'executed':
			return 'already running'

		try:
			self.status = 'executed'

			service = self.service
			sector = self.sector

			with sector.xact() as xact:
				os.chdir(service.route.fullpath)
				sub, stderr = xact.daemon(self.invocation)

			sub.subresource(sector)
			sub.actuate()
			sub.atexit(self.service_exit)

			self.subprocess = sub # need for control interface (http)

			# stderr stopgap; probably move to a log file managed by this class.
			f = library.Flow()
			def gah(s):
				for x in s:
					sys.stderr.write(x.decode('utf-8'))
				sys.stderr.flush()
			pt = library.Functional(gah)
			f.requisite(*(library.core.meter_input(stderr) + (pt,)))

			sector.dispatch(f)
			f.process(None)
		except BaseException as exc:
			# special status used to explain the internal failure
			self.status = 'exception'
			raise

		self.last_invocation = libtime.now()
		return 'invoked'

		# service_exit is called when the process exit signal is received.

	def again(self):
		"Called when a non-command service exits."

		r = self.rate()
		self.status = 'waiting'
		# based on the rate, defer .invoke by an interval bounded
		# by minimum_wait and maximum_wait.
		self.invoke()

	def rate(self):
		"Average exits per second."

		et = self.exit_events
		#times = [et[i].measure(et[i-1]) for i in range(1, len(et))]
		avg = et[-1][0].measure(et[0][0]) / len(et)

	def service_exit(self, exit_count):
		pid_exit = self.subprocess.only
		self.subprocess = None

		if self.status != 'exception':
			self.status = 'terminated'

		self.exit_events.append((libtime.now(),) + pid_exit)

		# automatically recover if its a daemon or sectors
		if self.service.type in ('daemon', 'sectors'):
			if self.inhibit_recovery == True:
				pass
			else:
				if self.service.enabled:
					self.again()
				elif self.inhibit_recovery == False:
					# restarted
					self.inhibit_recovery = None
					self.again()

	def update(self):
		# KInvocation used to run the command.
		service = self.service

		env = dict(os.environ.items())

		if self.root.environment:
			env.update(self.root.environment)

		if service.environment:
			env.update(service.environment)

		env['SERVICE_NAME'] = service.name

		ki = libfork.KInvocation(*service.execution(), environ=env)
		self.invocation = ki

# faultd manages services via a set of directories that identify the service
# and its launch parameters/environment.

# fault.io sectors are more complicated in that they are actually process groups
# that contain multiple root Sectors (applications) that may or may not fork.
# A given group has a set of configured interfaces; these interfaces
# are allocated by the parent process as they're configured.

class Control(library.Control):
	"""
	The (io.path)`/control` sector of the root daemon (faultd) managing a set of services.

	Executes the managed services inside (io.path)`/bin/*`; ignores
	natural exit signals as it waits for administrative termination
	signal.
	"""

	def __init__(self, route):
		super().__init__()
		self.route = route.rebase()
		self.services = {} # name => ManagedService() instances
		self.root = None

	def halt(self, source):
		self.context.process.log("halt requested")

	def exit(self, unit):
		# faultd only exits when explicitly terminated.
		# It is possible to have a running daemon without services;
		# the provided HTTP interface allows modification to the service set.
		pass

	def actuate(self):
		# initialize controld service directory
		super().actuate()

		srv = libservice.Service(self.route, 'root')
		os.environ['FAULTD_DIRECTORY'] = self.route.fullpath

		# check process running

		if not srv.exists():
			srv.create('unspecified')
			srv.executable = sys.executable
			srv.type = 'root'
			srv.enabled = True
			srv.store()
		else:
			srv.prepare()
			srv.load()

		srv.pid = libfork.current_process_id
		srv.store_pid()
		self.root = srv
		srv.critical("starting daemon")

		# root's service instance will be loaded again in boot.
		# this reference will be simply dropped.

		srv_list = self.route.subnodes()[0]
		services = {}
		services.update(
			(x.identity, srv.coservice(x.identity))
			for x in srv_list
		)

		# bind http control interface
		endpoint = library.endpoint('local', (srv.route/"if").fullpath, "0")
		self.controller.ports.bind('http', endpoint)
		# XXX: needs to be sourced from configuration
		self.controller.ports.bind('http', library.endpoint('ip4', '127.0.0.1', 8181))

		os.chdir(srv.route.fullpath)
		self.boot(services)

		hi = libhttp.Interface()
		hi.requisite('http', HTTP.http_accept)
		self.dispatch(hi)

		return self

	def boot(self, services):
		"Start all the *enabled* services."

		unit = self.context.association()
		root = self.root

		# invocation. each subprocess gets its own sector
		# the RService instances manages the core.Subprocess instance
		# running the actual system [sub] process.
		for sn, s in services.items():
			s.load()
			if s.type == 'root':
				continue

			S = library.Sector()
			unit.place(S, "bin", s.name)
			S.subresource(unit)
			S.actuate()

			d = ServiceManager()
			d.requisite(s, root)
			# HTTP needs to be able to find the SM to interact with it.
			self.services[s.name] = d

			d.subresource(S)
			S.dispatch(d)
