"""
# Executive processors.
"""
import os
import types
import collections
import functools

from . import core

class Call(core.Processor):
	"""
	# A single call represented as a Processor.

	# The callable is executed by process and signals its exit after completion.

	# Used as an abstraction to explicit enqueues, and trigger faults in Sectors.
	"""

	@classmethod
	def partial(Class, call:collections.abc.Callable, *args, **kw):
		"""
		# Create a call applying the arguments to the callable upon actuation.
		# The positional arguments will follow the &Sector instance passed as
		# the first argument.
		"""
		return Class(functools.partial(call, *args, **kw))

	def __init__(self, call:functools.partial):
		"""
		# The partial application to the callable to perform.
		# Usually, instantiating from &partial is preferrable;
		# however, given the presence of a &functools.partial instance,
		# direct initialization is better.

		# [ Parameters ]
		# /call/
			# The callable to enqueue during actuation of the &Processor.
		"""
		self.source = call

	def actuate(self):
		self.ctx_enqueue_task(self.execution)

	def execution(self, event=None, source=None):
		assert self.functioning

		try:
			self.product = self.source() # Execute Callable.
			self.termination_completed()
			self.exit()
		except BaseException as exc:
			self.product = None
			self.fault(exc)

	def structure(self):
		return ([('source', self.source)], ())

class Coroutine(core.Processor):
	"""
	# Processor for coroutines.

	# Manages the generator state in order to signal the containing &Sector of its
	# exit. Generator coroutines are the common method for serializing the dispatch of
	# work to relevant &Sector instances.
	"""

	def __init__(self, coroutine):
		self.source = coroutine

	@property
	def state(self):
		return self.unit.stacks[self]

	def _co_complete(self):
		super().terminate()
		self.controller.exited(self)

	@types.coroutine
	def container(self):
		"""
		# ! INTERNAL:
			# Private Method.

		# Container for the coroutine's execution in order
		# to map completion to processor exit.
		"""
		try:
			yield None
			self.product = (yield from self.source)
			self.enqueue(self._co_complete)
		except BaseException as exc:
			self.product = None
			self.fault(exc)

	def actuate(self, partial=functools.partial):
		"""
		# Start the coroutine.
		"""

		state = self.container()
		self.unit.stacks[self] = state

		self.enqueue(state.send)

	def terminate(self):
		"""
		# Force the coroutine to close.
		"""
		if not super().terminate():
			return False
		self.state.close()
		return True

	def interrupt(self):
		self.state.throw(KeyboardInterrupt)

class Thread(core.Processor):
	"""
	# A &Processor that runs a callable in a dedicated thread.
	"""

	def __init__(self, callable):
		self.callable = callable

	def trap(self):
		final = None
		try:
			self.callable(self)
			self.termination_started()
			# Must be enqueued to exit.
			final = self.exit
		except BaseException as exc:
			final = functools.partial(self.fault, exc)

		self.ctx_enqueue_task(final)

	def actuate(self):
		"""
		# Execute the dedicated thread for the transformer.
		"""

		self.context.execute(self, self.trap)

class Subprocess(core.Processor):
	"""
	# A Processor that represents a *set* of Unix subprocesses.

	# Primarily exists to map process exit events to processor exits and
	# management of subprocessor metadata such as the Process-Id of the child.
	"""

	def __init__(self, *pids):
		self.process_exit_events = {}
		self.active_processes = set(pids)

	def structure(self):
		p = [
			x for x in [
				('active_processes', self.active_processes),
				('process_exit_events', self.process_exit_events),
			] if x[1]
		]
		return (p, ())

	@property
	def only(self):
		"""
		# The exit event of the only Process-Id. &None or the pair (pid, exitcode).
		"""

		for i in self.process_exit_events:
			return i, self.process_exit_events.get(i)

		return None

	def sp_exit(self, pid, event):
		# Target of the system event, this may be executed in cases
		# where the Processor has exited.

		# Being that this is representation of a resource that is not
		# actually controlled by the Processor, it will continue
		# to update the state. However, the exit event will only
		# occur if the Sector is consistent.

		self.process_exit_events[pid] = event
		self.active_processes.discard(pid)

		if not self.active_processes:
			self.active_processes = ()
			self._pexe_state = -1

			# Don't exit if interrupted; maintain position in hierarchy.
			if not self.interrupted:
				self.exit()

	def sp_signal(self, signo, send_signal=os.kill):
		"""
		# Send the given signal number (os.kill) to the active processes
		# being managed by the instance.
		"""

		for pid in self.active_processes:
			send_signal(pid, signo)
	signal = sp_signal # REMOVE

	def signal_process_group(self, signo, send_signal=os.kill):
		"""
		# Like &signal, but send the signal to the process group instead of the exact process.
		"""

		for pid in self.active_processes:
			send_signal(-pid, signo)

	def actuate(self):
		"""
		# Initialize the system event callbacks for receiving process exit events.
		"""

		proc = self.context.process
		track = proc.kernel.track
		callback = self.sp_exit

		for pid in self.active_processes:
			try:
				track(pid)
				proc.system_event_connect(('process', pid), self, callback)
			except OSError as err:
				if err.errno != errno.ESRCH:
					raise
				# Doesn't exist or already exited. Try to reap.
				self.ctx_enqueue_task(functools.partial(callback, pid, execution.reap(pid)))

	def check(self):
		"""
		# Initialize the system event callbacks for receiving process exit events.
		"""

		proc = self.context.process
		reap = execution.reap
		untrack = proc.kernel.untrack
		callback = self.sp_exit

		# Validate that the process exists; it may have exited before .track() above.
		# Apparently macos has a race condition here and a process that has exited
		# prior to &track will not get the event. This loop checks to make sure
		# that the process exists and whether or not it has exit status.
		finished = False
		proc_set = iter(list(self.active_processes))
		while not finished:
			try:
				for pid in proc_set:
					os.kill(pid, 0) # Looking for ESRCH errors.

					d = reap(pid)
					if not d.running:
						untrack(pid)
						proc.system_event_disconnect(('process', pid))
						self.sp_exit(pid, d)
						continue
				else:
					finished = True
			except OSError as err:
				if err.errno != errno.ESRCH:
					raise
				untrack(pid)
				proc.system_event_disconnect(('process', pid))
				self.sp_exit(pid, reap(pid))

	def terminate(self, by=None):
		"""
		# If the process set isn't terminating, issue SIGTERM
		# to all of the currently running processes.
		"""

		if not self.terminating:
			super().terminate(by=by)
			self.sp_signal(15)

	def interrupt(self, by=None, send_signal=os.kill):
		"""
		# Interrupt the running processes by issuing a SIGKILL signal.
		"""

		for pid in self.active_processes:
			try:
				send_signal(pid, 9)
			except ProcessLookupError:
				pass

	def abort(self, by=None):
		"""
		# Interrupt the running processes by issuing a SIGQUIT signal.
		"""

		r = super().interrupt(by)
		self.sp_signal(signal.SIGQUIT)
		return r
