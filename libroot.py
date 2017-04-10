"""
# Root process for service management and scheduled processes.

# libroot provides the primary support for &.bin.rootd which manages a scheduling daemon,
# a set of service processes and a set of service Sectors assigned to a particular
# group with its own configurable concurrency level.
# 
# Multiple instances of faultd may exist, but usually only one per-user is necessary.
# The (system:directory)`$HOME/.faultd` directory is used by default, but can be adjusted by a command
# line parameter. The daemon directory supplies all the necessary configuration,
# so few options are available from system invocation.
# 
# It is important that the faultd directory exist on the same partition as the
# Python executable. Hardlinks are used in order to provide accurate process names.
# 
# The daemon directory structure is a set of service directories managed by the instance with
# "scheduled" and "root" reserved for the management of the administrative scheduler
# and the spawning daemon itself.
# 
# /root/
	# Created automatically to represent the faultd process.
	# All files are instantiated as if it were a regular service.
	# state is always ON
	# invocation.xml written every boot to reflect its invocation

# /root/
	# type: sectors | daemon | command | root (reserved for libroot)
	# actuates: True or False (whether or not its to be spawned)
	# status: run state (executed|terminated|exception)
	# invocation.xml: command and environment for service
	# if/: directory of sockets; 0 refers to the master
		# 0-n
		# Only guaranteed to be available for sectord and control types.
"""

import os
import sys
import signal
import functools
import itertools
import typing

from ..system import library as libsys
from ..routes import library as libroutes
from ..chronometry import library as libtime

from . import libservice
from . import library as libio

from ..web import libhttpd

class HumanInterface(libhttpd.Index):
	pass

class HumanInterfaceSupport(libhttpd.Index):
	pass

class Commands(libhttpd.Index):
	"""
	# HTTP Control API used by control (Host) connections.

	# GET Retrieves documentation, POST performs.
	"""

	def __init__(self, services, managed):
		self.managed = managed
		self.services = services

	@libhttpd.Resource.method()
	def sleep(self, resource, parameters) -> (str, str):
		"""
		# Send a stop signal associated with a timer to pause the process group.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.status == 'executed':
			service.subprocess.signal(signal.SIGSTOP)
			return (service.identifier, "service signalled to pause")
		else:
			return (service.identifier, "cannot signal service when not running")

	@libhttpd.Resource.method()
	def enable(self, resource, parameters) -> typing.Tuple[str, str]:
		"""
		# Enable the service, but do not start it.
		"""

		service = self.services[parameters['service']]
		service.actuates = True
		service.store_actuation()

		return (service.identifier, "enabled")

	@libhttpd.Resource.method()
	def disable(self, resource, parameters):
		"""
		# Disable the service, but do not change its status.
		"""

		service = self.services[parameters['service']]
		service.actuates = False
		service.store_actuation()

		return (service.identifier, "disabled")

	@libhttpd.Resource.method()
	def signal(self, resource, parameters):
		"""
		# Send the given signal to the process.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]
		signo = int(parameters['number'])

		if service.status == 'executed':
			managed.subprocess.signal(signo)
			return "service signalled"
		else:
			return "signal not sent as service has not been executed"

	@libhttpd.Resource.method()
	def stop(self, resource, parameters):
		"""
		# Signal the service to stop and inhibit it from being restarted if enabled.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.actuates:
			managed.inhibit_recovery = True
		else:
			# No need.
			managed.inhibit_recovery = None

		if managed.status != 'executed':
			return (service.identifier, "stop ineffective when not running")

		managed.subprocess.signal_process_group(signal.SIGTERM)
		return (service.identifier, "daemon signalled to terminate")

	@libhttpd.Resource.method()
	def restart(self, resource, parameters):
		"""
		# Signal the service to stop (SIGTERM) and allow it to restart.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.status != 'executed':
			return (service.identifier, "restart ineffective when not running")

		managed.inhibit_recovery = False
		managed.subprocess.signal_process_group(signal.SIGTERM)

		return (service.identifier, "daemon signalled to restart")

	@libhttpd.Resource.method()
	def reload(self, resource, parameters):
		"""
		# Send a SIGHUP to the service.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if managed.subprocess is not None:
			managed.subprocess.signal(signal.SIGHUP)
			return (service.identifier, "daemon signalled to reload using SIGHUP")
		else:
			return (service.identifier, "reload ineffective when service is not running")

	@libhttpd.Resource.method()
	def replace(self, resource, parameters):
		service = self.services[parameters['service']]
		# substitute the sectord process (code/process update)
		# 1. write a substitution file to filesystem
		# 2. signal hup
		# 3. [sectord] check for substitution file on hup receive and begin natural halt
		# 4. [sectord] store environment state recording interfaces
		# 5. [sectord] exec to new process and load state from environment
		return (service.identifier, "substitute not supported")

	@libhttpd.Resource.method()
	def start(self, resource, parameters):
		"""
		# Start the daemon unless it's already running; explicit starts ignore
		# &libservice.Service.actuates.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.status == 'executed':
			return (service.identifier, "already running")
		else:
			managed.invoke()
			return (service.identifier, "invoked")

	@libhttpd.Resource.method()
	def environment(self, resource, parameters):
		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]
		return service.environment

	@libhttpd.Resource.method()
	def normalize(self, resource, parameters):
		"""
		# Normalize the set of services by shutting down any running
		# disabled services and starting any enabled services.

		# Command services are ignored by &normalize.
		"""

		for name, service in self.services.items():
			managed = self.managed[name]

			if service.actuates and service.status != 'executed':
				yield (service.identifier, managed.invoke())
			elif service.disabled and service.status == 'executed':
				yield (service.identifier, managed.subprocess.signal(signal.SIGTERM))

	@libhttpd.Resource.method()
	def execute(self, resource, parameters):
		"""
		# Execute the command associated with the service. Only applies to command types.
		"""

		managed = self.managed[parameters['service']]
		service = self.services[parameters['service']]

		if service.status == 'executed':
			return (service.identifier, "already running")
		if service.type != 'command':
			return (service.identifier, "not a command service")
		else:
			managed.invoke()
			return (service.identifier, "service invoked")

	@libhttpd.Resource.method()
	def report(self, resource, parameters):
		pass

	@libhttpd.Resource.method()
	def timestamp(self, resource, parameters):
		"""
		Return the faultd's perception of time.
		"""
		return libtime.now().select("iso")

	# /if/signal?number=9

	@libhttpd.Resource.method()
	def __resource__(self, resource, path, query, px):
		pass

	@libhttpd.Resource.method()
	def list(self, resource, parameters):
		"""
		# List the set of configured services.
		"""

		# list all if no filter
		service_set = [x for x in self.services.keys()]
		return service_set

	@libhttpd.Resource.method()
	def create(self, resource, parameters):
		"""
		# Create a service.
		"""

		name = parameters['service']

	@libhttpd.Resource.method()
	def void(self, resource, parameters):
		"""
		# Terminate the service and destroy it's stored configuration.
		"""

		name = parameters['service']
		m = self.managed[name]
		m.inhibit_recovery = True
		m.subprocess.signal(signal.SIGKILL)
		m.terminate()
		s = self.services[name]
		s.void()

	@libhttpd.Resource.method()
	def interface(self, resource, parameters):
		"""
		# Add a set of interfaces.
		"""

		name = parameters['service']
		service = self.services[name]
		return service.interfaces

class ServiceManager(libio.Processor):
	"""
	# Service daemon state and interface.

	# Manages the interactions to daemons and commands.

	# ServiceManager processors do not exit unless the service is *completely* removed
	# by an administrative instruction; disabling a service does not remove it.
	# They primarily respond to events in order to keep the daemon running.
	# Secondarily, it provides the administrative interface.

	# ! WARNING:
		# There is no exclusion primitive used to protect read or write operations,
		# so there are race conditions.

	# [ Properties ]

	# /minimum_runtime
		# Identifies the minimum time required to identify a successful start.

	# /minimum_wait
		# Identifies the minimum wait time before trying again.

	# /maximum_wait
		# Identifies the maximum wait time before trying again.
	"""

	# delay before faultd perceives the daemon as running
	minimum_runtime = libtime.Measure.of(second=3)
	minimum_wait = libtime.Measure.of(second=2)
	maximum_wait = libtime.Measure.of(second=32)

	def structure(self):
		p = [
			('status', self.status),
			('actuates', self.service.actuates),
			('service', self.service),
			('invocation', self.invocation),
			('exit_events', self.exit_events),
		]

		if self.subprocess:
			sr = [('subprocess', self.subprocess)]
		else:
			sr = []

		return (p, sr)

	critical = "critical.log"

	status = 'unspecified'
	service = None
	root = None
	invocation = None
	subprocess = None
	inhibit_recovery = None
	exit_events = ()

	def __init__(self, service, root):
		self.service = service
		self.root = root # global environment

	def actuate(self):
		super().actuate()
		self.exit_events = []
		self.status = 'terminated'

		self.sm_update()
		self.last_known_time = libtime.now()
		srv = self.service

		if srv.actuates and srv.type in ('daemon', 'sectors'):
			self.invoke()

		return self

	def invoke(self):
		"""
		# Invoke the service daemon or command.
		# Does nothing if &status is `'executed'`.
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

			os.chdir(service.route.fullpath)
			fd = os.open(self.critical, os.O_APPEND|os.O_WRONLY|os.O_CREAT)

			pid = self.context.daemon_stderr(fd, self.invocation)
			sub = self.subprocess = libio.Subprocess(pid)

			sector.dispatch(sub)
			sub.atexit(self.sm_service_exit)
		except BaseException as exc:
			# special status used to explain the internal failure
			self.status = 'exception'
			raise # XXX: needs to report rather than fault

		return 'invoked'

		# service_exit is called when the process exit signal is received.

	def again(self):
		"""
		# Called when a non-command service exits.
		"""

		r = self.rate()
		self.status = 'waiting'
		# based on the rate, defer .invoke by an interval bounded
		# by minimum_wait and maximum_wait.
		self.invoke()

	def rate(self):
		"""
		# Average exits per second.
		"""

		et = self.exit_events
		#times = [et[i].measure(et[i-1]) for i in range(1, len(et))]
		avg = et[-1][0].measure(et[0][0]) / len(et)

	def sm_service_exit(self, exit_count):
		if self.subprocess is not None:
			pid_exit = self.subprocess.only
		else:
			pid_exit = None

		self.subprocess = None

		if self.status != 'exception':
			self.status = 'terminated'

		self.exit_events.append((libtime.now(), pid_exit))

		# automatically recover if its a daemon or sectors
		if self.service.type in ('daemon', 'sectors'):
			if self.inhibit_recovery == True:
				pass
			else:
				if self.service.actuates:
					self.again()
				elif self.inhibit_recovery == False:
					# restarted
					self.inhibit_recovery = None
					self.again()

	def sm_update(self):
		"""
		# Create or Update the KInvocation instance.
		# Used to initiate the Invocation and after command and environment changes.
		"""

		# KInvocation used to run the command.
		service = self.service
		command_def = service.execution()
		if command_def[0] is None:
			command_def = ()
			return

		env = dict(os.environ.items())

		if service.environment:
			env.update(service.environment)

		env['SERVICE_NAME'] = service.identifier

		ki = libsys.KInvocation(*command_def, environ=env, set_process_group=True)
		self.invocation = ki

	def terminate(self, by=None):
		if super().terminate(by):
			terminated = True
			self.controller.exited(self)

	def interrupt(self, by=None):
		if super().interrupt(by):
			self.controller.exited(self)

# faultd manages services via a set of directories that identify the service
# and its launch parameters/environment.

# fault.io sectors are more complicated in that they are actually process groups
# that contain multiple root Sectors (applications) that may or may not fork.
# A given group has a set of configured interfaces; these interfaces
# are allocated by the parent process as they're configured.

class Set(libio.Interface):
	"""
	# The (io.path)`/control` sector of the root daemon (faultd)
	# managing a set of services.

	# Executes the managed services inside (io.path)`/bin/*`; ignores
	# natural exit signals as it waits for administrative termination
	# signal.

	# [ Engineering ]

	# Operation set for dispatched processes. Provides instropection
	# to the operation status, and any blocking operations.
	"""

	def halt(self, source):
		self.context.process.log("halt requested")

	def exit(self, unit):
		# faultd only exits when explicitly terminated.
		# It is possible to have a running daemon without services;
		# the provided HTTP interface allows modification to the service set.
		pass

	def actuate(self):
		"""
		# Create the faultd context if it does not exist.
		# This is performed in actuate because it is desirable
		# to trigger a &libsys.Panic when an exception occurs.
		"""
		super().actuate()

		self.route = libroutes.File.from_cwd()
		self.services = {} # name :> ManagedService() instances
		self.managed = {} # the ServiceManager instances dispatched in io://faultd/bin/
		self.root = None

		srv = libservice.Service(self.route, 'faultd')
		if libservice.environment not in os.environ:
			os.environ[libservice.environment] = self.route.fullpath

		# check process running
		srv.prepare()
		srv.load()

		srv.pid = libsys.current_process_id
		srv.store_pid()
		self.root = srv
		srv.critical("starting root daemon")
		os.chdir(srv.route.fullpath)

		# root's service instance will be loaded again in boot.
		# this reference will be simply dropped.

		rd = self.r_daemons = self.route / 'daemons'
		srv_list = rd.subnodes()[0]
		self.services.update(
			(x.identifier, libservice.Service(x, x.identifier))
			for x in srv_list
		)
		self.context.enqueue(self.boot)

		return self

	def manage_service(self, unit, srv:libservice.Service):
		"""
		# Install the service's manager for execution.
		"""

		S = libio.Sector()
		unit.place(S, "bin", srv.identifier)
		S.subresource(unit)
		S.actuate()

		d = ServiceManager(srv, self.root)
		# HTTP needs to be able to find the SM to interact with it.
		self.managed[srv.identifier] = d

		d.subresource(S)
		S.dispatch(d)

	def forget_service(self, s:libservice.Service):
		"""
		# Remove the service from the managed list and the service set.
		"""
		raise Exception('not implemented')

	def boot(self):
		"""
		# Start all the *actuating* services and mention all the disabled ones.
		"""

		unit = self.context.association()

		# invocation. each subprocess gets its own sector
		# the RService instances manages the core.Subprocess instance
		# running the actual system [sub] process.
		for sn, s in self.services.items():
			s.load()
			self.manage_service(unit, s)

	@classmethod
	def rs_initialize(Class, sector):
		"""
		# sectord entry point for initializing the application sector.
		"""
		rset = Class()
		sector.dispatch(rset)
		web_interface = {
			'/sys/': Commands(rset.services, rset.managed),
		}
		libhttpd.init(sector, ('control',), web_interface, 'http')
