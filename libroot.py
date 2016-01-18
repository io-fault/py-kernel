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
import typing

from ..fork import library as libfork
from ..routes import library as libroutes
from ..chronometry import library as libtime

from . import libservice
from . import library as libio
from . import libhttp

class HumanInterface(libhttp.Index):
	pass

class HumanInterfaceSupport(libhttp.Index):
	pass

class Commands(libhttp.Index):
	"""
	HTTP Control API used by control (Host) connections.

	GET Retrieves documentation, POST performs.
	"""

	def __init__(self, services, managed):
		self.managed = managed
		self.services = services

	@libhttp.Resource.method()
	def sleep(self, resource, parameters) -> (str, str):
		"""
		Send a stop signal associated with a timer to pause the process group.
		"""

		if service.status == 'executed':
			service.subprocess.signal(signal.SIGSTOP)
			return (service.name, "service signalled to stop")
		else:
			return (service.name, "cannot signal service when not running")

	@libhttp.Resource.method()
	def enable(self, resource, parameters) -> typing.Tuple[str, str]:
		"""
		Enable the service, but do not start it.
		"""

		service = self.services[parameters['service']]
		service.enabled = True
		service.store_enabled()

		return (service.name, "enabled")

	@libhttp.Resource.method()
	def disable(self, resource, parameters):
		"""
		Disable the service, but do not change its status.
		"""

		service = self.services[parameters['service']]
		service.enabled = False
		service.store_enabled()

		return (service.name, "disabled")

	@libhttp.Resource.method()
	def signal(self, resource, parameters):
		"Send the given signal to the process."

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]
		signo = int(parameters['number'])

		if service.status == 'executed':
			managed.subprocess.signal(signo)
			return "service signalled"
		else:
			return "signal not sent as service has not been executed"

	@libhttp.Resource.method()
	def stop(self, resource, parameters):
		"Signal the service to stop and inhibit from being restarted."

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.enabled:
			managed.inhibit_recovery = True
		else:
			# No need.
			managed.inhibit_recovery = None

		managed.subprocess.signal(signal.SIGTERM)
		return (service.name, "daemon signalled to terminate")

	@libhttp.Resource.method()
	def restart(self, resource, parameters):
		"Signal the service to stop (SIGTERM) and allow it to restart."

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.status != 'executed':
			return (service.name, "restart ineffective when not running")

		managed.inhibit_recovery = False
		managed.subprocess.signal(signal.SIGTERM)

		return (service.name, "daemon signalled to restart")

	@libhttp.Resource.method()
	def reload(self, resource, parameters):
		"Send a SIGHUP to the service."

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.subprocess is not None:
			managed.subprocess.signal(signal.SIGHUP)
			return (service.name, "daemon signalled to reload using SIGHUP")
		else:
			return (service.name, "reload ineffective when service is not running")

	@libhttp.Resource.method()
	def replace(self, resource, parameters):
		service = self.services[parameters['service']]
		# substitute the sectord process (code/process update)
		# 1. write a substitution file to filesystem
		# 2. signal hup
		# 3. [sectord] check for substitution file on hup receive and begin natural halt
		# 4. [sectord] store environment state recording interfaces
		# 5. [sectord] exec to new process and load state from environment
		return (service.name, "substitute not supported")

	@libhttp.Resource.method()
	def start(self, resource, parameters):
		"""
		Start the daemon unless it's already running; explicit starts ignore
		&libservice.Service.enabled.
		"""
		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.status == 'executed':
			return (service.name, "already running")
		else:
			managed.invoke()
			return (service.name, "invoked")

	@libhttp.Resource.method()
	def environment(self, resource, parameters):
		pass

	@libhttp.Resource.method()
	def normalize(self, resource, parameters):
		"""
		Normalize the set of services by shutting down any running
		disabled services and starting any enabled services.

		Command services are ignored by &normalize.
		"""

		for name, service in self.services.items():
			managed = self.managed[name]

			if service.enabled and service.status != 'executed':
				yield (service.name, managed.invoke())
			elif service.disabled and service.status == 'executed':
				yield (service.name, managed.subprocess.signal(signal.SIGTERM))

	@libhttp.Resource.method()
	def execute(self, resource, parameters):
		"""
		Execute the command associated with the service. Only applies to command types.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.status == 'executed':
			return (service.name, "already running")
		if service.type != 'command':
			return (service.name, "not a command service")
		else:
			managed.invoke()
			return (service.name, "service invoked")

	@libhttp.Resource.method()
	def report(self, resource, parameters):
		pass

	@libhttp.Resource.method()
	def timestamp(self, resource, parameters):
		"Return the faultd's perception of time."
		return libtime.now().select("iso")

	# /if/signal?number=9

	@libhttp.Resource.method()
	def __resource__(self, resource, path, query, px):
		pass

	@libhttp.Resource.method()
	def list(self, resource, parameters):
		"List the set of configured services."

		# list all if no filter
		service_set = [x for x in self.services.keys()]
		return service_set

	@libhttp.Resource.method()
	def create(self, resource, parameters):
		"Create a service."

		name = parameters['service']

	@libhttp.Resource.method()
	def void(self, resource, parameters):
		"Terminate the service and destroy it's stored configuration."

		name = parameters['service']
		m = self.managed[name]
		m.inhibit_recovery = True
		m.subprocess.signal(signal.SIGKILL)
		m.terminate()
		s = self.services[name]
		s.void()

	@libhttp.Resource.method()
	def interface(self, resource, parameters):
		"Add a set of interfaces"

		name = parameters['service']

class ServiceManager(libio.Processor):
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

	def requisite(self, service, root):
		self.service = service
		self.root = root # global environment

	def actuate(self):
		self.exit_events = []
		self.status = 'terminated'

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
			f = libio.Flow()
			def gah(s):
				for x in s:
					sys.stderr.write(x.decode('utf-8'))
				sys.stderr.flush()
			pt = libio.Functional(gah)
			f.requisite(*(libio.core.meter_input(stderr) + (pt,)))

			sector.dispatch(f)
			f.process(None)
		except BaseException as exc:
			# special status used to explain the internal failure
			self.status = 'exception'
			raise

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

class Control(libio.Control):
	"""
	The (io.path)`/control` sector of the root daemon (faultd) managing a set of services.

	Executes the managed services inside (io.path)`/bin/*`; ignores
	natural exit signals as it waits for administrative termination
	signal.
	"""

	def halt(self, source):
		self.context.process.log("halt requested")

	def exit(self, unit):
		# faultd only exits when explicitly terminated.
		# It is possible to have a running daemon without services;
		# the provided HTTP interface allows modification to the service set.
		pass

	def requisite(self, route:libroutes.File):
		self.route = route.rebase()

	def actuate(self):
		"""
		Create the faultd context if it does not exist.
		This is performed in actuate because it is desirable
		to trigger a &libfork.Panic when an exception occurs.
		"""
		# initialize controld service directory
		super().actuate()

		self.services = {} # name => ManagedService() instances
		self.managed = {} # the ServiceManager instances dispatched in io://faultd/bin/
		self.root = None

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
		self.services.update(
			(x.identity, srv.coservice(x.identity))
			for x in srv_list
		)

		self.root_paths = {
			'/': HumanInterface(),
			'/sys/': Commands(self.services, self.managed),
			'/hif/': HumanInterfaceSupport(),
		}

		# bind http control interface; predefined.
		stdif = libio.endpoint('local', (srv.route/"if").fullpath, "0")

		self.controller.ports.bind('http', stdif)
		for slot, binds in srv.interfaces.items():
			ports.bind(slot, *itertools.starmap(libio.endpoint, binds))

		control = libhttp.Host()
		control.requisite(self.root_paths, 'control')
		scheduler = libhttp.Host()
		scheduler.requisite({}, 'scheduler')

		hi = libhttp.Interface()
		libio.Interface.requisite(hi, 'http', hi.accept)
		libhttp.Interface.requisite(hi, libhttp.server_v1, control, scheduler)
		self.dispatch(hi)

		os.chdir(srv.route.fullpath)
		self.context.enqueue(self.boot)

		return self

	def manage_service(self, unit, s:libservice.Service):
		"""
		Install the service's manager for execution.
		"""

		S = libio.Sector()
		unit.place(S, "bin", s.name)
		S.subresource(unit)
		S.actuate()

		d = ServiceManager()
		d.requisite(s, self.root)
		# HTTP needs to be able to find the SM to interact with it.
		self.managed[s.name] = d

		d.subresource(S)
		S.dispatch(d)

	def forget_service(self, s:libservice.Service):
		"""
		Remove the service from the managed list and the service set.
		"""
		raise Exception('not implemented')

	def boot(self):
		"""
		Start all the *enabled* services and mention all the disabled ones.
		"""

		unit = self.context.association()

		# invocation. each subprocess gets its own sector
		# the RService instances manages the core.Subprocess instance
		# running the actual system [sub] process.
		for sn, s in self.services.items():
			s.load()
			if s.type == 'root':
				# this process/sector.
				continue

			self.manage_service(unit, s)
