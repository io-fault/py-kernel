import os
import _thread
from ... import system

class EMatrix(system.Matrix):
	def _err(self, *args):
		self.errlist.append(args)

	@staticmethod
	def _exe(ignored, target, *args):
		return _thread.start_new_thread(target, args)

	def __init__(self):
		super().__init__(self._err, (lambda x: x()), self._exe)

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
	T.acquire(b'---')
	T.mslice = slice(0,3)
	d = system.Delta.snapshot(T)
	test/d.terminal == True
	test/d.payload == b'---'
	test/d.demand == None
	test.isinstance(str(d), str)
	test/d.endpoint == "END"

	T = Channel()
	T.polarity = -1
	T.acquire(b'...')
	T.exhausted = True
	T.mslice = slice(0,3)
	d = system.Delta.snapshot(T)
	test/d.terminal == False
	test/d.payload == b'...'
	test/d.demand == T.acquire
	test.isinstance(str(d), str)
	test/d.endpoint == None

def test_matrix_empty(test):
	ix = EMatrix()
	test/len(ix.arrays) == 0
	test.isinstance(repr(ix), str)

def test_matrix_termination(test):
	ix = EMatrix()

	r, w = os.pipe()
	ix.acquire([
		system.io.alloc_input(r),
		system.io.alloc_output(w),
	])
	ix.terminate()

def test_idle_array_terminates(test):
	"""
	# Validate inactive termination.
	"""
	import time

	loop = 0
	ix = EMatrix()
	try:
		ix._alloc()
		test/len(ix.arrays) == 1

		while ix.arrays:
			ix.force()
			time.sleep(0.00000001)

			if loop > 256:
				test.fail("I/O array did not exit within the expected cycles")
			else:
				loop += 1

		test/len(list(ix.arrays)) == 0
	finally:
		ix.terminate()

def test_active_array_continues(test):
	"""
	# Validate active maintenance.
	"""
	import time

	loops = 0
	j = None
	def incloops(self, x):
		nonlocal loops
		loops += 1
		self.force()

	def testevents(self, err, events):
		test/events == None

	class TMatrix(EMatrix):
		io_collect = incloops
		io_deliver = testevents

	ix = TMatrix()
	try:
		ix._alloc()
		r, w = os.pipe()
		r = system.io.alloc_input(r)
		w = system.io.alloc_output(w)
		ix.acquire([r, w])

		# we use j.force to rapidly trip the countdown.
		# there are channels, so we should never break;
		# rather the loop condition should fail.
		ix.force()
		while loops < 256:
			# encourage switch
			if not list(ix.arrays):
				break
		test/list(ix.arrays) != []

		ix.terminate()

		while list(ix.arrays):
			time.sleep(0.000001)
		test/w.terminated == True
		test/r.terminated == True
	finally:
		ix.terminate()

def test_matrix_transfer(test):
	ix = EMatrix()
	try:
		r, w = os.pipe()
		r = system.io.alloc_input(r)
		w = system.io.alloc_output(w)
		ix.acquire([r, w])

		buf = bytearray(60)
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
			ix.force()

		r, w = os.pipe()
		r = system.io.alloc_input(r)
		w = system.io.alloc_output(w)
		ix.acquire([r, w])

		# Couple cycles should trigger the exit_at_zero reset.
		ix.force()
		ix.force()
		r.terminate()
		w.terminate()

		while not list(ix.arrays):
			ix.force()
		test/bytes(buf) == b'4' * 60
	finally:
		ix.terminate()

def test_alloc_single_matrix(test):
	# single channel allocations have a distinct branch
	import time
	ix = EMatrix()
	try:
		r = os.open('/dev/zero', os.O_RDONLY)
		r2 = os.open('/dev/zero', os.O_RDONLY)
		r = system.io.alloc_input(r)
		r2 = system.io.alloc_input(r2)
		ix.acquire([r, r2])

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
	ix = EMatrix()
	ix.channels_per_array = 0
	try:
		tset = []
		for i in range(20):
			r, w = os.pipe()
			tset.append(system.io.alloc_input(r))
			tset.append(system.io.alloc_output(w))

		ix.acquire(tset)

		# checking for per array limits
		# ix.acquire allows the entire overflow to spill into the new array.
		test/len(list(ix.arrays)) == 2
	finally:
		ix.terminate()

def test_matrix_void(test):
	ix = EMatrix()
	# empty, safe to run.
	ix.void()
	# XXX: needs to be tested in a fork

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
