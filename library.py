"""
Commons area. Most functionality lives in nucleus modules with descriptive names.
"""
import os
import sys
import functools
import collections
import contextlib
import inspect
import weakref
import queue

from . import core
from . import traffic
from .kernel import Interface as Kernel

from ..fork import library as forklib # cpu and memory
from ..fork import libhazmat

from ..internet import library as netlib
from ..internet import libri

def profile(hostname = None):
	"""
	Dictionary containing a profile of the machine's components.
	"""
	import psutil
	import platform
	import sys
	import resource
	from ..chronometry import library as timelib

	boot = timelib.unix(psutil.boot_time())

	machine = {
		'boot': boot,
		'architecture': platform.machine(),
		'cpu': {
			'physical': psutil.cpu_count(logical=False),
			'logical': psutil.cpu_count(),
		},
		'memory': {
			'capacity': psutil.virtual_memory().total
		}
	}

	os = {
		'name': platform.system(),
		'version': platform.release(),
		'network': {
			'hostname': hostname or platform.node(),
			'net': psutil.net_io_counters(True),
		},
		'memory': {
			'pagesize': resource.getpagesize(),
		}
	}

	python = {
		'name': 'python',
		'implementation': platform.python_implementation(),
		'version': platform.python_version_tuple(),
		'compiler': platform.python_compiler(),
		'abi': sys.abiflags,
	}

	return {
		'machine': machine,
		'system' : os,
		'substrate': {
			'python': python,
		}
	}

class Port(int):
	"""
	System port[file descriptor] indicator. System endpoint address.

	Ports can be associated with arbitrary endpoints.
	"""
	__slots__ = ()

	def __str__(self):
		return 'spi://' + int.__str__(self)

class Endpoint(tuple):
	"""
	A process-local endpoint. These objects are pointers to [logical] process objects.
	"""
	__slots__ = ()
	protocol = 'ps' # Process[or Program] Space

	@property
	def program(self):
		'The absolute program name; &None if subjective reference.'
		return self[0]

	@property
	def pid(self):
		"""
		The process identifier pointing to the location of the endpoint.
		Necessary in interprocess communication.
		"""
		return self[4]

	@property
	def path(self):
		"""
		The path in the structure used to locate the container.
		"""
		if not self.directory:
			return self[1][:-1]

	@property
	def identifier(self):
		"""
		Last component in the path if it's not a directory.
		"""
		if not self.directory:
			return self[1][-1]

	@property
	def directory(self):
		"""
		Endpoint refers to the *directory* of the location, not the assigned object.
		"""
		return self[2]

	@property
	def validation(self):
		"""
		A unique identifier selecting an object within the &core.Object.
		Usually the result of an &id call of a particular object
		"""
		return self[3]

	def __str__(self, formatting = "{0}{4}/{1}{2}{3}"):
		one = '/'.join(self.path)
		three = two = ''
		if self.directory:
			two = '/'
		if self.validation is not None:
			three = '#' + str(self.validation)

		if self.program:
			zero = "ps://" + self.program
		else:
			zero = "/"

		if self.pid is not None:
			four = ":" + str(self.pid)

		return formatting.format(zero, one, two, three, four)

	@classmethod
	def parse(Class, psi):
		"""
		Parse an IRI-like indicator for selecting a process object.
		"""
		dir = False
		d = libri.parse(psi)

		path = d.get('path', ())
		if path != ():
			if path[-1] == '':
				pseq = path[:-1]
				dir = True
			else:
				pseq = path
		else:
			pseq = ()

		port = d.get('port', None)

		return Class(
			(d['host'], tuple(pseq), dir, d.get('fragment', None), port)
		)

	@classmethod
	def local(Class, *path, directory = False):
		"""
		Construct a local reference using the given absolute path.
		"""
		return Class((None, path, directory, None, None))

	def dereference(self, program = None, process = None):
		if program is None:
			program = core.__process_index__[process][self.program]

		# specific object?
		dir = program.index.get(self.path, None)
		if dir is None:
			# file not found
			return None

		path = self.path
		eid = self.eid

		if self.directory:
			# it's a directory reference, so no entry object
			return (program, path, None)
		else:
			eid = self.identifier
			if eid is None:
				return (program, path, program.index[path])
			else:
				return (program, path, program.index[path].access(eid))

class Pipeline(object):
	"""
	Manages the set of information regarding an executed pipeline.
	"""
	__slots__ = ('identifiers', 'commands', 'pids', 'errors', 'status', 'input', 'output')

	def __init__(self, names, commands):
		self.identifiers = tuple(names)
		self.commands = tuple(commands)
		ncommands = len(self.commands)
		self.pids = [None] * ncommands
		self.errors = [None] * ncommands
		self.status = [None] * ncommands
		self.input = None
		self.output = None

	def spawn(self):
		n = len(self.commands)

		# one for each command, split read and write ends into separate lists
		stderr = []
		pipes = []

		for i in range(n):
			stderr.append(os.pipe())

		self.errors = [x[0] for x in stderr]
		stderr = [x[1] for x in stderr]

		# first stdin and final stdout
		for i in range(n+1):
			pipes.append(os.pipe())

		self.input = pipes[0][1]
		self.output = pipes[-1][0]

		try:
			for i in range(0, len(self.commands)):
				command = self.commands[i]
				self.pids[i] = spawn(command, stdin = pipes[i][0], stdout = pipes[i+1][1], stderr = stderr[i])
		finally:
			# fd's inherited in the child processes
			os.close(pipes[0][0])
			os.close(pipes[-1][1])
			for r, w in pipes[1:-2]:
				os.close(r)
				os.close(w)

class Program(core.Resource):
	"""
	An asynchronous Program.

	These objects are used to manage the running state of a part of a &LogicalProcess,
	and to provide introspective interfaces for it.
	"""
	def __init__(self, identifier):
		self.identifier = identifier
		self.terminated = None

		self.roots = []
		self.structure = {}
		self.index = {}

	def initialize(self, *mains, process = None, context = None, Context = None):
		# make sure we have a context
		if context is None:
			context = Context(process)
			context.associate(self)
			self.context = context

		self.roots.extend(mains)

	def execute(self):
		"""
		Execute the program by enqueueing the initialization functions.

		This should only be called by the controller of the program.
		Normally, it is called automatically when the program is loaded by the process.
		"""
		if self.terminated is not None:
			return

		for program_initializor in self.roots:
			program_initializor(self)

		self.terminated = False

	def terminate(self, _process_index = core.__process_index__):
		if self.terminated is not True:
			if _process_index[self.context.process][None] is self:
				self.context.process.terminate(self.result)
				self.terminated = True
			else:
				self.terminated = True

	def place(self, obj, *destination):
		"""
		Place the given object in the program at the specified location.
		"""
		self.index[destination] = obj

		try:
			# build out path
			p = self.structure
			for x in destination:
				if x in p:
					p = p[x]
				else:
					p[x] = dict()

			obj.location = Endpoint.local(*destination)
		except:
			del self.index[destination]
			raise

	def delete(self, *address):
		obj = self.index[address]
		obj.location_path = None
		del self.index[address]

	def listdir(self, *address):
		"""
		List the contents of an address.
		This only includes subdirectories.
		"""
		p = self.structure
		for x in address:
			if x in p:
				p = p[x]
			else:
				break
		else:
			return list(p.keys())
		# no directory
		return None

class Context(object):
	"""
	Execution context class providing access to per-context resource acquisition.

	Manages dedicated threads, general processing threads, memory allocation,
	flow constructors, environment variable access and local overrides, contextual tasks,
	pipeline construction, child management.
	"""
	inheritance = ('environment',)

	def __init__(self, process):
		self.process = process
		self.context = None # weak reference to the context that this context was based on
		self.association = None
		self.environment = ()

	def associate(self, obj):
		"""
		Associate the context with a particular process object, &point.

		Only one association may exist and implies that the context will be terminated
		after the object has finished its work.
		"""
		self.association = weakref.ref(obj)

	def enqueue(self, *tasks):
		self.process.enqueue(*tasks)

	def dispatch(self, controller, task):
		fenqueue = self.process.fabric.enqueue
		fenqueue(controller, task)

	def environ(self, identifier):
		"""
		Access.
		"""
		if identifier in self.environment:
			return self.environment[identifier]

		return os.environ.get(identifier)

	def override(self, identifier, value):
		"""
		Override an environment variable for the execution context.

		Child processes spawned relative to the context will inherit the overrides.
		"""
		if self.environment:
			self.environment[identifier] = value
		else:
			self.environment = {}
			self.environment[identifier] = value

	def inherit(self, context):
		"""
		Inherit the context's exports.
		"""
		raise Exception("not implemented")

	def kio(self, *io, Transformer = core.Detour):
		"""
		Allocate a set of Transformers for performing I/O with the kernel.
		Returns a sequence the same length as the &requests given.
		"""
		area = self.association() # usually Program instance

		with self.process.io(area) as alloc:
			for x in io:
				ip = x.interface
				r = x.route

				if x.transmission == 'octets':
					locator = ('octets', r.protocol)
					i = Transformer()
					o = Transformer()

					rw = alloc(locator, (str(r.address), r.port))
					i.install(rw[0])
					o.install(rw[1])

					return (i, o)
				elif x.transmission == 'sockets':
					locator = ('sockets', r.protocol)
					i = Transformer()
					r = alloc(locator, (str(r.address), r.port))
					r.link = i
					i.transit = r

					return r
				else:
					pass
		# with process.io

class Fabric(object):
	"""
	Thread manager for logical processes;
	Logical process thread pool with capacity to manage dedicated threads.
	"""
	Queue = queue.Queue

	def __init__(self, process, minimum = 1, maximum = 16):
		self.process = weakref.proxy(process) # report unhandled thread exceptions
		self.minimum = minimum
		self.maximum = maximum

		self.gpt = dict() # general purpose threads
		self.dpt = dict() # dedicated purpose threads

		self.general_purpose_queue = self.Queue()

	def execute(self, controller, callable, *args):
		"""
		Create a dedicated thread and execute the given callable within it.
		"""
		self.spawn(weakref.ref(controller), callable, args)

	def critical(self, controller, context, callable, *args):
		"""
		Create a dedicated thread that is identified as a critical resource where exceptions
		trigger &forklib.Panic exceptions.

		The additional &context parameter is an arbitrary object describing the resource;
		often the object whose method is considered critical.
		"""
		self.spawn(weakref.ref(controller), forklib.critical, (context, callable) + args)

	def spawn(self, controller, callable, args, create_thread = libhazmat.create_thread):
		"""
		Add a thread to the context's fabric.
		This expands the "parallel" capacity of the logical process.
		"""
		tid = create_thread(self.thread, (controller, (callable, args)))
		return tid

	def thread(self, *parameters, gettid = libhazmat.identify_thread):
		"""
		Manage the execution of a general purpose thread or a dedicated thread.
		"""
		controller, thread_root = parameters
		tid = gettid()

		try:
			if controller is None:
				self.gpt[tid] = None
			else:
				self.dpt[tid] = parameters

			thread_call, thread_args = thread_root
			del thread_root

			return thread_call(*thread_args)
		finally:
			if controller is None:
				del self.gpt[tid]
			else:
				del self.dpt[tid]

	def loop(self, *parameters, gettid = libhazmat.identify_thread):
		"""
		Internal use only.

		Function used to manage threads in a logical process's fabric.
		This function is called within a new thread.
		"""
		controller, queue = parameters
		assert controller is None # controller is implicitly LogicalProcess

		get = queue.get
		tid = gettid()
		self.gpt[tid] = locals()

		while True:
			try:
				task = None
				controller, task = get()
				if task is None:
					break

				r = task()
				if r is not None:
					# sync result if any
					self.process.enqueue(r)
			except BaseException as err:
				self.exception(task, err, title = "General Purpose Thread")
			finally:
				pass

	def executing(self, tid):
		'Whether or not the given thread [identifier] is executing in this Fabric instance.'
		return tid in self.dpt or tid in self.gpt

	def increase(self, count = 1):
		"""
		Increase the general purpose thread count.
		"""
		for x in range(count):
			self.spawn(None, self.loop, (None, self.general_purpose_queue,))

	def descrease(self, count = 1):
		"""
		Reduce the general purpose thread count.
		"""
		for x in range(count):
			# None signal .thread() to exit
			self.general_purpose_queue.put(None)

	def enqueue(self, controller, task):
		"""
		Execute the given task in a general purpose thread. A new thread will *not* be created.
		"""
		qsize = self.general_purpose_queue.qsize()
		self.general_purpose_queue.put((controller, task))
		return qsize

class LogicalProcess(object):
	"""
	A logical process.

	Usually only one @LogicalProcess is active per-process, but it is reasonable to launch multiple
	in order to perform operations that would otherwise expect its own space.
	"""

	@staticmethod
	def current(tid = libhazmat.identify_thread):
		"""
		Resolve the current logical process based on the thread's identifier.
		@None is returned if the thread was not created by a @LogicalProcess.
		"""
		x = tid()
		for y in core.__process_index__:
			if y.fabric.executing(x):
				return y

	@classmethod
	def spawn(Class, invocation, programs, identifier = 'root'):
		"""
		Construct a booted &LogicalProcess using the given &invocation
		with the specified Programs.
		"""
		lp = Class(identifier, invocation = invocation)
		lpd = core.__process_index__[lp] = {}

		inits = []
		for identifier, roots in programs.items():
			program = Program(identifier)
			program.initialize(*roots, process = lp, Context = Context)
			program.location = (lp.identifier,)
			lpd[identifier] = program

			lp._enqueue(program.execute)

		lpd[None] = program # determines primary program
		return lp

	def log(self, data):
		"""
		Append only access to a *critical* process log. Usually points to &sys.stderr and
		primarily used for process related issues. Normally inappropriate for &Program's.
		"""
		self._logfile.write(data)

	def boot(self, *tasks):
		"""
		Boot the Context with the given tasks enqueued in the Task queue.
		"""
		if self.kernel is not None:
			raise Exception("already booted")

		# kernel interface: watch pid exits, process signals, and enqueue events
		self.kernel = Kernel()
		self.enqueue(*tasks)

		self.fabric.increase(1)
		self.fabric.spawn(None, self.main, ())

		# replace boot() with protect() for main thread protection
		forklib.Fork.substitute(forklib.protect)

	def main(self):
		"""
		The main task loop executed by a dedicated thread created by &boot.
		"""
		# Normally
		try:
			self.loop()
		except BaseException:
			self.exception(self.loop, err, title = "Task Loop")
			forklib.panic("exception raised by process loop") # programming error in LogicalProcess.loop

	def terminate(self, exit = None):
		"""
		Terminate the context. If no contexts remain, exit the process.
		"""
		self._exit_stack.__exit__(None, None, None)

		del core.__process_index__[self]
		del core.__traffic_index__[self]

		if not core.__process_index__:
			if exit is None:
				# no exit provided, so use our own exit code
				interject(SystemExit(250).raised)
			else:
				self.invocation.exit(exit)

	def __init__(self, identifier, invocation = None):
		# Context Wide Resources
		self.identifier = identifier
		self.invocation = invocation # exit resource and invocation parameters

		# track number of loop and designate maintenance frequency
		self.cycles = 0 # count of task cycles
		self.maintenance_frequency = 256 # in task cycles

		self._logfile = sys.stderr

		# .kernel.Interface instance
		self.kernel = None

		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		# XXX: does not handle term/void cases.
		self._init_traffic()

	def _init_exit(self):
		self._exit_stack = contextlib.ExitStack()
		self._exit_stack.__enter__()

	def _init_fabric(self):
		self.fabric = Fabric(self)

	def _init_taskq(self, Queue = collections.deque):
		self._tq = (Queue(), Queue())
		self._tq_state = (0, 1)
		self._tq_maintenance = set()

	def _init_traffic(self):
		execute = functools.partial(self.fabric.critical, self, traffic.adapter)
		ix = traffic.library.Interchange(traffic.adapter, execute = execute)
		forklib.fork_child_cleanup.add(ix)
		core.__traffic_index__[self] = ix

	@property
	def interchange(self):
		return core.__traffic_index__[self]

	def io(self, program):
		"""
		Context manage to allocate Transit resources for use by the given Program.
		"""
		return self.interchange.xact(id = program)

	def void(self):
		"""
		Tear down the existing logical process state. Usually internally used after a
		physical process fork.
		"""
		# normally called in fork
		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self.kernel.void()
		self.interchange.void()

	def __repr__(self):
		return "{0}(identifier = {1!r})".format(self.__class__.__name__, self.identifier)

	def report(self, target):
		"""
		Send an overview of the logical process state to the given target.
		"""
		response = "CONTEXT: [{0}]\n".format
		txt = response(self.identifier)
		txt += ' {0}: {1}\n'.format('TASKS', sum(map(len,self._tq)))
		txt += ' {0}: threads {1}, queue {2}\n'.format('FABRIC', len(self.fabric.gpt), self.fabric.general_purpose_queue.qsize())

		nprograms = len(core.__process_index__[self]) - 1
		programs = ' '.join(set([y.identifier for x, y in core.__process_index__[self].items()]))
		txt += ' {0}: {1} {2}\n'.format('PROGRAMS', nprograms, programs)
		target(txt)

	def maintain(self, task):
		"""
		Add a task that is repeatedly executed after each task cycle.
		"""
		if task in self._tq_maintenance:
			self._tq_maintenance.discard(task)
		else:
			self._tq_maintenance.add(task)

	def schedule(context, measure, task):
		"""
		Schedule the task for execution after the period of time @measure elapses.
		"""
		scheduler = libharm.Harmony()

		p = scheduler.period()
		t = (measure, task)
		scheduler.put(t)
		if p is None or p > measure:
			context.kernel.alarm(scheduler.period() // 10000)
		return t

		def transact(scheduler, context):
			"""
			Process the alarm event that occurred in the given context.
			"""
			current = scheduler.get()
			context.enqueue(*[event for (time, event) in current])

			# schedule the next period
			p = scheduler.period()
			if p is not None:
				context.kernel.alarm(p // 10000)

	def exception(self, context, error, title = "Unspecified Execution Area"):
		"""
		Exception handler for the @LogicalProcess instance.

		Normally, *all* unhandled exceptions should be sent here for reporting.
		"""
		error.__traceback__ = error.__traceback__.tb_next

		# exception reporting facility
		self.log("[Exception from %s: %r]\n" %(title, context,))
		sys.excepthook(error.__class__, error, error.__traceback__)

	def maintenance(self):
		# tasks to run after every cycle
		tasks = list(self._tq_maintenance)

		for task in tasks:
			try:
				task() # maintenance task
			except BaseException as e:
				self.exception(task, e, title = 'Maintenance',)

	def loop(self, _swap = {
			(0, 1) : (1, 0),
			(1, 0) : (0, 1),
		},
		len = len,
	):
		cwq = None # current working queue
		nwq = None # next working queue

		while self._tq is not None:
			self.cycles += 1 # bump cycle

			# The consumed queue becomes the loading and the loading will be consumed.
			self._tq_state = _swap[self._tq_state]

			cwq = self._tq[self._tq_state[0]]
			nwq = self._tq[self._tq_state[1]]

			# The swap is performed this way to avoid unnecessary locks.
			# The setting of the _tq_state changes the queue that will be
			# loaded by .enqueue(...).

			if cwq:
				while cwq:
					# consume queue
					try:
						pop = cwq.popleft
						while cwq:
							task = pop()
							task() # perform the enqueued task
					except BaseException as e:
						self.exception(task, e, title = 'Task',)
			else:
				# no items in queue. wait for signal from Context.enqueue()
				events = ()
				waiting = (len(nwq) == 0 and len(cwq) == 0)

				if self._tq_maintenance and (waiting or self.cycle % self.maintenance_frequency == 0):
					# it's going to wait, so run maintenance
					# XXX need to be able to peek at the kqueue events
					self.maintenance()

				with self.kernel:
					if waiting:
						events = self.kernel.wait()
					else:
						# the next working queue has items, so don't bother waiting.
						events = self.kernel.wait(0)

				# process signals and child exit events
				for event in events:
					print(event)
					if event[0] == 'process':
						y = (pid, termd, status, cored) = libhazmat.process_delta(event[1])
						if termd is None:
							print('process:', y)
					elif event[0] == 'signal':
						control = event[1]
						if control == 'terminal.query':
							self._enqueue(functools.partial(self.report, self.log))
					elif event[0] == 'alarm':
						pass
					elif event[0] == 'recur':
						pass
					elif event[0] == 'file':
						pass
					else:
						# XXX: hazard
						raise RuntimeError(event) # unknown event type
				# for event
			# if-else
		# while

	def _enqueue(self, *tasks):
		self._tq[self._tq_state[1]].extend(tasks)

	def cut(self, *tasks, selection = (0, 1)):
		"""
		Impose the tasks by prepending them to the next working queue.

		Used to enqueue tasks with "high" priority.
		"""
		self._tq[self._tq_state[1]].extendleft(tasks)
		self.kernel.force()

	def enqueue(self, *tasks):
		"""
		Enqueue a task to be ran in the `Tasks` instance's thread.
		"""
		self._tq[self._tq_state[1]].extend(tasks)
		self.kernel.force()

def execute(**programs):
	"""
	Spawn a logical process to represent the invocation from the [operating] system.

	This is the appropriate way to invoke an IO process from an executable module.

		io.library.execute(program_name = (initialize_program,))
	"""
	lp = LogicalProcess.spawn(forklib.Invocation.system(), programs)
	# import root function
	forklib.control(lp.boot)
