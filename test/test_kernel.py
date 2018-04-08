import os
import time
from .. import kernel as library
kernel = library

def test_alarm_units(test):
	kif = kernel.Interface()
	try:
		kif.alarm(1, 0, 'n')
		kif.alarm(2, 0, 's')
		kif.alarm(3, 0, 'm')
		kif.alarm(4, 0, 'u')
		with test/TypeError:
			kif.alarm(5, 0, 492492)
		with test/TypeError:
			kif.alarm(6, 0, 'microsecond')
		with test/ValueError:
			kif.alarm(7, 0, 'f')

		test/len(kif.wait()) == 4
	finally:
		kif.void()
		test.garbage()

def test_alarm(test):
	kif = kernel.Interface()
	try:
		ob = "foobar"
		kif.alarm(ob, 1, 'n')
		test/kif.wait() << ('alarm', ob)
	finally:
		kif.void()
		test.garbage()

def test_alarm_time(test):
	kif = kernel.Interface()
	try:
		ob = "foobar"
		a=time.time()
		kif.alarm(ob, 1, 's')
		test/kif.wait() << ('alarm', ob)
		b=time.time()
		test/(b-a-1) < 0.3
	finally:
		kif.void()
		test.garbage()

def test_ignore_force(test):
	kif = kernel.Interface()
	try:
		ob = "foobar"
		a=time.time()
		kif.alarm(ob, 1200, 'm')
		kif.force()
		# forced while not waiting outside block validate that it's not drop through.
		kif.wait()
		b=time.time()
		test/(b-a) >= 1
	finally:
		kif.void()
		test.garbage()

def test_force(test):
	kif = kernel.Interface()
	try:
		ob = "foobar"
		a=time.time()
		kif.alarm(ob, 5, 's')
		test/kif.force() == None
		with kif:
			test/kif.force() == True
			kif.force()
			# signals that it was already tripped
			test/kif.force() == False
			test/kif.force() == False
			# forced while not waiting outside block validate that it's not drop through.
			kif.wait()
		test/kif.force() == None
		b=time.time()
		test/(b-a) < 5
	finally:
		kif.void()
		test.garbage()

def test_recur(test):
	kif = kernel.Interface()
	try:
		ob = "foo"
		a=time.time()
		# recur about 500ms
		kif.recur(ob, 100, 'm')
		for x in range(5):
			test/kif.wait() << ('recur', ob)
		b=time.time()
		# approx half a second
		test/(b-a) < 0.8

		# cancellation
		kif.cancel(ob)
		with kif:
			kif.force()
			test/kif.wait() == []
	finally:
		kif.void()
		test.garbage()

def test_track(test):
	import os
	r, w = os.pipe()
	def child(fd = r):
		i = os.read(fd, 1)
		os._exit(3)

	kif = kernel.Interface()
	try:
		pid = os.fork()

		if pid == 0:
			child()
		else:
			kif.track(pid)
			os.write(w, b'f')
		with kif:
			r = kif.wait()
		test/r[0] == ('process', pid, None)
		_, status = os.waitpid(pid, os.P_WAIT)
		test/os.WIFEXITED(status) == True
		test/os.WEXITSTATUS(status) == 3
	finally:
		kif.void()
		test.garbage()

if __name__ == '__main__':
	import sys; from ...test import library as libtest
	libtest.execute(sys.modules[__name__])
