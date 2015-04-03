"""
Scheduling library for managing processes.
"""
import os
import sys
import functools
import collections
import contextlib
import inspect
import weakref
import queue

from ..chronometry import library as timelib
from ..chronometry import libharm

from ..fork import library as forklib # cpu and memory
from ..fork import libhazmat

from .func import Pair
from . import abstract

def profile(hostname = None):
	"""
	Dictionary containing a profile of the machine's components.
	"""
	import psutil
	import platform
	import sys
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
			'hostname': hostname or platform.node()
		},
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
		'engine': python
	}

__context_index__ = dict()

def identify_context(tid = libhazmat.identify_thread):
	"""
	Resolve the current context based on the thread's identifier.

	@None is returned if the thread was not created by a @Context.
	"""
	x = tid()
	for y in __context_index__:
		if x in y._fabric:
			return y

def thread(context, queue, gettid = libhazmat.identify_thread):
	"""
	Function used to manage threads in a context's fabric.
	This function is called within a new thread.
	"""
	enq = context.enqueue
	get = queue.get
	tid = gettid()

	try:
		while 1:
			try:
				task = None
				task = get()
				if task is None:
					break

				r = task()
				if r is not None:
					# sync result if any
					enq(r)
			except BaseException:
				e.__traceback__ = e.__traceback__.tb_next
				sys.stderr.write("[Thread Exception: %r]\n" %(task or get,))
				sys.excepthook(e.__class__, e, e.__traceback__)
			finally:
				pass
	finally:
		del context._threads[tid]

def callref(decorated, partial = functools.partial):
	"""
	Decorate the given callable such that when the
	function is called, a reference to the call is returned
	rather than the result.

	Invoking a callref is equivalent to::

		return functool.partial(decorated, *args, **kw)
	"""
	def decoration(*args, **kw):
		return partial(decorated, *args, **kw)
	return functools.update_wrapper(decoration, decorated)

def outerlocals(depth = 0):
	"""
	Get the locals dictionary of the calling context.

	If the depth isn't specified, the locals of the caller's caller.
	"""
	if depth < 0:
		raise TypeError("depth must be greater than or equal to zero")

	f = sys._getframe().f_back.f_back
	while depth:
		depth -= 1
		f = f.f_back
	return f.f_locals

class Context(object):
	"""
	A logical process.

	Usually only one Context is active per-process. Context instances conceptually represent a logical
	portion of the process itself.
	"""
	def __repr__(self):
		return "<Context '{0}'>".format(self.identity)

	def __init__(self, identity = 'root'):
		# Context Wide Resources
		self.identity = identity
		self.terminal = sys.stderr

		# .kernel.Interface instance
		self.kernel = None

		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self._processes = {}

	def _init_exit(self):
		self._exit_stack = contextlib.ExitStack()
		self._exit_stack.__enter__()

	def _init_fabric(self, Queue = queue.Queue):
		self._fabricq = Queue()
		self._fabric = dict()
		self.dispatch = self._fabricq.put

	def _init_taskq(self, Queue = collections.deque):
		self._harmony = libharm.Harmony()
		self._tq = (Queue(), Queue())
		self._tq_state = (0, 1)
		self._tq_maintenance = set()

	def void(self):
		"""
		Tear down existing state.
		"""
		# normally called in fork
		self._init_exit()
		self._init_fabric()
		self._init_taskq()
		self.kernel.void()
		self.processes = {}

	def weave(self, *args, association = None, manage = thread, new = libhazmat.create_thread):
		"""
		Add a thread to the context's fabric.
		This expands the "parallel" capacity of the Context.
		"""
		tid = new(manage, (self, self._fabricq))
		self._fabric[tid] = association
		if args:
			task, *args = args
			self.dispatch(functools.partial(task, *args))
		return tid

	def boot(self, *tasks):
		"""
		Boot the Context with the given tasks enqueued in the Task queue.
		"""
		self.__enqueue__(*tasks)

		# kernel interface: watch pid exits, process signals, and enqueue events
		self.kernel = forklib.Kernel()
		self.weave(forklib.critical, self._taskloop)

		# now replace boot() with protect()
		forklib.Fork.substitute(forklib.protect)

	def terminate(self):
		"""
		Terminate the context. If no contexts remain, exit the process.
		"""
		self._exit_stack.__exit__(None, None, None)

		del __context_index__[self]

		if not __context_index__:
			forklib.interject(forklib.Exit(250).raised)

	def _query(self):
		response = "CONTEXT: [{0}]\n".format
		txt = response(self.identity)
		txt += ' {0}: {1}\n'.format('TASKS', sum(map(len,self._tq)))
		txt += ' {0}: threads {1}, queue {2}\n'.format('FABRIC', len(self._fabric), self._fabricq.qsize())
		self.terminal.write(txt)

	def _tq_executor(self, queue, title = "Unspecified"):
		# task queue
		while queue:
			try:
				task = queue.popleft
				while queue:
					task()() # Valve place and/or transfer method.
			except BaseException as e:
				# Report Exception, but don't let it stop the remainder.
				# KeyboardInterrupt and SystemExit should not be thrown by tasks.

				e.__traceback__ = e.__traceback__.tb_next
				sys.stderr.write("[%s Exception: %r]\n" %(title, task,))
				sys.excepthook(e.__class__, e, e.__traceback__)

	def maintain(self, task):
		"""
		Add a task that is repeatedly executed after each cycle.

		This can be used to manage things such as approximate time snapshots.
		"""
		if task in self._tq_maintenance:
			self._tq_maintenance.discard(task)
		else:
			self._tq_maintenance.add(task)

	def schedule(self, measure, task):
		"""
		Schedule the task for execution after the period of time @measure elapses.
		"""
		p = self._harmony.period()
		t = (measure, task)
		self._harmony.put(t)
		if p is None or p > measure:
			self.kernel.alarm(self._harmony.period() // 10000)
		return t

	def _taskloop(self, _swap = {
			(0, 1) : (1, 0),
			(1, 0) : (0, 1),
		},
		now = timelib.clock.monotonic
	):
		harm = self._harmony

		while self._tq is not None:
			# swap, the consumed becomes the fed and fed will be consumed.
			self._tq_state = _swap[self._tq_state]

			# current working queue
			cwq = self._tq[self._tq_state[0]]
			# next working queue
			nwq = self._tq[self._tq_state[1]]

			# The swap is performed to avoid unnecessary locks.
			# The process could be waiting for a signal when in self.kernel.wait(),
			# so in order to avoid superfluous .wait() and .force() invocations,
			# two queues are used: a loading queue and a processing queue.

			if cwq:
				self.process_time_index = now()

				# tasks to run before every cycle
				for mtask in self._tq_maintenance:
					try:
						mtask() # context maintenance task
					except BaseException as e:
						e.__traceback__ = e.__traceback__.tb_next
						sys.stderr.write("[Maintenance Exception: %r]\n" %(mtask,))
						sys.excepthook(e.__class__, e, e.__traceback__)
				while cwq:
					# consume queue
					try:
						pop = cwq.popleft
						while cwq:
							task = pop()
							task() # context task
					except BaseException as e:
						e.__traceback__ = e.__traceback__.tb_next
						sys.stderr.write("[Task Exception: %r]\n" %(task,))
						sys.excepthook(e.__class__, e, e.__traceback__)
					break
			else:
				# no items in queue. wait for tasks.
				events = ()
				with self.kernel:
					events = self.kernel.wait()

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
							self.enqueue(self._query)
					elif event[0] == 'alarm':
						current = harm.get()
						self.enqueue(*[event for (time, event) in current])

						# schedule the next period
						p = harm.period()
						if p is not None:
							self.kernel.alarm(p // 1000)
					elif event[0] == 'recur':
						pass
					elif event[0] == 'file':
						pass
					else:
						# XXX: hazard
						raise RuntimeError(event) # unknown event type

	def enqueue(self, *tasks):
		"""
		Enqueue a task to be ran in the `Tasks` instance's thread.

		Enqueued tasks should return `None` or a Callable that will be enqueued.
		"""
		self._tq[self._tq_state[1]].extend(tasks)

		if self.kernel.waiting or not self._tq[self._tq_state[0]]:
			# If the _taskloop is in kernel.wait() or
			# the *current working queue* is empty, .force() has to be called.

			# Simultaneous enqueue() operations may perform superfluous kernel.force()
			# calls, but primarily in cases where the kernel has already been waiting.
			self.kernel.force()

	def __enqueue__(self, *tasks):
		"""
		Enqueue a task without signalling the task loop.
		"""
		self._tq[self._tq_state[1]].extend(tasks)

	def task(self, func, partial = functools.partial):
		"""
		Decorator that causes the invoked callable to be enqueued by the context.

		Example::

			context = fault.scheduling.library.Context()

			@context.task
			def method(...)
				...

			method(...) # enqueued call

		Module must be imported by Context acquisition.
		"""
		def wrapper(*args, **kw):
			return self._enq(func, *args, **kw)
		functools.update_wrapper(wrapper, func)
		return wrapper
