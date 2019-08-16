import os
from ... import system

def test_adapter_properties(test):
	a = system.Adapter.create("endpoint", "transformer")
	test/a.endpoint == "endpoint"
	test/a.transformer == "transformer"

def test_delta(test):
	d = system.Delta.construct()
	test/d.endpoint == None
	test/d.terminal == False
	test/d.demand == None
	test/d.payload == None
	test.isinstance(repr(d), str)
	test.isinstance(str(d), str)

	class Channel(object):
		def __init__(self):
			self.polarity = 1
			self.terminated = False
			self.resource = None
			self.mslice = None
			self.exhausted = False
			self.port = None
			self.mendpoint = None

		def slice(self):
			return self.mslice

		def transfer(self):
			return self.resource[self.mslice]

		def sizeof_transfer(self):
			return self.mslice.stop - self.mslice.start

		def acquire(self, res):
			self.resource = res
			return self

		def endpoint(self):
			return self.mendpoint

	T = Channel()
	T.mendpoint = "END"
	T.terminated = True
	T.acquire(b'foo')
	T.mslice = slice(0,3)
	d = system.Delta.snapshot(T)
	test/d.terminal == True
	test/d.payload == b'foo'
	test/d.demand == None
	test.isinstance(str(d), str)
	test/d.endpoint == "END"

	T = Channel()
	T.polarity = -1
	T.acquire(b'bar')
	T.exhausted = True
	T.mslice = slice(0,3)
	d = system.Delta.snapshot(T)
	test/d.terminal == False
	test/d.payload == b'bar'
	test/d.demand == T.acquire
	test.isinstance(str(d), str)
	test/d.endpoint == None

def new():
	l = []
	def add(x, l = l):
		l.append(x)
	a = system.Adapter(add, system.Delta.construct)
	return l, a

def test_matrix_repr(test):
	l, a = new()
	test.isinstance(repr(system.Matrix(a)), str)

def test_matrix_empty(test):
	l, a = new()
	ix = system.Matrix(a)
	'system' in test/ix.routes
	test/len(ix.arrays) == 0

def test_matrix_routes(test):
	l, a = new()
	ix = system.Matrix(a)
	ix.route(foo = 'bar')
	test/ix.routes['foo'] == 'bar'

def test_matrix_termination(test):
	def null(x):
		pass
	ix = system.Matrix((null, null))
	with ix.xact() as alloc:
		r, w = os.pipe()
		alloc('octets://acquire/input', r)
		alloc('octets://acquire/output', w)
	ix.terminate()

def test_idle_array_terminates(test):
	import time

	# we use the adapter's callbacks to increment our counter and to trip j.force()
	loops = 0
	def incloops(x):
		nonlocal loops
		loops += 1
		#test/isinstance(x, io.Array) == True
		test/list(x.transfer()) == []
		x.force()

	def testevents(events):
		test/events == None

	adapter = (testevents, incloops)

	ix = system.Matrix(adapter)
	try:
		ix._get() # kicks off the array's thread

		# we use j.force to rapidly trip the countdown.
		# there are no channels, so we should be able to trigger it quickly
		ix.force()
		while loops < 128:
			# encourage switch
			time.sleep(0.00001)
			if len(list(ix._iterarrays())) == 0:
				break

		test/len(list(ix._iterarrays())) == 0
	finally:
		ix.terminate()

def test_active_array_continues(test):
	import time

	# in the previous test, we validate that the thread terminates an idle array.

	# in this test, we want to validate the inverse, an active array
	# is never terminated

	loops = 0
	j = None
	def incloops(x):
		nonlocal loops
		loops += 1
		#test/isinstance(x, io.Array) == True
		x.force()

	def testevents(events):
		test/events == None

	adapter = (testevents, incloops)

	ix = system.Matrix(adapter)
	try:
		ix._get() # kicks off the array's thread
		with ix.xact() as st:
			r, w = os.pipe()
			r = st('octets://acquire/input', r)
			w = st('octets://acquire/output', w)

		# we use j.force to rapidly trip the countdown.
		# there are channels, so we should never break;
		# rather the loop condition should fail.
		ix.force()
		while loops < 256:
			# encourage switch
			if not list(ix._iterarrays()):
				break
		test/list(ix._iterarrays()) != []

		ix.terminate()

		while list(ix._iterarrays()):
			time.sleep(0.000001)
		test/w.terminated == True
		test/r.terminated == True
	finally:
		ix.terminate()

def test_matrix_transfer(test):
	l, a = new()
	ix = system.Matrix(a)
	try:
		with ix.xact() as alloc:
			r, w = os.pipe()
			r = alloc('octets://acquire/input', r)
			w = alloc('octets://acquire/output', w)

		buf = r.rallocate(60)
		r.acquire(buf)
		w.acquire(b'4' * 60)
		while not w.exhausted or not r.exhausted:
			pass
		r.terminate()
		w.terminate()
		while not w.terminated or not r.terminated:
			pass

		# trigger the array recovery code
		for x in range(8):
			ix.force(a)

		with ix.xact() as alloc:
			r, w = os.pipe()
			r = alloc('octets://acquire/input', r)
			w = alloc('octets://acquire/output', w)
		# Couple cycles should trigger the exit_at_zero reset.
		ix.force()
		ix.force()
		r.terminate()
		w.terminate()

		while not list(ix._iterarrays()):
			ix.force()
		test/bytes(buf) == b'4' * 60
	finally:
		ix.terminate()

def test_alloc_single_matrix(test):
	# single channel allocations have a distinct branch
	import time
	l, a = new()
	ix = system.Matrix(a)
	try:
		with ix.xact() as alloc:
			r = alloc('octets://acquire/input', os.open('/dev/zero', os.O_RDONLY))
			r2 = alloc('octets://acquire/input', os.open('/dev/zero', os.O_RDONLY))

		r.acquire(bytearray(b'\xFF'*10))
		r2.acquire(bytearray(b'\xFF'*10))

		r.force()
		while not r.exhausted:
			time.sleep(0.0001)

		r2.force()
		while not r2.exhausted:
			time.sleep(0.0001)
		r.terminate()
	finally:
		ix.terminate()

def test_matrix_overflow(test):
	"""
	# Test the effect of the limit attribute.
	"""
	l, a = new()
	ix = system.Matrix(a)
	ix.channels_per_array = 0
	try:
		with ix.xact() as alloc:
			for i in range(10):
				r, w = os.pipe()
				r = alloc('octets://acquire/input', r)
				w = alloc('octets://acquire/output', w)

		# checking for per array limits
		# ix.acquire allows the entire overflow to spill into the new array.
		test/len(list(ix._iterarrays())) == 2
	finally:
		ix.terminate()

def test_matrix_void(test):
	l, a = new()
	ix = system.Matrix(a)
	# empty, safe to run.
	ix.void()
	# XXX: needs to be tested in a fork

def test_matrix_xact_fail(test):
	"""
	# .xact() context block that raises an exception
	"""
	l, a = new()

	ix = system.Matrix(a)
	# empty, safe to run.
	try:
		with test/Exception as e:
			with ix.xact() as alloc:
				r = alloc('octets://acquire/input', os.open('/dev/zero', os.O_RDONLY))
				raise Exception("error-string")
		test/r.terminated == True
	finally:
		ix.terminate()

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
