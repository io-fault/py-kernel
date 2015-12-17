"""
Public acccess to common Processing classes and process management classes.
"""

import os
import sys
import functools
import collections
import contextlib
import inspect
import weakref
import queue
import traceback
import itertools

from . import core
from . import traffic
from .kernel import Interface as Kernel

from ..fork import library as forklib # cpu and memory
from ..fork import libhazmat

from ..internet import library as netlib
from ..internet import libri

from ..chronometry import library as libtime
from ..routes import library as routeslib

class Context(object):
	"""
	Execution context class providing access to per-context resource acquisition.

	Manages dedicated threads, general processing threads, memory allocation,
	flow constructors, environment variable access and local overrides, contextual tasks,
	pipeline construction, child management.

	Contexts are the view to the &Process and the Kernel of the system running
	the process. Subcontexts can be created to override the default functionality
	and provide a different environment. Contexts are associated with every &core.Resource.
	"""

	inheritance = ('environment',)

	def __init__(self, process):
		"""
		Initialize a &Context instance with the given &process.
		"""

		self.process = process
		self.context = None # weak reference to the context that this context was based on
		self.association = None
		self.environment = ()

	@property
	def unit(self):
		"The &Unit of the association."
		global Unit

		point = self.association()
		while not isinstance(point, Unit):
			point = point.controller

		return point

	def faulted(self, resource):
		"""
		Notify the controlling &Unit instance of the fault.
		"""

		self.unit.faulted(resource)

	def defer(self, measure, task, maximum=6000, seconds=libtime.Measure.of(second=2)):
		"""
		Schedule the task for execution after the period of time &measure elapses.

		&core.Scheduler instances will resubmit a task if there is a substantial delay
		remaining. When large duration defers are placed, the seconds unit are used
		and decidedly inexact, so resubmission is used with a finer grain.
		"""

		# select the granularity based on the measure

		if measure > seconds:
			# greater than two seconds
			quantity = min(measure.select('second'), maximum)
			quantity -= 1
			unit = 's'
		elif measure < 10000:
			# measures are in nanoseconds
			unit = 'n'
			quantity = measure
		elif measure < 1000000:
			unit = 'u'
			quantity = measure.select('microsecond')
		else:
			unit = 'm'
			quantity = min(measure.select('millisecond'), 0xFFFFFFFF)

		return self.process.kernel.alarm(task, quantity, unit)

	def cancel(self, task):
		"""
		Cancel a scheduled task.
		"""

		return self.process.kernel.cancel(task)

	def io(self):
		"""
		Signal the &Process that I/O occurred for this context.

		XXX: Replace with direct Junction references in Transits?
		"""

		unit = self.association()
		self.process.interchange.force(id=unit)

	def inherit(self, context):
		"""
		Inherit the exports from the given &context.
		"""

		raise Exception("not implemented")

	def associate(self, resource, Ref=weakref.ref):
		"""
		Associate the context with a particular &core.Resource object, &resource.

		Only one association may exist and implies that the context will be destroyed
		after the object has finished its work.
		"""

		self.association = Ref(resource)

	def enqueue(self, *tasks):
		"Enqueue the tasks for subsequent processing; used by threads to synchronize their effect."

		self.process.enqueue(*tasks)

	def dispatch(self, controller, task):
		"Execute the given task on a general purpose thread"

		fenqueue = self.process.fabric.enqueue
		fenqueue(controller, task)

	def execute(self, controller, function, *parameters):
		"Execute the given function in a thread associated with the specified controller"

		return self.process.fabric.execute(controller, function, *parameters)

	def environ(self, identifier):
		"""
		Access the environment from the perspective of the context.
		Context overrides may hide process environment variables.
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

	def interfaces(self, *allocs, transmission = 'sockets'):
		"""
		Allocate leaked listening interfaces.
		"""

		unit = self.association()
		if unit is None:
			raise RuntimeError("context has no associated resource")

		r = []
		with self.process.io(unit) as alloc:
			for endpoint in allocs:
				typ = endpoint.protocol
				r.append(alloc((transmission, typ), (str(endpoint.address), endpoint.port)))

		return r

	def bindings(self, *allocs, transmission = 'sockets'):
		"""
		Allocate leaked listening interfaces.

		Returns a sequence of file descriptors that can later be acquired by traffic.
		"""

		alloc = traffic.library.kernel.Junction.rallocate
		unit = self.association()
		if unit is None:
			raise RuntimeError("context has no associated resource")

		for endpoint in allocs:
			typ = endpoint.protocol
			t = alloc((transmission, typ), (str(endpoint.address), endpoint.port))

			fd = t.port.fileno
			t.port.leak()
			t.terminate()
			del t

			yield fd

class Fabric(object):
	"""
	Thread manager for processes; thread pool with capacity to manage dedicated threads.
	"""

	Queue = queue.Queue

	def __init__(self, process, minimum=1, maximum=16, proxy=weakref.proxy):
		self.process = proxy(process) # report unhandled thread exceptions
		self.minimum = minimum
		self.maximum = maximum

		self.gpt = dict() # general purpose threads
		self.dpt = dict() # dedicated purpose threads

		self.general_purpose_queue = self.Queue()

	def void(self):
		"""
		Destroy the thread indexes and general purpose queue.
		Normally used after a process fork on the residual Process.
		"""

		self.gpt.clear()
		self.dpt.clear()
		self.general_purpose_queue.clear()

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
		Add a thread to the fabric.
		This expands the "parallel" capacity of a &Process.
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
		except BaseException as exception:
			self.process.error(controller, exception, "Thread")

	def loop(self, *parameters, gettid = libhazmat.identify_thread):
		"""
		Internal use only.

		Function used to manage threads in a logical process's fabric.
		This function is called within a new thread.
		"""

		controller, queue = parameters
		assert controller is None # controller is implicitly Process

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
				self.error(task, err, title = "General Purpose Thread")
			finally:
				pass

	def executing(self, tid):
		"Whether or not the given thread [identifier] is executing in this Fabric instance."

		return tid in self.dpt or tid in self.gpt

	def increase(self, count = 1):
		"""
		Increase the general purpose thread count.
		"""

		for x in range(count):
			self.spawn(None, self.loop, (None, self.general_purpose_queue,))

	def decrease(self, count = 1):
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

# Process exists here as it is rather distinct from core.*
# It doesn't fall into the classification of a Resource.
class Process(object):
	"""
	The representation of the system process running Python.

	Usually only one &Process is active per-process, but it can be reasonable to launch multiple
	in order to perform operations that would otherwise expect its own space.

	[System Events]

	The &system_event_connect and &system_event_disconnect methods
	are the mechanisms used to respond to child process exits signals.

	[ Properties ]

	/fabric
		The &Fabric instance managing the threads controlled by the process.
	"""

	@staticmethod
	def current(tid = libhazmat.identify_thread):
		"""
		Resolve the current logical process based on the thread's identifier.
		&None is returned if the thread was not created by a &Process.
		"""

		x = tid()
		for y in core.__process_index__:
			if y.fabric.executing(x):
				return y

	@classmethod
	def spawn(Class, invocation, units, identity = 'root'):
		"""
		Construct a booted &Process using the given &invocation
		with the specified &Unit.
		"""

		proc = Class(identity, invocation = invocation)
		lpd = core.__process_index__[proc] = {}

		inits = []
		for identity, roots in units.items():
			unit = Unit()
			unit.requisite(identity, roots, process = proc, Context = Context)
			lpd[identity] = unit
			proc._enqueue(functools.partial(forklib.critical, None, unit.actuate))

		lpd[None] = unit # determines primary program
		return proc

	def log(self, data):
		"""
		Append only access to a *critical* process log. Usually points to &sys.stderr and
		primarily used for process related issues. Normally inappropriate for &Unit
		instances.
		"""

		self._logfile.write(data)
		self._logfile.flush()

	def fork(self, *tasks):
		"""
		Fork the process and enqueue the given tasks in the child.
		Returns a &core.Subprocess instance referring to the Process-Id.
		"""

		global Subprocess

		pid = forklib.Fork.dispatch(self.boot, *tasks)
		subprocess = Subprocess()
		subprocess.requisite((pid,))

		return subprocess

	def boot(self, *tasks):
		"""
		Boot the Context with the given tasks enqueued in the Task queue.
		"""

		if self.kernel is not None:
			raise RuntimeError("already booted")

		forklib.fork_child_cleanup.add(self.void)

		# kernel interface: watch pid exits, process signals, and enqueue events
		self.kernel = Kernel()
		self.enqueue(*[functools.partial(forklib.critical, None, x) for x in tasks])

		self.fabric.increase(1) # general purpose threads
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
		except BaseException as critical_loop_exception:
			self.error(self.loop, critical_loop_exception, title = "Task Loop")
			raise
			raise forklib.Panic("exception escaped process loop") # programming error in Process.loop

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
				forklib.interject(forklib.SystemExit(250).raised)
			else:
				self.invocation.exit(exit)

	def __init__(self, identity, invocation = None):
		"""
		Initialize the &Process instance using the designated &identity.
		The identity is essentially arbitrary, but must be hashable as it's
		used to distinguish one &Process from another. However,
		usually there is only one process, so "root" or "main" is often used.

		Normally, &execute is used to manage the construction of the &Process instance.
		"""
		# Context Wide Resources
		self.identity = identity
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
		self._init_system_events()
		# XXX: does not handle term/void cases.
		self._init_traffic()

	def _init_exit(self):
		self._exit_stack = contextlib.ExitStack()
		self._exit_stack.__enter__()

	def _init_system_events(self):
		self.system_event_connections = {}
		self.system_event_connect(('signal', 'terminal.query'), None, self.report)

	def _init_fabric(self):
		self.fabric = Fabric(self)

	def _init_taskq(self, Queue = collections.deque):
		self.loading_queue = Queue()
		self.processing_queue = Queue()
		#self._tq = (Queue(), Queue())
		#self._tq_state = (0, 1)
		self._tq_maintenance = set()

	def _init_traffic(self, Interchange=traffic.library.Interchange):
		execute = functools.partial(self.fabric.critical, self, traffic.adapter)
		ix = Interchange(traffic.adapter, execute = execute)
		core.__traffic_index__[self] = ix

	@property
	def interchange(self):
		global core
		return core.__traffic_index__[self]

	def io(self, unit):
		"""
		Context manager to allocate Transit resources for use by the given Unit.
		"""

		return self.interchange.xact(id = unit)

	def void(self):
		"""
		Tear down the existing logical process state. Usually used internally after a
		physical process fork.
		"""

		# normally called in fork
		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self._init_system_events()
		self.kernel.void()
		self.kernel = None
		self.interchange.void()

	def __repr__(self):
		return "{0}(identity = {1!r})".format(self.__class__.__name__, self.identity)

	actuated = True
	terminated = False
	terminating = None
	interrupted = None
	def structure(self):
		"""
		Structure information for the &Unit device entry.
		"""
		sr = ()

		# processing_queue is normally empty whenever report is called.
		ntasks = sum(map(len, (self.loading_queue, self.processing_queue)))
		ngthreads = len(self.fabric.gpt)
		nftasks = self.fabric.general_purpose_queue.qsize()
		nunits = len(core.__process_index__[self]) - 1

		p = [
			('pid', forklib.current_process_id),
			('tasks', ntasks),
			('threads', ngthreads),
			('general tasks', nftasks),
			('units', nunits),
			('executable', sys.executable),
		]

		python = os.environ.get('PYTHON')
		p.append(('python', python))

		return (p, sr)

	def report(self, target=sys.stderr):
		"""
		Send an overview of the logical process state to the given target.
		"""

		txt = "[%s]\n" %(libtime.now().select('iso'),)

		units = set(core.__process_index__[self].values())
		for unit in units:
			txt += '\n'.join(core.format(unit.identity, unit))

		target.write(txt)
		target.write('\n')
		target.flush()

	def maintain(self, task):
		"""
		Add a task that is repeatedly executed after each task cycle.
		"""

		if task in self._tq_maintenance:
			self._tq_maintenance.discard(task)
		else:
			self._tq_maintenance.add(task)

	def error(self, context, exception, title = "Unspecified Execution Area"):
		"""
		Exception handler for the &Process instance.

		This handler is called for unhandled exceptions.
		"""

		exc = exception
		exc.__traceback__ = exc.__traceback__.tb_next

		# exception reporting facility
		formatting = traceback.format_exception(exc.__class__, exc, exc.__traceback__)
		formatting = ''.join(formatting)

		self.log("[Exception from %s: %r]\n%s" %(title, context, formatting))

	def maintenance(self):
		# tasks to run after every cycle
		tasks = list(self._tq_maintenance)

		for task in tasks:
			try:
				task() # maintenance task
			except BaseException as e:
				self.error(task, e, title = 'Maintenance',)

	def loop(self, len=len, partial=functools.partial, BaseException=BaseException):
		"""
		Internal loop that processes the task queue. Executed by &boot in a thread
		managed by &fabric.
		"""

		cwq = self.processing_queue # current working queue; should be empty at start
		nwq = self.loading_queue # next working queue
		sec = self.system_event_connections

		task_queue_interval = 2
		default_interval = sys.getswitchinterval() / 5
		setswitchinterval = sys.setswitchinterval

		# discourage switching while processing task queue.
		setswitchinterval(2)

		while 1:
			self.cycles += 1 # bump cycle

			# The processing queue becomes the loading and the loading becomes processing.
			self.processing_queue, self.loading_queue = cwq, nwq = nwq, cwq
			append = nwq.append

			while cwq:
				# consume queue
				try:
					pop = cwq.popleft
					while cwq:
						task = pop()
						task() # perform the enqueued task
				except BaseException as e:
					self.error(task, e, title = 'Task',)

			# This appears undesirable, but the alternative
			# is to run force for each process local I/O event.
			# Presuming that some I/O has occurred while processing
			# the queue is not actually much of a stretch.
			self.interchange.activity()

			events = ()
			waiting = (len(nwq) == 0 and len(cwq) == 0)

			if self._tq_maintenance and (waiting or self.cycle % self.maintenance_frequency == 0):
				# it's going to wait, so run maintenance
				# XXX need to be able to peek at the kqueue events
				self.maintenance()

			try:
				# Change the interval to encourage switching in Python threads.
				setswitchinterval(default_interval)

				with self.kernel:
					# Sets a flag inside the kernel structure indicating
					# that a wait is about to occur; if the flag isn't
					# set, a user event is not sent to the kqueue as it
					# is unnecessary.

					if waiting:
						events = self.kernel.wait()
					else:
						# the next working queue has items, so don't bother waiting.
						events = self.kernel.wait(0)
			finally:
				setswitchinterval(2)

			# process unix signals and child exit events
			for event in events:
				remove_entry = False

				if event[0] == 'process':
					event = ('process', event[1])
					args = (event[1], libhazmat.process_delta(event[1]),)
					remove_entry = True
				elif event[0] == 'alarm':
					append(event[1])
					continue
				else:
					args = ()

				if event in sec:
					callback = sec[event][1] # system_event_connections
					if remove_entry:
						# process events only occur once
						del sec[event]

					append(partial(callback, *args))
				else:
					# note unhandled system events
					print('unhandled event', event)

			# for event
		# while True

	def system_event_connect(self, event, resource, callback):
		"""
		Connect the given callback to system event, &event.
		System events are given string identifiers.
		"""

		self.system_event_connections[event] = (resource, callback)

	def system_event_disconnect(self, event):
		"""
		Disconnect the given callback from the system event.
		"""

		if event not in self.system_event_connections:
			return False

		del self.system_event_connections[event]
		return True

	def _enqueue(self, *tasks):
		self.loading_queue.extend(tasks)

	def cut(self, *tasks):
		"""
		Impose the tasks by prepending them to the next working queue.

		Used to enqueue tasks with "high" priority. Subsequent cuts will
		precede the earlier ones, so it is not appropriate to use in cases were
		order is significant.
		"""

		self.loading_queue.extendleft(tasks)
		self.kernel.force()

	def enqueue(self, *tasks):
		"""
		Enqueue a task to be ran.
		"""

		self.loading_queue.extend(tasks)
		self.kernel.force()

# core exports
endpoint = core.endpoint
#Port = core.Port
Endpoint = core.Endpoint
Local = core.Local
Projection = core.Projection
Layer = core.Layer # Base class for all layer contexts
Interface = core.Interface

Resource = core.Resource
Extension = core.Extension
Device = core.Device

Transformer = core.Transformer
Functional = core.Functional
Reactor = core.Reactor # Transformer
Parallel = core.Parallel
Generator = core.Generator

Collect = core.Collect
Iterate = core.Iterate
Spawn = core.Spawn

Terminal = core.Terminal
Trace = core.Trace

Processor = core.Processor
Unit = core.Unit
Sector = core.Sector
Library = core.Library
Executable = core.Executable
Control = core.Control
Subprocess = core.Subprocess
Scheduler = core.Scheduler

# Common Processors inside Sectors
Coroutine = core.Coroutine
Flow = core.Flow
Thread = core.Thread
Call = core.Call
Protocol = core.Protocol

Null = core.Null

def execute(*identity, **units):
	"""
	Initialize a &Process to represent the invocation from the [operating] system.

	This is the appropriate way to invoke an fault.io process from an executable module.

	#!/pl/python
		io.library.execute(unit_name = (unit_initialization,))

	Creates a &Unit instance that is passed to the initialization function where
	its hierarchy is then populated with &Sector instances.
	"""

	if identity:
		ident, = identity
	else:
		ident = 'root'

	sp = Process.spawn(forklib.Invocation.system(), units, identity=ident)
	# import root function
	forklib.control(sp.boot)
