"""
faultd service management interfaces.

Manages the service state stored on disk.

[ Properties ]

/environment
	The environment variable that will be referenced in order
	to identify the default service directory override.

/default_route
	A &routes.library.File instance pointing to the default route
	relative to the user's home directory. (~/.faultd)

[ Service Types ]

The types of services that are managed by a faultd instance.

/daemon
	An invocation that is expected to maintain its running state.

/sectors
	A daemon that is specialized for fault.io sectord executions.

/command
	Exclusive command execution; guarantees that only a configured
	number of invocations can be running at a given moment.

/processor
	A variant of &command where faultd maintains a set of invocations
	where they are expected to exit when their allotted duration
	has expired.

/root
	Service representation of the faultd instance. Provides
	global environment configuration.

/unspecified
	Placeholder type used when a created service has not been given
	a type.
"""

import os
import sys
import itertools
import xml.etree.ElementTree as xmllib

from ..chronometry import library as libtime
from ..routes import library as libroutes
from ..xml import library as libxml

types = set((
	'daemon',
	'command',
	'sectors',
	'processor',

	'root',
	'unspecified',
))

environment = 'FAULT_DAEMON_DIRECTORY'
default_route = libroutes.File.home() / '.fault' / 'daemons'

def identify_route(override=None):
	"""
	Return the service directory route.
	"""

	global libroutes

	if override is not None:
		return libroutes.File.from_path(override)

	env = os.environ.get(environment)

	if env is None:
		return default_route

	return libroutes.File.from_path(env)

def extract(xml, nsmap={"fs": "https://fault.io/xml/spawns"}):
	"""
	Extract a service configuration from an XML file.
	"""

	xr = xmllib.XML(xml)
	find = lambda x: xr.find(x, nsmap)

	typ = xr.attrib["type"]

	env_element = find("fs:environment")
	params = find("fs:parameters")
	reqs = find("fs:requirements")

	doc = xr.attrib.get("abstract")

	libelements = find("fs:libraries")
	ifelements = find("fs:interfaces")

	exe = xr.attrib.get("executable", None)
	dist = xr.attrib.get("concurrency", None)

	env = {
		x.attrib["name"]: x.attrib["value"]
		for x in list(env_element)
	}

	if libelements:
		libs = [
			(x.attrib["libname"], x.attrib["fullname"])
			for x in list(libelements)
		]
		libs = dict(libs)
	else:
		libs = None

	if ifelements:
		interfaces = {
			element.attrib["name"]: set([
				(x.attrib["type"], x.attrib["address"], x.attrib["port"])
				for x in list(element)
			])
			for element in list(ifelements)
		}
	else:
		interfaces = {}

	fields = [x.attrib["literal"] for x in list(params)]

	deps = [x.attrib["name"] for x in list(reqs)]

	struct = {
		'executable': exe,
		'environment': env,
		'parameters': fields,
		'requirements': deps,
		'abstract': doc,
		'libraries': libs,
		'interfaces': interfaces,
		'type': typ,
		'concurrency': None if dist is None else int(dist),
	}

	return struct

def construct(struct,
		encoding="utf-8",
		ns="https://fault.io/xml/spawns",
		chain=itertools.chain.from_iterable
	):
	"""
	Construct an XML configuration for a service spawn.
	"""

	xmlctx = libxml.Serialization()

	return xmlctx.root('spawn',
		chain((
			xmlctx.element('requirements',
				chain(
					xmlctx.element('service', None, ('name', x))
					for x in struct['requirements']
				)
			),
			xmlctx.element('environment',
				chain(
					xmlctx.element('setting', None, ('name', k), ('value', v))
					for k, v in struct['environment'].items()
				)
			),
			xmlctx.element('parameters',
				chain(
					xmlctx.element('field', None, ('literal', x))
					for x in struct['parameters']
				)
			),
			xmlctx.element('libraries',
				chain(
					xmlctx.element('module', None, ('libname', x), ('fullname', fn))
					for x, fn in (struct.get('libraries', None) or {}).items()
				)
			),
			xmlctx.element('interfaces',
				chain(
					xmlctx.element('interface',
						chain(
							xmlctx.element('bind', None,
								('type', atype),
								('address', address),
								('port', port)
							)
							for atype, address, port in binds
						),
						('name', slot),
					)
					for slot, binds in struct.get('interfaces', {}).items()
				)
			),
		)),
		('executable', struct.get('executable')),
		('concurrency', struct.get('concurrency')),
		('type', struct["type"]),
		('abstract', struct.get('abstract')),
		namespace=ns,
	)

def service_routes(route=default_route):
	"""
	Collect the routes to the set of services in the directory.
	"""

	# Only interested in directories.
	for i in route.subnodes()[1]:
		bn = i.basename
		yield bn, i

class Service(object):
	"""
	faultd service state.

	Represents the faultd service stored on disk. The load and store methods are used
	to perform the necessary updates to or from disk.
	"""

	def libexec(self, recreate=False, root="root"):
		"""
		Return the path to a hardlink for the service. Create if absent.
		"""

		root = self.coservice(root)
		led = root.route / "libexec"

		if self.type == 'root':
			exe = led / 'faultd'
		else:
			exe = led / self.name

		fp = exe.fullpath

		if recreate:
			exe.void()

		if not exe.exists():
			led.init("directory")
			os.link(self.executable, fp)

		return fp

	def coservice(self, service):
		"""
		Return the Service instance to the &service in the same set.
		"""

		if service == self.name:
			return self

		return self.__class__(self.faultd, service)

	def __init__(self, route, service):
		self.faultd = +route
		self.name = self.service = service
		self.route = route / service

		self.executable = None
		self.requirements = []
		self.environment = {}
		self.parameters = []
		self.abstract = None
		self.enabled = None
		self.type = 'unspecified'
		self.interfaces = {}
		self.concurrency = None

		# sectors
		self.libraries = None

	def critical(self, message):
		"""
		Log a critical message. Usually used by &.bin.rootd and
		&.bin.sectord.
		"""

		logfile = self.route / "critical.log"
		ts = libtime.now().select('iso')

		with logfile.open('a') as f:
			f.write('%s: %s\n' %(ts, message))

	def trim(self):
		"""
		Trim the critical log in the service's directory.

		! PENDING:
			Not implemented.
		"""

		pass

	def execution(self):
		"""
		Return a tuple consisting of the executable and the parameters.
		"""

		if self.type == 'root':
			exe = self.libexec('faultd')
			return exe, ['faultd'] + (self.parameters or [])
		elif self.type == 'sectors':
			exe = self.libexec(self.name)
			return exe, [self.name] + (self.parameters or [])
		else:
			# daemon or command
			return self.executable, [self.executable] + (self.parameters or [])

	def create(self, type, types=types):
		"""
		Create the service directory and initialize many of the configuration files.

		There are three types that may be created: "command", "daemon", and "sectors".

		"command" types are simple commands that are executed exclusively. The
		faultd process provides the necessary synchronization to avoid concurrent invocations.
		Any requests to run the command while it's running will induce no effect.

		"daemon" types are daemon processes spawned to remain within the process tree.
		Additional retry logic is used to manage daemons in order to guarantee that a reasonable
		attempt was made to start them.

		"sectors" is a daemon, but understood to be a fault.io based process. Configuration
		changes to the process will sometimes be dynamically modified without restart
		or reload operations as the root process will provide a control interface that can
		be used to propagate changes.
		"""

		if type not in types:
			raise ValueError("unknown service type: " + type)

		self.enabled = False
		self.type = type
		self.prepare()
		self.store()

		self.critical("created service")

	def void(self):
		"""
		Destroy the service directory.
		"""

		self.route.void()

	def exists(self):
		"""
		Whether or not the service directory exists.
		"""

		return self.route.exists()

	def prepare(self):
		"""
		Create the service directory and any type specific subnodes.
		"""

		self.route.init("directory")

		if self.type in ('sectors', 'root'):
			if_dir = (self.route / 'if')
			if_dir.init("directory")

			if self.type == 'root':
				(self.route / 'libexec').init("directory")

	def load(self):
		"""
		Load the service definition from the filesystem.
		"""

		self.load_enabled()
		self.load_invocation()

	def store(self):
		"""
		Store the service definition to the filesystem.
		"""

		self.store_invocation()
		self.store_enabled()

	# one pair for each file
	invocation_attributes = (
		'libraries',
		'executable',
		'requirements',
		'environment',
		'parameters',
		'abstract',
		'type',
		'interfaces',
		'concurrency',
	)

	@property
	def parts(self):
		return {
			x: self.__dict__[x]
			for x in self.invocation_attributes
		}

	def load_invocation(self):
		inv_r = self.route / "invocation.xml"
		data = inv_r.load()
		if data:
			inv = extract(data)
		else:
			inv = None

		if inv is not None:
			for k, v in inv.items():
				self.__dict__[k] = v
			if self.type == 'sectors':
				if self.libraries is None:
					self.libraries = {}

	def store_invocation(self):
		xml = b''.join(construct(self.parts))
		inv_r = self.route / "invocation.xml"
		inv_r.store(xml)

	def load_enabled(self, map={'true':True, 'false':False}):
		en_r = self.route / "enabled"
		text = en_r.load().decode('ascii')
		self.enabled = map.get(text.strip().lower(), False)

	def store_enabled(self):
		en_r = self.route / "enabled"
		en_r.store(str(self.enabled).lower().encode('ascii')+b'\n')

	def load_pid(self):
		pid_r = self.route / "pid"
		self.pid = int(pid_r.load().decode('ascii').strip())

	def store_pid(self):
		pid_r = self.route / "pid"
		pid_r.store(str(self.pid).encode('ascii')+b'\n')

	@property
	def status(self):
		"""
		Get and set the contents of the status file in the Service directory.
		"""

		return (self.route / "status").load().decode('utf-8').strip()

	@status.setter
	def status(self, val):
		"""
		Valid values: 'terminated', 'running', 'initializing', 'exception'.
		"""

		status_r = self.route / "status"
		status_r.store(str(val).encode('utf-8')+b'\n')

