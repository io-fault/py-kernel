import sys
from .. import libservice as library

def test_service_routes(test):
	tr = test.exits.enter_context(library.libroutes.File.temporary())
	for i in range(12):
		sr = tr / ('s'+str(i))
		sr.init("directory")

	s = set(['s'+str(i) for i in range(12)])

	for bn, r in library.service_routes(tr):
		test/(bn in s) == True

def test_Service(test):
	tr = test.exits.enter_context(library.libroutes.File.temporary())
	# create, store/load and check empty

	srv = library.Service(tr, "test-service")
	libs = srv.libraries = {
		'libsomething': 'module.path.something'
	}

	srv.store()
	srv.load()

	test/srv.libraries == libs
	test/srv.actuates == False
	test/srv.parameters == []
	test/srv.environment == {}

	# modify and store, then create new service to compare
	enabled = srv.actuates = True
	params = srv.parameters = ['--long-param', 'some', 'parameter']
	docs = srv.abstract = "SOME DOCUMENTATION"
	env = srv.environment = {"ENV1" : "VALUE1", "ENV2": "VALUE2"}
	exe = srv.executable = "/sbin/somed"

	srv.store()

	srv2 = library.Service(tr, "test-service")
	srv2.load()
	test/srv2.executable == exe
	test/srv2.environment == env
	test/srv2.abstract == docs
	test/srv2.parameters == params
	test/srv2.actuates == enabled
	test/srv2.actuates == True

	# check the alteration.
	srv.actuates = False
	srv.store_actuation()
	srv2.load_actuation()
	test/srv2.actuates == False

if __name__ == '__main__':
	import sys
	from ...development import libtest
	libtest.execute(sys.modules[__name__])
