"""
# faultd service management interfaces.

# Manages the service state stored on disk.

# [ Properties ]

# /environment
	# The environment variable that will be referenced in order
	# to identify the default service directory override.

# /default_route
	# A &routes.library.File instance pointing to the default route
	# relative to the user's home directory. (~/.fault)

# [ Service Types ]

# The types of services that are managed by a faultd instance.

# /daemon
	# An invocation that is expected to maintain its running state.

# /sectors
	# A daemon that is specialized for fault.io sectord executions.
	# This includes &.libroot processes.

# /command
	# Exclusive command execution; guarantees that only a configured
	# number of invocations can be running at a given moment.

# /processor
	# A variant of &command where faultd maintains a set of invocations
	# where they are expected to exit when their allotted duration
	# has expired.

# /root
	# Service representation of the faultd instance. Provides
	# global environment configuration.

# /unspecified
	# Placeholder type used when a created service has not been given
	# a type. Unspecified services may be removed arbitrarily.
"""

import os
import sys
import itertools

from ..chronometry import library as libtime
from ..routes import library as libroutes
from ..system import xml as system_xml

types = set((
	'daemon',
	'sectors',
	'processor',

	'root',
	'unspecified',
))

environment = 'FAULT_DAEMON_DIRECTORY'
default_route = libroutes.File.home() / '.fault' / 'rootd'

def identify_route(override=None):
	"""
	# Return the service directory route.
	"""

	global libroutes

	if override is not None:
		return libroutes.File.from_path(override)

	env = os.environ.get(environment)

	if env is None:
		return default_route

	return libroutes.File.from_path(env)

def service_routes(route=default_route):
	"""
	# Collect the routes to the set of services in the directory.
	"""

	# Only interested in directories.
	for i in route.subnodes()[1]:
		bn = i.basename
		yield bn, i

_actuation_map = {'enabled':True, 'disabled':False, True:'enabled', False:'disabled'}

def configure_root_service(srv):
	"""
	# Given a &Service selecting an uninitialized file system path,
	# configure the path as a root sector daemon.
	"""
	srv.create('root')
	srv.executable = sys.executable # reveal original executable
	srv.actuation = 'enabled'
	# rootd is a sector daemon.
	srv.parameters = [
		'-m', __package__+'.bin.sectord',
		__package__+'.libroot.Set.rs_initialize'
	]
	srv.store()

	# The services controlled by &srv
	(srv.route / 'daemons').init('directory')

	# initialize sectors.xml
	from ..daemon import library as libd
	from . import library as libio
	xml = srv.route / 'sectors.xml'
	struct = {
		'concurrency': 0,
		'interfaces': {
			'http': [
				libio.endpoint('local', str(srv.route/'if'), 'http'),
			]
		},
	}
	xml.store(b''.join(libd.serialize_sectors(struct)))

class Service(object):
	"""
	# faultd service states manager.

	# Represents the faultd service stored on disk. The load and store methods are used
	# to perform the necessary updates to or from disk.
	"""

	def libexec(self, recreate=False, root=None):
		"""
		Return the path to a hardlink for the service. Create if absent.
		"""

		r = self.route
		led = r / "libexec"

		if self.type == 'root':
			exe = led / 'rootd'
		else:
			exe = led / self.identifier

		fp = exe.fullpath

		if recreate:
			exe.void()

		if not exe.exists():
			led.init("directory")
			os.link(self.executable, fp)

		return fp

	def prepare(self):
		"""
		# Create the service directory and any type specific subnodes.
		"""

		typ = self.type
		r = self.route

		r.init("directory")
		(r / 'libexec').init("directory")

		if typ in ('sectors', 'root'):
			if_dir = (r / 'if')
			if_dir.init("directory")

	def void(self):
		"""
		# Destroy the service directory.
		"""

		self.route.void()

	def __init__(self, route:libroutes.File, identifier:str, type='unspecified'):
		"""
		# Initialize the Service structure selecting the &route as its
		# storage location. The &route may not exist upon instantiation
		# as it may be the first use in which the user may choose to
		# initialize a directory or merely check for whether it is
		# a service at all.
		"""
		self.route = route
		self.identifier = identifier
		self.type = type

		self.executable = None
		self.environment = {}
		self.parameters = []

		self.abstract = None
		self.actuation = 'disabled'

	def critical(self, message):
		"""
		# Log a critical message. Usually used by &.bin.rootd and
		# &.bin.sectord.
		"""

		logfile = self.route / "critical.log"
		ts = libtime.now().select('iso')

		with logfile.open('a') as f:
			f.write('%s: %s\n' %(ts, message))

	def trim(self):
		"""
		# Trim the critical log in the service's directory.

		# ! PENDING:
			# Not implemented.
		"""

		pass

	def execution(self):
		"""
		# Return a tuple consisting of the executable and the parameters.
		"""

		if self.type == 'root':
			exe = self.libexec('faultd')
			return exe, ['faultd'] + (self.parameters or [])
		elif self.type == 'sectors':
			exe = self.libexec(self.identifier)
			return exe, [self.identifier] + (self.parameters or [])
		else:
			# daemon or command
			return self.executable, [self.executable] + (self.parameters or [])

	def execute(self):
		"""
		# Execute the service replacing the process image. &execute does not return.

		# Environment variables will be updated by the running process,
		# the current working directory will be switched to service's directory,
		# &route, and the service with be executed according to the current
		# working settings assigned to &self.

		# A call to &load prior to running this is often reasonable.
		"""
		global os

		os.environ.update(self.environment or ())
		exe, params = self.execution()
		os.chdir(self.route.fullpath)
		os.execl(exe, *params)

		assert False

	def create(self, type, types=types):
		"""
		# Create the service directory and initialize many of the configuration files.

		# There are three types that may be created: "command", "daemon", and "sectors".

		# "command" types are simple commands that are executed exclusively. The
		# faultd process provides the necessary synchronization to avoid concurrent invocations.
		# Any requests to run the command while it's running will induce no effect.

		# "daemon" types are daemon processes spawned to remain within the process tree.
		# Additional retry logic is used to manage daemons in order to guarantee that a reasonable
		# attempt was made to start them.

		# "sectors" is a daemon, but understood to be a fault.io based process. Configuration
		# changes to the process will sometimes be dynamically modified without restart
		# or reload operations as the root process will provide a control interface that can
		# be used to propagate changes.
		"""

		if type not in types:
			raise ValueError("unknown service type: " + type)

		self.actuation = 'disabled'
		self.type = type
		self.prepare()
		self.store()

		self.critical("created service")

	def exists(self):
		"""
		# Whether or not the service directory exists.
		"""

		return self.route.exists()

	def load(self):
		"""
		# Load the service definition from the filesystem.
		"""

		self.load_actuation()
		self.load_invocation()

	def store(self):
		"""
		# Store the service definition to the filesystem.
		"""

		self.store_invocation()
		self.store_actuation()

	# one pair for each file
	invocation_attributes = (
		'type',
		'abstract',
		'executable',
		'environment',
		'parameters',
	)

	@property
	def parts(self):
		return {
			x: self.__dict__[x]
			for x in self.invocation_attributes
		}

	def load_invocation(self):
		inv_r = self.route / "if" / "invocation.xml"
		data = inv_r.load()
		if data:
			# Delay import.
			import xml.etree.ElementTree as et
			inv = system_xml.Execute.structure(et.XML(data))
		else:
			inv = None

		if inv is not None:
			for k, v in inv.items():
				self.__dict__[k] = v

	def store_invocation(self):
		global system_xml
		xml = b''.join(system_xml.Execute.serialize(self.parts))
		inv_r = self.route / "if" / "invocation.xml"
		inv_r.store(xml)

	def load_actuation(self):
		en_r = self.route / "actuation.txt"
		text = en_r.load().decode('ascii').strip().lower()
		self.actuation = text.strip().lower()

	def store_actuation(self):
		en_r = self.route / "actuation.txt"
		actstr = str(self.actuation).lower().encode('ascii')+b'\n'
		en_r.store(actstr)

	@property
	def actuates(self) -> bool:
		"""
		# Manage the actuation state of the service. &True means the
		# actuation.txt file contain `'enabled'`, &False means the
		# file contains `'disabled'`. Updating the property stores
		# the state to the file.
		"""
		global _actuation_map
		return _actuation_map.get(self.actuation, False)

	@actuates.setter
	def actuates(self, val:bool):
		global _actuation_map
		actstr = _actuation_map[val] # &val must be True or False.

		if actstr != self.actuation:
			# Update file if different from memory.
			self.actuation = actstr
			self.store_actuation()

	def load_pid(self):
		pid_r = self.route / "pid"
		self.pid = int(pid_r.load().decode('ascii').strip())

	def store_pid(self):
		pid_r = self.route / "pid"
		pid_r.store(str(self.pid).encode('ascii')+b'\n')

	@property
	def status(self):
		"""
		# Get and set the contents of the status file in the Service directory.
		"""

		return (self.route / "status").load().decode('utf-8').strip()

	@status.setter
	def status(self, val):
		status_r = self.route / "status"
		status_r.store(str(val).encode('utf-8')+b'\n')
