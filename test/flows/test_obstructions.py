"""
# Validate the operation of obstructing flows.
"""
from ... import flows

def test_Flow_operation(test):
	# base class transformers emit what they're given to process
	f = flows.Channel()
	end = flows.Collection.list()
	f.f_connect(end)

	endpoint = end.c_storage
	f.actuate()
	end.actuate()

	f.f_transfer("event")
	test/endpoint == ["event"]

	f.f_transfer("event2")
	test/endpoint == ["event", "event2"]

def test_Flow_obstructions(test):
	"""
	# Validate signaling of &flows.Flow obstructions.
	"""

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = flows.Channel()
	f.f_watch(obstructed, cleared)

	f.f_obstruct(test, None)

	test/f.f_obstructed == True
	test/status == [True]

	f.f_obstruct(f, None)
	test/f.f_obstructed == True
	test/status == [True]

	f.f_clear(f)
	test/f.f_obstructed == True
	test/status == [True]

	f.f_clear(test)
	test/f.f_obstructed == False
	test/status == [True, False]

def test_Flow_obstructions_initial(test):
	"""
	# Validate obstruction signaling when obstruction is presented before the watch.
	"""

	status = []
	def obstructed(flow):
		status.append(True)

	def cleared(flow):
		status.append(False)

	f = flows.Channel()
	f.actuate()
	f.f_obstruct(test, None)

	f.f_watch(obstructed, cleared)

	test/f.f_obstructed == True
	test/status == [True]

def test_Flow_obstructions(test):
	"""
	# Validate that joins receive obstruction notifications.
	"""

	l = []
	def suspend(flow):
		l.append('suspend')

	def resume(flow):
		l.append('resume')

	f = flows.Channel()
	f.f_watch(suspend, resume)
	f.actuate()

	f.f_obstruct(test, None)
	test/l == ['suspend']

	f.f_clear(test)
	test/l == ['suspend', 'resume']
	f.f_clear(test) # no op
	test/l == ['suspend', 'resume']

	f.f_obstruct(test, None)
	test/l == ['suspend', 'resume', 'suspend',]
	f.f_obstruct(test, None) # no op; already obstructed.
	test/l == ['suspend', 'resume', 'suspend',]

if __name__ == '__main__':
	import sys; from ....test import library as libtest
	libtest.execute(sys.modules['__main__'])
