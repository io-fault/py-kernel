import collections
import functools
import typing
import itertools

from .. import dispatch as module
from .. import core
from .. import flows
from . import library as testlib

def test_Call(test):
	Type = module.Call
	ctx, sect = testlib.sector()

	arg = object()
	kw = object()

	effects = []
	def call_to_perform(arg1, key=None):
		effects.append(arg1)
		effects.append(key)
		effects.append('called')

	c = Type.partial(call_to_perform, arg, key=kw)
	sect.dispatch(c)

	ctx()

	test/effects[0] == arg
	test/effects[1] == kw
	test/effects[-1] == 'called'

def test_Coroutine(test):
	"""
	# Evaluate the functions of a &module.Coroutine process;
	# notably the continuations and callback registration.
	"""
	Type = module.Coroutine
	ctx, sect = testlib.sector()
	return

	effects = []

	@typing.coroutine
	def coroutine_to_execute(sector):
		yield None
		effects.append(sector)
		effects.append('called')

	co = Type(coroutine_to_execute)
	sect.dispatch(co)
	ctx()

	test/effects[-1] == 'called'
	test/effects[0] == sect

class SPTestSystem(object):
	def connect_process_exit(self, proc, cb, *procs):
		pass

class TestSubprocess(module.Subprocess):
	def actuate(self):
		system = SPTestSystem()
		self.system = system

		self._signals = []
		super().actuate()

	def sp_signal(self, signo):
		self._signals.append(signo)

def test_Subprocess_termination(test):
	"""
	# - &module.Subprocess

	# Validate that process exits block termination.
	# The subclasses are used for injections to avoid real system processes.
	"""
	ctx, S = testlib.sector()
	reap = (lambda x: -x)

	##
	# Termination on process exit.
	sp = TestSubprocess(reap, {1: None})

	xact = core.Transaction.create(sp)
	S.dispatch(xact)
	test/sp.sp_waiting == {1}

	sp.sp_exit(1)
	test/sp.sp_reaped == True
	ctx(2)
	test/sp.terminated == True
	test/xact.terminated == True

	##
	# Termination on subtransaction exit.
	ctx, S = testlib.sector()
	sp = TestSubprocess(reap, {2: None})

	xact = core.Transaction.create(sp)
	S.dispatch(xact)
	subxact = (core.Transaction.create(core.Context()))
	xact.dispatch(subxact)
	test/sp.sp_waiting == {2}

	sp.sp_exit(2)
	test/sp.sp_reaped == True
	ctx(2)
	test/sp.terminated == False
	test/xact.terminated == False

	# xact_void triggers termination
	subxact.terminate()
	ctx(2)
	test/sp.terminated == True
	test/xact.terminated == True

	##
	# Termination on second process exit.
	ctx, S = testlib.sector()
	sp = TestSubprocess(reap, dict({3: None, 4: None}))

	xact = core.Transaction.create(sp)
	S.dispatch(xact)
	subxact = (core.Transaction.create(core.Context()))
	xact.dispatch(subxact)

	test/sp.sp_reaped == False
	test/sp.sp_waiting == {3, 4}
	sp.sp_exit(3)
	ctx(2)
	test/sp.sp_reaped == False
	test/sp.terminated == False
	test/xact.terminated == False
	test/sp.sp_waiting == {4}

	subxact.terminate()
	test/sp.terminated == False
	test/xact.terminated == False

	sp.sp_exit(4)
	test/sp.sp_waiting == set()
	ctx(2)
	test/sp.terminated == True
	test/xact.terminated == True

def test_Subprocess_only_status(test):
	"""
	# - &module.Subprocess.sp_only
	"""
	ctx, S = testlib.sector()
	reap = (lambda x: -x)

	##
	# Termination on process exit.
	sp = TestSubprocess(reap, {1: None})

	xact = core.Transaction.create(sp)
	S.dispatch(xact)
	test/sp.sp_only == None
	sp.sp_exit(1)
	ctx(2)
	test/sp.sp_only == -1

	##
	# Termination on second process exit.
	ctx, S = testlib.sector()
	sp = TestSubprocess(reap, dict({3: None, 4: None}))

	xact = core.Transaction.create(sp)
	S.dispatch(xact)

	test/sp.sp_only == None
	sp.sp_exit(3)
	ctx(2)
	test/sp.sp_only == None
	sp.sp_exit(4)
	ctx(2)
	test/sp.sp_only == None

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules['__main__'])
