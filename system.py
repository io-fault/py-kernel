"""
# Process management classes.

# Implements the thread management and process representation management necessary
# to work with a set of &.library.Unit instances. &Context instances are indirectly
# associated with the &.library.Unit instances in order to allow &.library.Processor
# instances to cache access to &Context.enqueue.

# [ Properties ]

# /__process_index__/
	# Indirect association of &Proces and &Context
# /__traffic_index__/
	# Indirect association of Logical Process objects and traffic Interchanges.
	# Interchange holds references back to the process.
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
import typing
import signal # masking SIGINT/SIGTERM in threads.

from . import traffic
from .kernel import Interface as Kernel

from ..system import process
from ..system import thread
from ..system import memory
from ..system import execution as libexec
from ..time import library as libtime

__process_index__ = dict()
__traffic_index__ = dict()

class Context(object):
	"""
	# Execution context class providing access to per-context resource acquisition.

	# Manages allocation of kernel provided resources, system command execution, threading,
	# I/O connections.

	# Contexts are the view to the &Process and the Kernel of the system running
	# the process. Subcontexts can be created to override the default functionality
	# and provide a different environment.

	# Contexts are associated with every &.library.Resource.
	"""

	inheritance = ('environment',)

	def __init__(self, process, *api):
		"""
		# Initialize a &Context instance with the given &process.
		"""

		self.process = process
		self.context = process
		self.association = None
		self.environment = ()
		self.attachments = [] # traffic transits to be acquired by a junction

		self._connect, self._input, self._output, self._listen = api

	def associate(self, resource, Ref=weakref.ref):
		"""
		# Associate the context with a particular &.library.Resource object, &resource.

		# Only one association may exist and implies that the context will be destroyed
		# after the object is deleted.

		# Generally used by &.library.Sector instances that are augmenting the execution
		# context for subprocessors.
		"""

		self.association = Ref(resource)

	@property
	def unit(self):
		"""
		# The &Unit of the association.
		"""
		global Unit

		point = self.association()
		while point.controller is not None:
			point = point.controller

		return point

	def faulted(self, resource):
		"""
		# Notify the controlling &Unit instance of the fault.
		"""

		return self.unit.faulted(resource)

	def defer(self, measure, task, maximum=6000, seconds=libtime.Measure.of(second=2)):
		"""
		# Schedule the task for execution after the period of time &measure elapses.

		# &.library.Scheduler instances will resubmit a task if there is a substantial delay
		# remaining. When large duration defers are placed, the seconds unit are used
		# and decidedly inexact, so resubmission is used with a finer grain.
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
		# Cancel a scheduled task.
		"""

		return self.process.kernel.cancel(task)

	def inherit(self, context):
		"""
		# Inherit the exports from the given &context.
		"""

		raise Exception("not implemented")

	def _sys_traffic_cycle(self):
		"""
		# Signal the &Process that I/O occurred for this context.
		"""

		self.process.interchange.force(id=self.association())

	# Primary access to processor resources: task queue, work thread, and threads.
	def _sys_traffic_attach(self, *transits):
		# Enqueue flush once to clear new transits.
		if not self.attachments:
			self.enqueue(self._sys_traffic_flush)
		self.attachments.extend(transits)

	def _sys_traffic_flush(self):
		# Needs main task queue context.
		new_transits = self.attachments
		self.attachments = []

		unit = self.association()
		ix = self.process.interchange
		ix.acquire(unit, new_transits)
		ix.force(id=unit)

		del unit

	def interfaces(self, processor):
		"""
		# Iterator producing the stack of &Interface instances associated
		# with the sector ancestry.
		"""
		sector_scan = processor.controller
		while not isinstance(sector_scan, Unit):
			if isinstance(sector_scan, Sector):
				yield from sector_scan.processors.get(Interface, ())
			sector_scan = sector_scan.controller

	def enqueue(self, *tasks):
		"""
		# Enqueue the tasks for subsequent processing; used by threads to synchronize their effect.
		"""

		self.process.enqueue(*tasks)

	def execute(self, controller, function, *parameters):
		"""
		# Execute the given function in a thread associated with the specified controller.
		"""

		return self.process.fabric.execute(controller, function, *parameters)

	def environ(self, identifier):
		"""
		# Access the environment from the perspective of the context.
		# Context overrides may hide process environment variables.
		"""

		if identifier in self.environment:
			return self.environment[identifier]

		return os.environ.get(identifier)

	def override(self, identifier, value):
		"""
		# Override an environment variable for the execution context.

		# Child processes spawned relative to the context will inherit the overrides.
		"""

		if self.environment:
			self.environment[identifier] = value
		else:
			self.environment = {}
			self.environment[identifier] = value

	def bindings(self, *allocs, transmission = 'sockets'):
		"""
		# Allocate leaked listening interfaces.

		# Returns a sequence of file descriptors that can later be acquired by traffic.
		"""

		alloc = traffic.allocate
		unit = self.association()
		if unit is None:
			raise RuntimeError("context has no associated resource")

		# traffic normally works with transits that are attached to
		# junction, but in cases where it was never acquired, the
		# management operations still work.
		for endpoint in allocs:
			typ = endpoint.protocol
			t = alloc((transmission, typ), (str(endpoint.address), endpoint.port))

			fd = t.port.fileno
			t.port.leak()
			t.terminate()
			del t

			yield fd

	def connect_subflows_using(self, interface, endpoint, mitre, *protocols):
		"""
		# Given an endpoint and a transport stack, return the series used to
		# manage the connection's I/O from the given &interface.

		# [ Parameters ]

		# /interface/
			# The &.library.Endpoint instance describing the interface to use for the
			# connection.

		# /endpoint/
			# The &.library.Endpoint instance describing the target of the connection.

		# /protocols/
			# A sequence of transport layers to use with the &.library.Transport instances.
			# A &.library.Transport pair will be created even if &protocols is empty.
			# This parameter might be merged into the mitre.
		"""

		transits = traffic.allocate(
			('octets', endpoint.protocol), (str(endpoint.address), endpoint.port)
			# XXX: interface ref
		)
		return self._connect(mitre, transits, *protocols)

	def connect_subflows(self, endpoint, mitre, *protocols):
		"""
		# Given an endpoint and a transport stack, return the series used to
		# manage the connection's I/O.

		# [ Parameters ]

		# /endpoint/
			# The &.library.Endpoint instance describing the target of the connection.

		# /protocols/
			# A sequence of transport layers to use with the &.library.Transport instances.
			# A &.library.Transport pair will be created even if &protocols is empty.
			# This parameter might be merged into the mitre.
		"""

		transits = traffic.allocate(('octets', endpoint.protocol), (str(endpoint.address), endpoint.port))
		return self._connect(mitre, transits, *protocols)

	def accept_subflows(self, fd, mitre, *protocols):
		"""
		# Given a file descriptor and a transport stack, return the series used to
		# manage the connection's I/O.

		# [ Parameters ]
		# /fd/
			# The &.library.Endpoint instance describing the target of the connection.
		# /protocols/
			# A sequence of transport layers to use with the &.library.Transport instances.
			# A &.library.Transport pair will be created even if &protocols is empty.
			# This parameter might be merged into the mitre.
		"""

		transits = traffic.allocate('octets://acquire/socket', fd)
		return self._connect(mitre, transits, *protocols)

	def read_file(self, path):
		"""
		# Open a set of files for reading through a &.library.KernelPort.
		"""

		return self._input(traffic.allocate('octets://file/read', path))

	def append_file(self, path):
		"""
		# Open a set of files for appending through a &.library.KernelPort.
		"""

		return self._output(traffic.allocate('octets://file/append', path))

	def update_file(self, path, offset, size):
		"""
		# Allocate a transit for overwriting data at the given offset of
		# the designated file.
		"""

		t = traffic.allocate(('octets', 'file', 'overwrite'), path)
		position = os.lseek(t.port.fileno, 0, offset)

		return self._output(t)

	def listen(self, interfaces):
		"""
		# On POSIX systems, this performs (system:manual)`bind` *and*
		# (system/manual)`listen` system calls for receiving socket connections.

		# Returns a generator producing (interface, Flow) pairs.
		"""

		alloc = traffic.allocate

		for x in interfaces:
			t = alloc(('sockets', x.protocol), (str(x.address), x.port))
			yield (x, self._listen(t))

	def acquire_listening_sockets(self, kports):
		"""
		# Acquire the transits necessary for the set of &kports, file descriptors,
		# and construct a pair of &KernelPort instances to represent them inside a &Flow.

		# [ Parameters ]

		# /kports/
			# An iterable consisting of file descriptors referring to sockets.

		# [ Returns ]

		# /&Type/
			# Iterable of pairs. First item of each pair being the interface's local endpoint,
			# and the second being the &KernelPort instance.
		"""

		alloc = traffic.allocate

		for kp in kports:
			socket_transit = alloc('sockets://acquire', kp)
			yield (socket_transit.endpoint(), self._listen(socket_transit))

	def connect_output(self, fd):
		"""
		# Allocate &..traffic Transit instances for the given sequence
		# of file descriptors.
		"""

		return self._output(traffic.allocate('octets://acquire/output', fd))

	def connect_input(self, fd):
		"""
		# Allocate &..traffic Transit instances for the given sequence
		# of file descriptors.
		"""

		return self._input(traffic.allocate('octets://acquire/input', fd))

	def daemon(self, invocation, close=os.close) -> typing.Tuple[int, int]:
		"""
		# Execute the &..system.execution.KInvocation instance with stdin and stdout closed.

		# Returns the process identifier and standard error's file descriptor as a tuple.
		"""

		stdout = stdin = stderr = ()

		try:
			try:
				# use dev/null?
				stderr = os.pipe()
				stdout = os.pipe()
				stdin = os.pipe()

				pid = invocation(fdmap=[(stderr[1], 2), (stdout[1], 1), (stdin[0], 0)])
			finally:
				# clean up file descriptors

				for x in stderr[1:]:
					close(x)
				for x in stdout:
					close(x)
				for x in stdin:
					close(x)
		except:
			close(stderr[0])
			raise

		return pid, stderr[0]

	def daemon_stderr(self, stderr, invocation, close=os.close):
		"""
		# Execute the &..system.execution.KInvocation instance with stdin and stdout closed.
		# The &stderr parameter will be passed in as the standard error file descriptor,
		# and then *closed* before returning.

		# Returns a &Subprocess instance containing a single Process-Id.

		# Used to launch a daemon with a specific standard error for monitoring purposes.
		"""

		stdout = stdin = ()

		try:
			# use dev/null?
			stdout = os.pipe()
			stdin = os.pipe()

			pid = invocation(fdmap=[(stderr, 2), (stdout[1], 1), (stdin[0], 0)])
		finally:
			# clean up file descriptors
			close(stderr)

			for x in stdout:
				close(x)
			for x in stdin:
				close(x)

		return pid

	def system_execute(self, invocation:libexec.KInvocation):
		"""
		# Execute the &..system.execution.KInvocation inheriting standard input, output, and error.

		# This is used almost exclusively by shell-type processes where the calling process
		# suspends TTY I/O until the child exits.
		"""

		return Subprocess(invocation())

	def stream_shared_segments(self, path:str, range:tuple, *_, Segments=memory.Segments):
		"""
		# Construct a new Flow with an initial Iterate Transformer
		# flowing shared memory segments from the memory mapped file.

		# Returns a pair, the new Flow and a callable that causes the Flow to begin
		# transferring memory segments.

		# [ Parameters ]
		# /path/
			# Local filesystem path to read from.
		# /range/
			# A triple, (start, stop, size), or &None if the entire file should be used.
			# Where size is the size of the memory slices to emit.
		"""
		global Iteration, Flow

		segs = Segments.open(path, range)
		return Iteration(segs)

class Fabric(object):
	"""
	# Thread manager for processes; thread pool with capacity to manage dedicated threads.
	"""

	def __init__(self, process, proxy=weakref.proxy):
		self.process = proxy(process) # report unhandled thread exceptions
		self.threading = dict() # dedicated purpose threads

	def void(self):
		"""
		# Normally used after a process fork in the child.
		"""

		self.threading.clear()

	def execute(self, controller, callable, *args):
		"""
		# Create a dedicated thread and execute the given callable within it.
		"""

		self.spawn(weakref.ref(controller), callable, args)

	def critical(self, controller, context, callable, *args):
		"""
		# Create a dedicated thread that is identified as a critical resource where exceptions
		# trigger &process.Panic exceptions in the main thread.

		# The additional &context parameter is an arbitrary object describing the resource;
		# often the object whose method is considered critical.
		"""

		self.spawn(weakref.ref(controller), process.critical, (context, callable) + args)

	def spawn(self, controller, callable, args, create_thread=thread.create):
		"""
		# Add a thread to the fabric.
		# This expands the "parallel" capacity of a &Process.
		"""

		tid = create_thread(self.thread, (controller, (callable, args)))
		return tid

	def thread(self, *parameters, gettid=thread.identify):
		"""
		# Manage the execution of a thread.
		"""
		global signal

		# Block INT and TERM from fabric threads.
		# Necessary to allow process.protect()'s sleep function to
		# be interrupted when a signal is received.
		signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})

		controller, thread_root = parameters
		tid = gettid()

		try:
			try:
				self.threading[tid] = parameters

				thread_call, thread_args = thread_root
				del thread_root

				return thread_call(*thread_args)
			finally:
				del self.threading[tid]
		except BaseException as exception:
			self.process.error(controller, exception, "Thread")

	def executing(self, tid):
		"""
		# Whether or not the given thread [identifier] is executing in this Fabric instance.
		"""

		return tid in self.threading

class Process(object):
	"""
	# The representation of the system process running Python. Usually referred
	# to as `process` by &Context and other classes.

	# Usually only one &Representation is active per-process, but it can be reasonable to launch multiple
	# in order to perform operations that would otherwise expect its own space.

	# [ System Events ]

	# The &system_event_connect and &system_event_disconnect methods
	# are the mechanisms used to respond to child process exits signals.

	# [ Properties ]

	# /fabric/
		# The &Fabric instance managing the threads controlled by the process.
	"""

	@staticmethod
	def current(tid=thread.identify):
		"""
		# Resolve the current logical process based on the thread's identifier.
		# &None is returned if the thread was not created by a &Process.
		"""

		x = tid()
		for y in __process_index__:
			if y.fabric.executing(x):
				return y

	def primary(self) -> bool:
		"""
		# Return the primary &.library.Unit instance associated with the process.
		"""

		return __process_index__[self][None]

	@classmethod
	def spawn(Class, invocation, Unit, units, identity='root', critical=process.critical):
		"""
		# Construct a booted &Process using the given &invocation
		# with the specified &Unit.
		"""

		proc = Class(identity, invocation = invocation)
		lpd = {}
		__process_index__[proc] = lpd

		inits = []
		for identity, roots in units.items():
			unit = Unit()
			unit.requisite(identity, roots, process = proc, Context = Context)
			lpd[identity] = unit
			proc._enqueue(functools.partial(critical, None, unit.actuate))

		lpd[None] = unit # determines primary program
		return proc

	def log(self, data):
		"""
		# Append only access to a *critical* process log. Usually points to &sys.stderr and
		# primarily used for process related issues. Normally inappropriate for &Unit
		# instances.
		"""

		self._logfile.write(data)
		self._logfile.flush()

	def fork(self, *tasks):
		"""
		# Fork the process and enqueue the given tasks in the child.
		# Returns a &.library.Subprocess instance referring to the Process-Id.
		"""

		return process.Fork.dispatch(self.boot, *tasks)

	def actuate(self, *tasks):
		# kernel interface: watch process exits, process signals, and timers.
		self.kernel = Kernel()
		self.enqueue(*[functools.partial(process.critical, None, x) for x in tasks])
		self.fabric.spawn(None, self.main, ())

	def boot(self, main_thread_calls, *tasks):
		"""
		# Boot the Context with the given tasks enqueued in the Task queue.

		# Only used inside the main thread for the initialization of the
		# controlling processor.
		"""
		global process

		if self.kernel is not None:
			raise RuntimeError("already booted")

		process.fork_child_cleanup.add(self.void)
		for boot_init_call in main_thread_calls:
			boot_init_call()

		self.actuate(*tasks)
		# replace boot() with protect() for main thread protection/watchdog
		process.Fork.substitute(process.protect)

	def main(self):
		"""
		# The main task loop executed by a dedicated thread created by &boot.
		"""

		# Normally
		try:
			self.loop()
		except BaseException as critical_loop_exception:
			self.error(self.loop, critical_loop_exception, title = "Task Loop")
			raise
			raise process.Panic("exception escaped process loop") # programming error in Process.loop

	def terminate(self, exit=None):
		"""
		# Terminate the context. If no contexts remain, exit the process.
		"""
		self._exit_stack.__exit__(None, None, None)

		del __process_index__[self]
		del __traffic_index__[self]

		if not __process_index__:
			if exit is None:
				# no exit provided, so use our own exit code
				process.interject(process.Exit(250).raised)
			else:
				self.invocation.exit(exit)

	def __init__(self, identity, invocation=None):
		"""
		# Initialize the Process instance using the designated &identity.
		# The identity is essentially arbitrary, but must be hashable as it's
		# used to distinguish one &Representation from another. However,
		# usually there is only one process, so "root" or "main" is often used.

		# Normally, &execute is used to manage the construction of the
		# &Process instance.
		"""

		# Context Wide Resources
		self.identity = identity
		self.invocation = invocation # exit resource and invocation parameters

		# track number of loop and designate maintenance frequency
		self.cycle_count = 0 # count of task cycles
		self.cycle_start_time = None
		self.cycle_start_time_decay = None

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
		self._tq_maintenance = set()

	def _init_traffic(self, Interchange=traffic.library.Interchange):
		execute = functools.partial(self.fabric.critical, self, traffic.adapter)
		ix = Interchange(traffic.adapter, execute = execute)
		__traffic_index__[self] = ix

	@property
	def interchange(self):
		"""
		# The &..traffic.library.Interchange instance managing the I/O file descriptors used
		# by the &Process.
		"""
		return __traffic_index__[self]

	def void(self):
		"""
		# Tear down the existing logical process state. Usually used internally after a
		# physical process fork.
		"""

		# normally called in fork
		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self._init_system_events()
		self.kernel.void()
		self.kernel = None
		self.interchange.void()

	def report(self, target=sys.stderr):
		"""
		# Report a snapshot of the process' state to the given &target.
		"""

		target.write("[%s]\n" %(libtime.now().select('iso'),))
		for unit in set(__process_index__[self].values()):
			unit.report(target)

	def __repr__(self):
		return "{0}(identity = {1!r})".format(self.__class__.__name__, self.identity)

	actuated = True
	terminated = False
	terminating = None
	interrupted = None
	def structure(self):
		"""
		# Structure information for the &Unit device entry.
		"""
		sr = ()

		# processing_queue is normally empty whenever report is called.
		ntasks = sum(map(len, (self.loading_queue, self.processing_queue)))
		nunits = len(__process_index__[self]) - 1

		p = [
			('pid', process.current_process_id),
			('tasks', ntasks),
			('threads', len(self.fabric.threading)),
			('units', nunits),
			('executable', sys.executable),

			# Track basic (task loop) cycle stats.
			('cycles', self.cycle_count),
			('frequency', None),
			('decay', self.cycle_start_time_decay),
		]

		python = os.environ.get('PYTHON', sys.executable)
		if python is not None:
			p.append(('python', python))

		return (p, sr)

	def maintain(self, task):
		"""
		# Add a task that is repeatedly executed after each task cycle.
		"""

		if task in self._tq_maintenance:
			self._tq_maintenance.discard(task)
		else:
			self._tq_maintenance.add(task)

	def error(self, context, exception, title = "Unspecified Execution Area"):
		"""
		# Exception handler for the &Representation instance.

		# This handler is called for unhandled exceptions.
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

	def loop(self, partial=functools.partial, BaseException=BaseException):
		"""
		# Internal loop that processes the task queue. Executed by &boot in a thread
		# managed by &fabric.
		"""

		time_snapshot = libtime.now
		ix = self.interchange
		cwq = self.processing_queue # current working queue; should be empty at start
		nwq = self.loading_queue # next working queue
		sec = self.system_event_connections

		task_queue_interval = 2
		default_interval = sys.getswitchinterval() / 5
		setswitchinterval = sys.setswitchinterval

		# discourage switching while processing task queue.
		setswitchinterval(2)

		while 1:
			self.cycle_count += 1 # bump cycle
			self.cycle_start_time = time_snapshot()
			self.cycle_start_time_decay = 1 # Incremented by main thread.

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
			# the queue is not terribly inaccurate.
			ix.activity()

			events = ()
			waiting = (not nwq and not cwq) # both are empty.

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
					# Defer read until system event connect.
					# Might allow SIGCHLD support on linux.
					event = ('process', event[1])
					args = (event[1], libexec.reap(event[1]),)
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
		# Connect the given callback to system event, &event.
		# System events are given string identifiers.
		"""

		self.system_event_connections[event] = (resource, callback)

	def system_event_disconnect(self, event):
		"""
		# Disconnect the given callback from the system event.
		"""

		if event not in self.system_event_connections:
			return False

		del self.system_event_connections[event]
		return True

	def _enqueue(self, *tasks):
		self.loading_queue.extend(tasks)

	def cut(self, *tasks):
		"""
		# Impose the tasks by prepending them to the next working queue.

		# Used to enqueue tasks with "high" priority. Subsequent cuts will
		# precede the earlier ones, so it is not appropriate to use in cases were
		# order is significant.
		"""

		self.loading_queue.extendleft(tasks)
		self.kernel.force()

	def enqueue(self, *tasks):
		"""
		# Enqueue a task to be ran.
		"""

		self.loading_queue.extend(tasks)
		self.kernel.force()
